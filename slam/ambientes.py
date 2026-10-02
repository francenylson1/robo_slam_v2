"""
slam/ambientes.py
O PACOTE DE AMBIENTE: cada lugar mapeado (sala, corredor, quadra do evento) é
uma pasta com tudo o que o robô precisa para navegar ali, e o operador escolhe
qual usar.

DECISÕES (02/10/2026, docs/PRD.md §0 e §7; página da conversa de desenho:
https://claude.ai/artifact/3cqZvZGfP4wXKzLiudAaUJ):
  - escolhe-se no dashboard do robô 1, com login (página "Ambientes");
  - a troca é RECUSADA com missão em curso, editor de áreas aberto, robô
    andando ou modo mapeamento;
  - a troca grava o ativo.json e REINICIA o serviço (decisão 7): tudo sobe do
    zero com o pacote novo, sem sobrar fita, áreas ou base do anterior;
  - depois da troca, missão só depois de "Localizar na fita";
  - cada ambiente tem a sua fita física;
  - mapa novo = pacote novo; nada é sobrescrito. Arquiva-se, não se apaga.

FORMATO (data/ambientes/ — fora do git: é dado do robô, não código):
  ativo.json                {"id": "...", "quem": "...", "quando": "..."}
  <id>/ficha.json           {"id", "nome", "criado", "quem", "mapa_sha256",
                             "fita": [x, y, rumo] | null, "arquivado": bool}
  <id>/mapa.stcm            o mapa do Aurora
  <id>/planta.json + .png   gerada do mapa (scripts/aurora_planta.py --pacote)
  <id>/nav/                 áreas proibidas e POIs (slam/mapa_nav.py), com histórico
A fita é o PONTO DO AURORA medido, como sempre foi (main.py converte para o
centro com o braço do robô). O braço, a margem e as tolerâncias são do ROBÔ e
continuam no config/settings.py.

O ESTADO é calculado, nunca digitado:
  invalido  — sem ficha, sem mapa, ou o mapa não confere com a ficha (sha);
  rascunho  — mapa certo, mas falta a planta (do mesmo sha), a fita, ou o
              desenho de áreas/POIs salvo ao menos uma vez (B5, 02/10);
  pronto    — tudo conferido: aceita missão.

Nada aqui move o robô: é só arquivo e conferência.
"""

import json
import logging
import os
import re
import shutil
import threading
import time

from sensors.aurora_pose import sha256_arquivo

log = logging.getLogger(__name__)

_ID_OK = re.compile(r"^[A-Za-z0-9_-]{1,40}$")
ATIVO = "ativo.json"


def _ler_json(caminho):
    try:
        with open(caminho, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _gravar_json(caminho, doc):
    """Gravação atômica: um desligamento no meio não deixa arquivo pela metade."""
    tmp = caminho + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(doc, f, indent=2, ensure_ascii=False)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, caminho)


def _fita_ok(fita) -> bool:
    return (isinstance(fita, (list, tuple)) and len(fita) == 3
            and all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in fita))


# ─────────────────────────────────────────────
class Ambientes:

    def __init__(self, raiz: str, sha_fn=sha256_arquivo):
        self.raiz    = os.path.abspath(raiz)
        self._sha_fn = sha_fn
        self._cache  = {}                 # caminho → (mtime, tamanho, sha)
        self._lock   = threading.Lock()

    # ─── caminhos ─────────────────────────────
    def existe(self) -> bool:
        return os.path.isdir(self.raiz)

    def _pasta(self, pid):
        if not isinstance(pid, str) or not _ID_OK.match(pid):
            return None
        return os.path.join(self.raiz, pid)

    def caminhos(self, pid) -> dict | None:
        p = self._pasta(pid)
        if p is None:
            return None
        return {"pasta": p,
                "ficha": os.path.join(p, "ficha.json"),
                "mapa": os.path.join(p, "mapa.stcm"),
                "planta_json": os.path.join(p, "planta.json"),
                "nav_dir": os.path.join(p, "nav")}

    def ids(self) -> list[str]:
        if not self.existe():
            return []
        return sorted(n for n in os.listdir(self.raiz)
                      if _ID_OK.match(n) and os.path.isdir(os.path.join(self.raiz, n)))

    def _sha(self, caminho):
        """sha256 com cache por (mtime, tamanho): o .stcm tem até 60 MB."""
        st = os.stat(caminho)
        chave = (st.st_mtime_ns, st.st_size)
        c = self._cache.get(caminho)
        if c and c[:2] == chave:
            return c[2]
        sha = self._sha_fn(caminho)
        self._cache[caminho] = (*chave, sha)
        return sha

    # ─── avaliação ────────────────────────────
    def avaliar(self, pid) -> dict:
        """Estado de um pacote. Nunca levanta exceção."""
        r = {"id": pid, "nome": pid, "estado": "invalido", "motivos": [],
             "arquivado": False, "criado": None, "quem": None,
             "mapa_sha256": None, "fita": None}
        c = self.caminhos(pid)
        if c is None:
            r["motivos"].append("nome de ambiente inválido")
            return r
        ficha = _ler_json(c["ficha"])
        if not isinstance(ficha, dict):
            r["motivos"].append("ficha ausente ou ilegível")
            return r
        r.update(nome=str(ficha.get("nome") or pid), arquivado=bool(ficha.get("arquivado")),
                 criado=ficha.get("criado"), quem=ficha.get("quem"),
                 mapa_sha256=ficha.get("mapa_sha256"))
        # Os mapas dos C1 (Etapa B.2): não entram no "pronto" do robô 1, que
        # navega pelo Aurora; servem aos robôs sem Aurora. Só um resumo.
        c1 = ficha.get("c1") if isinstance(ficha.get("c1"), dict) else None
        if c1:
            nt = c1.get("nota") or {}
            r["c1"] = {"tem_145": bool(c1.get("1,45 m")), "tem_22": bool(c1.get("22 cm")),
                       "nota_145_cm": (nt.get("1,45 m") or {}).get("mediana_cm"),
                       "nota_juntos_cm": (nt.get("os dois") or {}).get("mediana_cm")}
        else:
            r["c1"] = None
        if not os.path.isfile(c["mapa"]):
            r["motivos"].append("mapa ausente")
            return r
        try:
            sha = self._sha(c["mapa"])
        except OSError as e:
            r["motivos"].append(f"mapa ilegível: {e}")
            return r
        if sha != ficha.get("mapa_sha256"):
            r["motivos"].append("o mapa não confere com a ficha (sha diferente)")
            return r
        planta = _ler_json(c["planta_json"])
        if not isinstance(planta, dict):
            r["motivos"].append("planta não gerada")
        elif planta.get("mapa_sha256") != sha:
            r["motivos"].append("a planta é de outro mapa (sha diferente)")
        if _fita_ok(ficha.get("fita")):
            r["fita"] = [float(v) for v in ficha["fita"]]
        else:
            r["motivos"].append("fita não medida")
        # B5 (02/10/2026): pronto só depois de alguém salvar o desenho no
        # /mapa pelo menos uma vez — mesmo sem nenhuma área. É a confirmação
        # de que alguém olhou as mesas daquele lugar.
        nav = _ler_json(os.path.join(c["nav_dir"], "nav.json"))
        if not (isinstance(nav, dict) and nav.get("mapa_sha256") == sha
                and isinstance(nav.get("versao"), int) and nav["versao"] >= 1):
            r["motivos"].append("desenho de áreas e POIs ainda não salvo no /mapa")
        r["estado"] = "rascunho" if r["motivos"] else "pronto"
        return r

    def listar(self) -> list[dict]:
        ativo = self.id_ativo()
        out = []
        for pid in self.ids():
            a = self.avaliar(pid)
            a["ativo"] = pid == ativo
            a["sha_curto"] = (a["mapa_sha256"] or "")[:8]
            out.append(a)
        return out

    # ─── o ativo ──────────────────────────────
    def id_ativo(self):
        doc = _ler_json(os.path.join(self.raiz, ATIVO))
        pid = doc.get("id") if isinstance(doc, dict) else None
        c = self.caminhos(pid)
        if c is None or not os.path.isdir(c["pasta"]):
            return None
        return pid

    def ativo(self) -> dict | None:
        """O pacote ativo (estado + caminhos), ou None se não houver um."""
        pid = self.id_ativo()
        if pid is None:
            return None
        a = self.avaliar(pid)
        c = self.caminhos(pid)
        a.update(mapa=c["mapa"], planta_json=c["planta_json"], nav_dir=c["nav_dir"])
        return a

    def pedir_troca(self, pid, quem, *, missao_ativa, editando, andando,
                    mapeando=False) -> tuple[bool, str]:
        """Troca o ambiente ativo. Quem chama reinicia o serviço se der certo."""
        if missao_ativa:
            return False, "há uma missão em curso — termine ou pare antes de trocar"
        if editando:
            return False, "o editor de áreas está aberto — feche antes de trocar"
        if mapeando:
            return False, "o robô está em modo mapeamento — conclua antes de trocar"
        if andando:
            return False, ("o robô precisa estar parado para trocar de ambiente "
                           "(depois do joystick, espere uns segundos)")
        c = self.caminhos(pid)
        if c is None or not os.path.isdir(c["pasta"]):
            return False, f"o ambiente '{pid}' não existe"
        with self._lock:
            if pid == self.id_ativo():
                return False, "este ambiente já está ativo"
            a = self.avaliar(pid)
            if a["arquivado"]:
                return False, f"o ambiente {a['nome']} está arquivado"
            if a["estado"] == "invalido":
                return False, (f"o ambiente {a['nome']} está inválido: "
                               + "; ".join(a["motivos"]))
            _gravar_json(os.path.join(self.raiz, ATIVO),
                         {"id": pid, "quem": quem,
                          "quando": time.strftime("%Y-%m-%d %H:%M:%S")})
        log.info(f"[Ambientes] Ativo agora: {pid} ({a['estado']}), por {quem}.")
        return True, f"ambiente {a['nome']} ativo ({a['estado']})"

    def arquivar(self, pid, quem, arquivar: bool = True) -> tuple[bool, str]:
        c = self.caminhos(pid)
        if c is None or not os.path.isdir(c["pasta"]):
            return False, f"o ambiente '{pid}' não existe"
        with self._lock:
            if arquivar and pid == self.id_ativo():
                return False, "não dá para arquivar o ambiente ativo"
            ficha = _ler_json(c["ficha"])
            if not isinstance(ficha, dict):
                return False, "ficha ausente ou ilegível"
            ficha["arquivado"] = bool(arquivar)
            _gravar_json(c["ficha"], ficha)
        log.info(f"[Ambientes] {pid} {'arquivado' if arquivar else 'reativado'} por {quem}.")
        return True, "arquivado" if arquivar else "reativado"


# ─────────────────────────────────────────────
# O QUE O SERVIÇO USA NA PARTIDA
# ─────────────────────────────────────────────
def resolver(amb: Ambientes, legado: dict) -> dict:
    """
    Mapa, sha, fita (ponto do Aurora), planta e pasta das áreas com que o
    serviço sobe, mais o motivo de a missão estar indisponível (ou None).

    Sem a pasta de ambientes (antes da migração), vale a configuração antiga
    do settings — o robô continua como estava. Com a pasta, vale SÓ o pacote:
    sem ativo, ou inválido, não há mapa e a missão fica indisponível; o
    joystick continua (fail-soft, como a bateria sem sensor).
    """
    if not amb.existe():
        return dict(legado, missao_motivo=None,
                    ambiente={"id": None, "nome": "configuração antiga (sem pacotes)",
                              "estado": "legado"})
    a = amb.ativo()
    vazio = {"mapa": None, "mapa_sha256": None, "fita": None,
             "planta_json": None, "nav_dir": None}
    if a is None:
        return dict(vazio, missao_motivo="nenhum ambiente ativo — escolha um em Ambientes",
                    ambiente={"id": None, "nome": "nenhum", "estado": "nenhum"})
    resumo = {"id": a["id"], "nome": a["nome"], "estado": a["estado"],
              "motivos": a["motivos"]}
    if a["estado"] == "invalido":
        return dict(vazio, ambiente=resumo,
                    missao_motivo=f"ambiente {a['nome']} inválido: " + "; ".join(a["motivos"]))
    r = {"mapa": a["mapa"], "mapa_sha256": a["mapa_sha256"],
         "fita": tuple(a["fita"]) if a["fita"] else None,
         "planta_json": a["planta_json"], "nav_dir": a["nav_dir"], "ambiente": resumo,
         "missao_motivo": None}
    if a["estado"] == "rascunho":
        r["missao_motivo"] = f"ambiente {a['nome']} é rascunho: " + "; ".join(a["motivos"])
    return r


# ─────────────────────────────────────────────
# MIGRAÇÃO (uma vez, na Pi): scripts/migrar_ambientes.py
# ─────────────────────────────────────────────
def migrar(raiz: str, legado: dict, extras=()) -> list[str]:
    """
    Cria os pacotes a partir dos arquivos de hoje, COPIANDO (nada é movido).
    O 'legado' vira o ambiente ativo se ainda não houver um. Pacote que já
    existe não é tocado: rodar de novo não muda nada.
    Cada item: {"id", "nome", "mapa", "mapa_sha256", "planta_json"|None,
                "nav_dir"|None, "fita"|None}.
    """
    os.makedirs(raiz, exist_ok=True)
    amb = Ambientes(raiz)
    feitos = []
    for item in [legado, *extras]:
        c = amb.caminhos(item["id"])
        if c is None:
            raise ValueError(f"id inválido: {item['id']!r}")
        if os.path.isdir(c["pasta"]):
            feitos.append(f"{item['id']}: já existe — não mexi")
            continue
        sha = sha256_arquivo(item["mapa"])
        if sha != item["mapa_sha256"]:
            raise ValueError(f"{item['id']}: o mapa {item['mapa']} não confere "
                             f"com o sha combinado ({sha[:8]} ≠ {item['mapa_sha256'][:8]})")
        tmp = c["pasta"] + ".parcial"
        if os.path.isdir(tmp):
            shutil.rmtree(tmp)
        os.makedirs(os.path.join(tmp, "nav"))
        shutil.copy2(item["mapa"], os.path.join(tmp, "mapa.stcm"))
        pj = item.get("planta_json")
        if pj and os.path.isfile(pj):
            shutil.copy2(pj, os.path.join(tmp, "planta.json"))
            png = pj[:-len(".json")] + ".png"
            if os.path.isfile(png):
                shutil.copy2(png, os.path.join(tmp, "planta.png"))
        # Só o desenho (nav.json + histórico). O registro de missões e os
        # traços moram na mesma pasta hoje, mas são do ROBÔ, não do ambiente.
        nd = item.get("nav_dir")
        if nd and os.path.isfile(os.path.join(nd, "nav.json")):
            shutil.copy2(os.path.join(nd, "nav.json"), os.path.join(tmp, "nav", "nav.json"))
            if os.path.isdir(os.path.join(nd, "historico")):
                shutil.copytree(os.path.join(nd, "historico"),
                                os.path.join(tmp, "nav", "historico"))
        _gravar_json(os.path.join(tmp, "ficha.json"), {
            "id": item["id"], "nome": item["nome"],
            "criado": time.strftime("%Y-%m-%d %H:%M:%S"), "quem": "migração",
            "mapa_sha256": sha,
            "fita": list(item["fita"]) if item.get("fita") else None,
            "arquivado": False})
        os.replace(tmp, c["pasta"])          # o pacote aparece inteiro ou não aparece
        feitos.append(f"{item['id']}: criado ({amb.avaliar(item['id'])['estado']})")
    if amb.id_ativo() is None:
        _gravar_json(os.path.join(raiz, ATIVO),
                     {"id": legado["id"], "quem": "migração",
                      "quando": time.strftime("%Y-%m-%d %H:%M:%S")})
        feitos.append(f"ativo: {legado['id']}")
    return feitos


def promover_se_pronto(amb: Ambientes, AMB: dict) -> bool:
    """
    O ambiente ATIVO subiu como rascunho e agora está pronto (o operador
    salvou o desenho no /mapa — B5)? Libera a missão SEM reiniciar, mas só se
    o mapa e a fita forem exatamente os que o serviço carregou na partida —
    senão a fita do validador estaria velha e é preciso reiniciar.
    Atualiza AMB no lugar; True se promoveu.
    """
    if (AMB.get("ambiente") or {}).get("estado") != "rascunho":
        return False
    a = amb.ativo()
    if (a is None or a["id"] != AMB["ambiente"].get("id") or a["estado"] != "pronto"
            or a["mapa_sha256"] != AMB.get("mapa_sha256")
            or AMB.get("fita") is None or a["fita"] is None
            or tuple(a["fita"]) != tuple(AMB["fita"])):
        return False
    AMB["missao_motivo"] = None
    AMB["ambiente"] = dict(AMB["ambiente"], estado="pronto", motivos=[])
    return True
