"""
slam/mapeamento.py
MAPEAR PELO PAINEL — os passos do mapeamento de um ambiente novo com o robô 1
(pacote de ambiente, Etapa B; decidido com o professor em 02/10/2026).

O FLUXO (3 passadas — decisão dele):
  1. iniciar(nome)     → o Aurora zera e começa um mapa novo   [zerando → mapeando]
     A passada 1 é no joystick, com as mesas do evento no lugar.
  2. concluir_mapa()   → baixa o .stcm e gera a planta          [salvando → mapa_salvo]
  3. medir_fita()      → robô na fita: carrega o mapa salvo,
                         relocaliza e mede a fita duas vezes    [medindo_fita → fita_medida]
  4. iniciar_coleta() / terminar_coleta(), 2 vezes (mínimo) — passadas 2 e 3,
     já localizado no mapa SALVO: o gravador de sempre grava o C1 e o laser do
     Aurora (ligado só aqui) com a pose final                   [coletando ↔ fita_medida]
  5. concluir()        → robô de volta na fita: confere quanto a pose escorregou
                         (B6: só AVISA acima de 5 cm), copia as varreduras das
                         passadas para o pacote e o pacote aparece  [conferindo → gerando → fim]
  cancelar() em qualquer passo descarta tudo.

O pacote em construção fica em data/ambientes/<id>.parcial/ — invisível para a
lista de ambientes — e vira <id>/ de uma vez no fim. Ele NÃO fica ativo sozinho
(B3): o operador escolhe "Usar este ambiente". Até salvar o desenho no /mapa,
fica rascunho (B5).

Por que a coleta é no mapa SALVO (bancada de 02/10): as poses gravadas durante
o mapeamento diferem do mapa final (13–18 cm no fim do corredor), e a grade
exportada pelo Aurora não bate com a pose ao vivo melhor que ~9 cm.

Reinício no meio: antes de o mapa ser salvo → "interrompido" (só cancelar);
depois → volta a "mapa_salvo" (medir a fita de novo e seguir).

Nada aqui move o robô: quem anda é o operador, no joystick. Os pedidos ao
Aurora vão pela fila dele (sensors/aurora_pose.py, um cliente só).
"""

import json
import logging
import os
import re
import shutil
import threading
import time
import unicodedata

log = logging.getLogger(__name__)

# fase do pedido ao Aurora → (nome do trabalho, fase se der certo, fase se falhar)
_ESPERA = {
    "zerando":      ("zerar_para_mapear", "mapeando", "interrompido"),
    "salvando":     ("salvar_mapa", "mapa_salvo", "mapeando"),
    "medindo_fita": ("medir_fita", "fita_medida", "mapa_salvo"),
    "conferindo":   ("conferir_fita", "gerando", "fita_medida"),
}


def _slug(nome: str) -> str:
    s = unicodedata.normalize("NFKD", nome).encode("ascii", "ignore").decode()
    s = re.sub(r"[^A-Za-z0-9]+", "_", s).strip("_").lower()
    return s[:28] or "ambiente"


def _gravar_json(caminho, doc):
    tmp = caminho + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(doc, f, indent=2, ensure_ascii=False)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, caminho)


def _ler_json(caminho):
    try:
        with open(caminho, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def copiar_varreduras(varreduras_dir, janelas, destino_dir) -> list[int]:
    """Copia, do gravador de sempre (AAAA-MM-DD/HH.jsonl), só as linhas dentro
    de cada janela (inicio, fim). Uma saída por janela; devolve as contagens."""
    os.makedirs(destino_dir, exist_ok=True)
    contagens = []
    for n, (t0, t1) in enumerate(janelas, start=2):        # passadas 2, 3, ...
        arquivos, h = [], t0 - (t0 % 3600)
        while h <= t1:
            chave = time.strftime("%Y-%m-%d/%H", time.localtime(h))
            arquivos.append(os.path.join(varreduras_dir, chave + ".jsonl"))
            h += 3600
        k = 0
        with open(os.path.join(destino_dir, f"passada_{n}.jsonl"), "w", encoding="utf-8") as out:
            for arq in dict.fromkeys(arquivos):
                if not os.path.isfile(arq):
                    continue
                with open(arq, encoding="utf-8") as f:
                    for linha in f:
                        try:
                            t = json.loads(linha).get("t")
                        except ValueError:
                            continue
                        if isinstance(t, (int, float)) and t0 <= t <= t1:
                            out.write(linha if linha.endswith("\n") else linha + "\n")
                            k += 1
        contagens.append(k)
    return contagens


def gerar_c1_seguro(gerar_fn, pasta):
    """Os mapas dos C1 servem aos robôs SEM Aurora. Se falharem, o pacote do
    robô 1 sai do mesmo jeito, com o erro na ficha para refazer depois."""
    try:
        return gerar_fn(pasta)
    except Exception as e:
        log.error(f"[Mapeamento] Mapas dos C1 falharam: {e} — o pacote segue sem eles.")
        return {"erro": f"{type(e).__name__}: {e}"}


class Mapeamento:

    def __init__(self, raiz, aurora, *, impedimentos_fn, parado_fn, varreduras_dir,
                 clock=time.time, livre_mb_fn=None, fita_tol=(0.02, 1.0),
                 aviso_m=0.05, min_coletas=2, min_livre_mb=1024, laser_coleta_s=1.0,
                 gerar_mapas_fn=None):
        self.raiz            = os.path.abspath(raiz)
        self.aurora          = aurora
        self._impedimentos   = impedimentos_fn
        self._parado         = parado_fn
        self.varreduras_dir  = varreduras_dir
        self._clock          = clock
        self._livre_mb       = livre_mb_fn or self._livre_mb_real
        self.fita_tol        = fita_tol
        self.aviso_m         = aviso_m
        self.min_coletas     = min_coletas
        self.min_livre_mb    = min_livre_mb
        self.laser_coleta_s  = laser_coleta_s
        self._gerar_mapas    = gerar_mapas_fn     # Etapa B.2: mapas dos C1 + nota
        self._lock           = threading.RLock()
        self._pedido_em      = 0.0
        self._fim            = None               # thread do passo final
        self.e               = None               # o mapeamento em andamento (dict)
        self.ultimo          = None               # resultado do último que terminou
        self._retomar()

    # ─── utilidades ───────────────────────────
    def _livre_mb_real(self):
        os.makedirs(self.raiz, exist_ok=True)
        return shutil.disk_usage(self.raiz).free / 1e6

    def _parcial(self, pid=None):
        return os.path.join(self.raiz, (pid or self.e["id"]) + ".parcial")

    def _salvar(self):
        _gravar_json(os.path.join(self._parcial(), "estado.json"), self.e)

    @property
    def ativo(self) -> bool:
        return self.e is not None

    def estado(self) -> dict:
        with self._lock:
            d = dict(self.e) if self.e else {"fase": None}
            d["ultimo"] = self.ultimo
            if self.aurora is not None:
                d["aurora_passo"] = self.aurora.trabalho.get("passo")
            return d

    def _fase(self, *fases):
        return self.e is not None and self.e["fase"] in fases

    def _recusa_fase(self, quer: str):
        if self.e is None:
            return False, "nenhum mapeamento em andamento"
        if self.e["fase"] == "interrompido":
            return False, "o mapeamento foi interrompido — só dá para cancelar"
        return False, f"agora não: o passo atual é '{self.e['fase']}' (este pede '{quer}')"

    def _pedir(self, trabalho, fase, **kw):
        ok, msg = self.aurora.pedir_trabalho(trabalho, self._parado, **kw)
        if not ok:
            return False, msg
        self._pedido_em = time.time()
        self.e.update(fase=fase, erro=None)
        self._salvar()
        return True, msg

    # ─── retomada depois de um reinício ───────
    def _retomar(self):
        if not os.path.isdir(self.raiz):
            return
        parciais = sorted((n for n in os.listdir(self.raiz) if n.endswith(".parcial")),
                          key=lambda n: os.path.getmtime(os.path.join(self.raiz, n)))
        if not parciais:
            return
        e = _ler_json(os.path.join(self.raiz, parciais[-1], "estado.json"))
        if not isinstance(e, dict) or "id" not in e:
            return
        if e.get("mapa_sha256"):
            e.update(fase="mapa_salvo", coleta_atual=None,
                     erro="o robô reiniciou — ponha na fita e meça a fita de novo para seguir")
        else:
            e.update(fase="interrompido",
                     erro="o robô reiniciou antes de o mapa ser salvo — cancele e comece de novo")
        self.e = e
        self._salvar()
        if self.aurora is not None:
            self.aurora.entrar_em_mapeamento()
        log.warning(f"[Mapeamento] Retomado após reinício: {e['id']} em '{e['fase']}'.")

    # ─── os passos ────────────────────────────
    def iniciar(self, nome, quem):
        with self._lock:
            if self.e is not None:
                return False, "já há um mapeamento em andamento"
            if self.aurora is None:
                return False, "este robô não tem Aurora — só o robô 1 mapeia"
            nome = (nome or "").strip()
            if not nome or len(nome) > 40:
                return False, "dê um nome ao ambiente (até 40 letras)"
            imp = self._impedimentos()
            if imp:
                return False, imp
            if not self._parado():
                return False, "o robô precisa estar parado para começar"
            livre = self._livre_mb()
            if livre < self.min_livre_mb:
                return False, (f"pouco espaço em disco: {livre:.0f} MB livres "
                               f"(precisa de {self.min_livre_mb} MB)")
            if self.aurora.ocupado:
                return False, "o Aurora está ocupado (partida em andamento?)"
            pid = f"{_slug(nome)}_{time.strftime('%Y%m%d', time.localtime(self._clock()))}"
            os.makedirs(self.raiz, exist_ok=True)
            for n in os.listdir(self.raiz):
                ficha = _ler_json(os.path.join(self.raiz, n, "ficha.json"))
                mesmo_nome = isinstance(ficha, dict) and \
                    str(ficha.get("nome", "")).strip().lower() == nome.lower()
                if n in (pid, pid + ".parcial") or mesmo_nome:
                    return False, f"já existe um ambiente com esse nome ({n})"
            os.makedirs(os.path.join(self._parcial(pid), "nav"))
            self.e = {"id": pid, "nome": nome, "quem": quem,
                      "criado": time.strftime("%Y-%m-%d %H:%M:%S"),
                      "fase": "zerando", "erro": None, "mapa_sha256": None,
                      "fita": None, "medida": None, "coletas": [], "coleta_atual": None}
            ok, msg = self._pedir("zerar_para_mapear", "zerando")
            if not ok:
                shutil.rmtree(self._parcial(pid), ignore_errors=True)
                self.e = None
                return False, msg
            log.info(f"[Mapeamento] {quem} começou a mapear '{nome}' ({pid}).")
            return True, f"mapeamento de {nome} começou — o Aurora está zerando"

    def concluir_mapa(self, quem):
        with self._lock:
            if not self._fase("mapeando"):
                return self._recusa_fase("mapeando")
            if not self._parado():
                return False, "o robô precisa estar parado para salvar o mapa"
            p = self._parcial()
            return self._pedir("salvar_mapa", "salvando",
                               destino=os.path.join(p, "mapa.stcm"),
                               planta_base=os.path.join(p, "planta"),
                               nome_mapa=f"{self.e['id']}/mapa.stcm")

    def medir_fita(self, quem):
        with self._lock:
            if not self._fase("mapa_salvo"):
                return self._recusa_fase("mapa_salvo")
            if not self._parado():
                return False, "o robô precisa estar parado na fita"
            return self._pedir("medir_fita", "medindo_fita",
                               mapa=os.path.join(self._parcial(), "mapa.stcm"),
                               mapa_sha256=self.e["mapa_sha256"],
                               tol_m=self.fita_tol[0], tol_deg=self.fita_tol[1])

    def iniciar_coleta(self, quem):
        with self._lock:
            if not self._fase("fita_medida"):
                return self._recusa_fase("fita_medida")
            self.e.update(fase="coletando", coleta_atual=self._clock(), erro=None)
            self.aurora.set_laser(self.laser_coleta_s)
            self._salvar()
            n = len(self.e["coletas"]) + 2
            return True, f"passada {n} (coleta) começou — percorra o ambiente todo"

    def terminar_coleta(self, quem):
        with self._lock:
            if not self._fase("coletando"):
                return self._recusa_fase("coletando")
            self.e["coletas"].append({"inicio": self.e["coleta_atual"], "fim": self._clock()})
            self.e.update(fase="fita_medida", coleta_atual=None)
            self.aurora.set_laser(None)
            self._salvar()
            n = len(self.e["coletas"])
            falta = max(0, self.min_coletas - n)
            return True, (f"passada de coleta {n} registrada"
                          + (f" — falta(m) {falta}" if falta else " — pode concluir"))

    def concluir(self, quem):
        with self._lock:
            if not self._fase("fita_medida"):
                return self._recusa_fase("fita_medida")
            n = len(self.e["coletas"])
            if n < self.min_coletas:
                return False, (f"faltam passadas de coleta: {n} de {self.min_coletas} "
                               f"(o mínimo é {self.min_coletas})")
            if not self._parado():
                return False, "o robô precisa estar parado na fita"
            return self._pedir("conferir_fita", "conferindo", fita=self.e["fita"])

    def cancelar(self, quem):
        with self._lock:
            if self.e is None:
                return False, "nenhum mapeamento em andamento"
            if self.aurora is not None and self.aurora.trabalho.get("passo"):
                return False, (f"aguarde o passo atual terminar "
                               f"({self.aurora.trabalho['passo']})")
            if self._fase("gerando"):
                return False, "o pacote já está sendo gerado — aguarde"
            pid = self.e["id"]
            shutil.rmtree(self._parcial(), ignore_errors=True)
            self.e = None
            if self.aurora is not None:
                self.aurora.voltar_ao_ambiente("mapeamento cancelado — 'Localizar na fita'")
            self.ultimo = {"ok": False, "id": pid, "msg": "cancelado"}
            log.info(f"[Mapeamento] {quem} cancelou {pid}.")
            return True, "mapeamento cancelado — nada foi gravado"

    # ─── acompanhamento (o main chama a cada ~0,5 s) ─
    def tick(self):
        with self._lock:
            if self.e is None:
                return
            fase = self.e["fase"]
            if fase == "gerando":
                if self._fim is not None and not self._fim.is_alive():
                    self._fim = None
                return
            if fase not in _ESPERA:
                return
            nome, fase_ok, fase_erro = _ESPERA[fase]
            t = self.aurora.trabalho
            if (t.get("nome") != nome or t.get("passo") is not None
                    or t.get("resultado") is None or (t.get("quando") or 0) < self._pedido_em):
                return
            if t["resultado"] != "ok":
                self.e.update(fase=fase_erro, erro=t["resultado"])
                self._salvar()
                return
            dados = t.get("dados") or {}
            if fase == "salvando":
                self.e["mapa_sha256"] = dados["sha256"]
                self._gravar_ficha()
            elif fase == "medindo_fita":
                self.e.update(fita=dados["fita"], medida=dados)
                self._gravar_ficha()
            elif fase == "conferindo":
                self.e["conferencia"] = dados
                self.e["fase"] = "gerando"
                self._salvar()
                self._fim = threading.Thread(target=self._finalizar, daemon=True,
                                             name="MapeamentoFim")
                self._fim.start()
                return
            self.e.update(fase=fase_ok, erro=None)
            self._salvar()

    def _gravar_ficha(self):
        _gravar_json(os.path.join(self._parcial(), "ficha.json"), {
            "id": self.e["id"], "nome": self.e["nome"], "criado": self.e["criado"],
            "quem": self.e["quem"], "mapa_sha256": self.e["mapa_sha256"],
            "fita": self.e["fita"], "arquivado": False})

    def _finalizar(self):
        """Fora do lock pesado: copia a coleta, (B.2) gera os mapas dos C1 e
        publica o pacote de uma vez."""
        with self._lock:
            e = dict(self.e)
        parcial = self._parcial(e["id"])
        try:
            conf = e.get("conferencia") or {}
            aviso = None
            if conf.get("desvio_cm") is not None and conf["desvio_cm"] > self.aviso_m * 100:
                aviso = (f"a pose escorregou {conf['desvio_cm']:.0f} cm durante a coleta "
                         f"(aviso acima de {self.aviso_m * 100:.0f} cm) — considere repetir a coleta")
            janelas = [(c["inicio"], c["fim"]) for c in e["coletas"]]
            contagens = copiar_varreduras(self.varreduras_dir, janelas,
                                          os.path.join(parcial, "coleta"))
            extra = gerar_c1_seguro(self._gerar_mapas, parcial) if self._gerar_mapas else None
            ficha = _ler_json(os.path.join(parcial, "ficha.json")) or {}
            ficha.update(
                coletas=[dict(c, varreduras=k) for c, k in zip(e["coletas"], contagens)],
                fita_medida=e.get("medida"),
                conferencia=dict(conf, aviso=aviso))
            if extra:
                ficha["c1"] = extra
            _gravar_json(os.path.join(parcial, "ficha.json"), ficha)
            os.remove(os.path.join(parcial, "estado.json"))
            os.replace(parcial, os.path.join(self.raiz, e["id"]))
            resultado = {"ok": True, "id": e["id"], "nome": e["nome"], "aviso": aviso,
                         "conferencia": conf, "varreduras": contagens, "c1": extra}
            log.info(f"[Mapeamento] {e['id']} concluído: {resultado}")
        except Exception as ex:
            log.error(f"[Mapeamento] Falha ao gerar o pacote {e['id']}: {ex}")
            with self._lock:
                self.e.update(fase="fita_medida", erro=f"falhou ao gerar o pacote: {ex}")
                self._salvar()
            return
        with self._lock:
            self.e = None
            self.ultimo = resultado
        self.aurora.voltar_ao_ambiente()
