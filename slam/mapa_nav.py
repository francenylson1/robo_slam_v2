"""
slam/mapa_nav.py
Áreas proibidas e POIs: o que o OPERADOR desenha sobre a planta do mapa.

DECISÕES (28 e 29/09/2026, docs/FASE4_ARQUITETURA_FROTA.md):
  - camada 1 = mapa 2D do Aurora + ÁREAS PROIBIDAS desenhadas;
  - quem desenha é o operador, no dashboard (com login) — as mesas mudam de
    lugar entre eventos e quem arruma a sala não pode depender de editar
    arquivo. O operador desenha só o OBJETO REAL; a margem de segurança é do
    sistema (NAV_MARGEM_M) e aparece em volta, no editor;
  - salvar cria uma VERSÃO nova (quem, quando) e guarda a anterior;
  - nenhuma missão começa enquanto a edição está aberta;
  - área que não fecha, que se cruza ou que sai da planta é RECUSADA; POI
    dentro de uma área (contando a margem) também.

FORMATO (data/navegacao/nav.json — fora do git: é dado do robô, não código):
  {"versao": 3, "quando": "2026-09-29 11:02:10", "quem": "operador",
   "mapa_sha256": "...",
   "areas": [{"id": "a1", "nome": "M1", "pontos": [[x, y], ...]}, ...],
   "pois":  [{"nome": "fita", "x": -0.046, "y": -0.253, "rumo": 125.8}, ...]}
x, y em metros no referencial do MAPA; rumo em graus na convenção do Aurora.

Nada aqui move o robô: é só o desenho e a sua conferência.
"""

import json
import logging
import math
import os
import shutil
import threading
import time

log = logging.getLogger(__name__)

MAX_AREAS        = 200
MAX_PONTOS       = 64
MAX_POIS         = 100
AREA_MINIMA_M2   = 0.01      # 10 × 10 cm: menos que isso é clique errado
EDICAO_EXPIRA_S  = 60.0      # editor fechado sem avisar libera a trava sozinho
HISTORICO_MAX    = 50


# ─────────────────────────────────────────────
# GEOMETRIA
# ─────────────────────────────────────────────
def _cruz(o, a, b):
    return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])


def _segmentos_cruzam(p1, p2, p3, p4) -> bool:
    """Cruzamento PRÓPRIO (as pontas compartilhadas não contam)."""
    d1, d2 = _cruz(p3, p4, p1), _cruz(p3, p4, p2)
    d3, d4 = _cruz(p1, p2, p3), _cruz(p1, p2, p4)
    return ((d1 > 0) != (d2 > 0) and d1 != 0 and d2 != 0
            and (d3 > 0) != (d4 > 0) and d3 != 0 and d4 != 0)


def se_cruza(pts) -> bool:
    n = len(pts)
    for i in range(n):
        a, b = pts[i], pts[(i + 1) % n]
        for j in range(i + 1, n):
            if abs(i - j) <= 1 or (i == 0 and j == n - 1):
                continue            # lados vizinhos compartilham a ponta
            if _segmentos_cruzam(a, b, pts[j], pts[(j + 1) % n]):
                return True
    return False


def area_poligono(pts) -> float:
    s = 0.0
    for i in range(len(pts)):
        x1, y1 = pts[i]
        x2, y2 = pts[(i + 1) % len(pts)]
        s += x1 * y2 - x2 * y1
    return abs(s) / 2.0


def ponto_dentro(p, pts) -> bool:
    x, y = p
    dentro = False
    j = len(pts) - 1
    for i in range(len(pts)):
        xi, yi = pts[i]
        xj, yj = pts[j]
        if (yi > y) != (yj > y) and x < (xj - xi) * (y - yi) / (yj - yi) + xi:
            dentro = not dentro
        j = i
    return dentro


def dist_ponto_segmento(p, a, b) -> float:
    ax, ay = a
    bx, by = b
    dx, dy = bx - ax, by - ay
    L = dx * dx + dy * dy
    t = 0.0 if L == 0 else max(0.0, min(1.0, ((p[0] - ax) * dx + (p[1] - ay) * dy) / L))
    return math.hypot(p[0] - (ax + t * dx), p[1] - (ay + t * dy))


def dist_ponto_poligono(p, pts) -> float:
    """0 dentro; fora, a distância até a borda."""
    if ponto_dentro(p, pts):
        return 0.0
    return min(dist_ponto_segmento(p, pts[i], pts[(i + 1) % len(pts)])
               for i in range(len(pts)))


def limpar_pontos(pts, min_m: float = 0.02):
    """Arredonda a mm e tira pontos colados no anterior (clique duplo)."""
    out = []
    for x, y in pts:
        p = [round(float(x), 3), round(float(y), 3)]
        if not out or math.hypot(p[0] - out[-1][0], p[1] - out[-1][1]) >= min_m:
            out.append(p)
    if len(out) > 3 and math.hypot(out[0][0] - out[-1][0], out[0][1] - out[-1][1]) < min_m:
        out.pop()
    return out


def _num(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)


# ─────────────────────────────────────────────
class NavStore:

    def __init__(self, pasta: str, mapa_sha256: str, margem_m: float,
                 planta_json: str | None = None, clock=time.monotonic):
        self.pasta       = os.path.abspath(pasta)
        self.arquivo     = os.path.join(self.pasta, "nav.json")
        self.mapa_sha256 = mapa_sha256
        self.margem_m    = margem_m
        self.planta_json = planta_json
        self._clock      = clock
        self._lock       = threading.Lock()
        self._edicao     = None      # {"quem": str, "ate": monotonic}
        self._plan       = None      # (versão, Planejador) — refeito se o desenho mudar
        os.makedirs(os.path.join(self.pasta, "historico"), exist_ok=True)

    # ─── planta ───────────────────────────────
    def planta(self):
        """Metadados da planta (origem/escala) ou None se ainda não gerada."""
        if not self.planta_json or not os.path.isfile(self.planta_json):
            return None
        try:
            with open(self.planta_json, encoding="utf-8") as f:
                meta = json.load(f)
        except Exception:
            return None
        if meta.get("mapa_sha256") != self.mapa_sha256:
            log.error("[Nav] A planta é de outro mapa (sha diferente) — ignorada.")
            return None
        return meta

    def planta_png(self):
        if not self.planta_json:
            return None
        p = self.planta_json[:-len(".json")] + ".png"
        return p if os.path.isfile(p) else None

    def _limites(self):
        m = self.planta()
        if m is None:
            return None
        x0 = m["min_x"]
        y1 = m["max_y"]
        return (x0, y1 - m["altura_px"] * m["res"],
                x0 + m["largura_px"] * m["res"], y1)

    # ─── leitura ──────────────────────────────
    def vazio(self) -> dict:
        return {"versao": 0, "quando": None, "quem": None,
                "mapa_sha256": self.mapa_sha256, "areas": [], "pois": []}

    def carregar(self) -> dict:
        with self._lock:
            if not os.path.isfile(self.arquivo):
                return self.vazio()
            try:
                with open(self.arquivo, encoding="utf-8") as f:
                    doc = json.load(f)
            except Exception as e:
                log.error(f"[Nav] {self.arquivo} ilegível: {e}")
                return self.vazio()
        if doc.get("mapa_sha256") != self.mapa_sha256:
            log.error("[Nav] Áreas e POIs são de outro mapa — ignorados.")
            return self.vazio()
        return doc

    # ─── validação ────────────────────────────
    def validar(self, doc: dict) -> list[str]:
        erros = []
        if not isinstance(doc, dict):
            return ["documento inválido"]
        if doc.get("mapa_sha256") != self.mapa_sha256:
            erros.append("desenho feito para outro mapa")
        areas = doc.get("areas", [])
        pois  = doc.get("pois", [])
        if not isinstance(areas, list) or not isinstance(pois, list):
            return erros + ["áreas e POIs precisam ser listas"]
        if len(areas) > MAX_AREAS:
            erros.append(f"mais de {MAX_AREAS} áreas")
        if len(pois) > MAX_POIS:
            erros.append(f"mais de {MAX_POIS} POIs")
        lim = self._limites()
        dentro_planta = (lambda x, y: lim[0] <= x <= lim[2] and lim[1] <= y <= lim[3]) \
            if lim else (lambda x, y: True)

        ids, validas = set(), []
        for k, a in enumerate(areas):
            nome = (a.get("nome") or f"área {k + 1}") if isinstance(a, dict) else f"área {k + 1}"
            if not isinstance(a, dict):
                erros.append(f"{nome}: formato inválido")
                continue
            aid = a.get("id")
            if not isinstance(aid, str) or not aid or aid in ids:
                erros.append(f"{nome}: id ausente ou repetido")
            ids.add(aid)
            if not isinstance(nome, str) or len(nome) > 40:
                erros.append(f"área {k + 1}: nome inválido")
            pts = a.get("pontos")
            if (not isinstance(pts, list) or not all(
                    isinstance(p, (list, tuple)) and len(p) == 2
                    and _num(p[0]) and _num(p[1]) for p in pts)):
                erros.append(f"{nome}: pontos inválidos")
                continue
            if len(pts) < 3:
                erros.append(f"{nome}: precisa de pelo menos 3 pontos (não fecha)")
                continue
            if len(pts) > MAX_PONTOS:
                erros.append(f"{nome}: mais de {MAX_PONTOS} pontos")
                continue
            if not all(dentro_planta(x, y) for x, y in pts):
                erros.append(f"{nome}: sai da planta do mapa")
            if se_cruza(pts):
                erros.append(f"{nome}: os lados se cruzam")
                continue
            if area_poligono(pts) < AREA_MINIMA_M2:
                erros.append(f"{nome}: área pequena demais (menos de 10 × 10 cm)")
                continue
            validas.append((nome, pts))

        nomes = set()
        for k, p in enumerate(pois):
            if not isinstance(p, dict):
                erros.append(f"POI {k + 1}: formato inválido")
                continue
            nome = p.get("nome")
            if not isinstance(nome, str) or not nome.strip() or len(nome) > 30:
                erros.append(f"POI {k + 1}: nome inválido")
                continue
            if nome in nomes:
                erros.append(f"POI {nome}: nome repetido")
            if nome.strip().lower() == "base":
                erros.append("POI base: o nome 'base' é reservado (é a fita)")
            nomes.add(nome)
            if not (_num(p.get("x")) and _num(p.get("y"))):
                erros.append(f"POI {nome}: posição inválida")
                continue
            if p.get("rumo") is not None and not _num(p.get("rumo")):
                erros.append(f"POI {nome}: rumo inválido")
            if not dentro_planta(p["x"], p["y"]):
                erros.append(f"POI {nome}: fora da planta do mapa")
            for anome, pts in validas:
                d = dist_ponto_poligono((p["x"], p["y"]), pts)
                if d < self.margem_m:
                    erros.append(f"POI {nome}: dentro da área {anome} contando a margem "
                                 f"de {self.margem_m * 100:.0f} cm (a {d * 100:.0f} cm)")
        return erros

    # ─── gravação ─────────────────────────────
    def salvar(self, doc: dict, quem: str, versao_base: int):
        """(True, doc_salvo) ou (False, [erros])."""
        # Limpa ANTES de validar: tirar pontos colados não pode deixar passar
        # uma área que, limpa, teria menos de 3 pontos.
        try:
            doc = dict(doc, areas=[dict(a, pontos=limpar_pontos(a["pontos"]))
                                   for a in doc.get("areas", [])])
        except Exception:
            pass                    # formato ruim: a validação diz o quê
        erros = self.validar(doc)
        if erros:
            return False, erros
        atual = self.carregar()
        if versao_base != atual["versao"]:
            return False, [f"alguém salvou a versão {atual['versao']} enquanto você "
                           f"editava a {versao_base} — recarregue o editor"]
        novo = {
            "versao": atual["versao"] + 1,
            "quando": time.strftime("%Y-%m-%d %H:%M:%S"),
            "quem": quem,
            "mapa_sha256": self.mapa_sha256,
            "areas": [{"id": a["id"], "nome": a.get("nome") or a["id"],
                       "pontos": limpar_pontos(a["pontos"])}
                      for a in doc.get("areas", [])],
            "pois": [{"nome": p["nome"].strip(), "x": round(float(p["x"]), 3),
                      "y": round(float(p["y"]), 3),
                      "rumo": (None if p.get("rumo") is None
                               else round(float(p["rumo"]), 1))}
                     for p in doc.get("pois", [])],
        }
        with self._lock:
            if os.path.isfile(self.arquivo):
                shutil.copy2(self.arquivo, os.path.join(
                    self.pasta, "historico", f"nav_v{atual['versao']:04d}.json"))
                self._podar_historico()
            tmp = self.arquivo + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(novo, f, indent=2, ensure_ascii=False)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp, self.arquivo)
        log.info(f"[Nav] Versão {novo['versao']} salva por {quem}: "
                 f"{len(novo['areas'])} áreas, {len(novo['pois'])} POIs.")
        return True, novo

    def _podar_historico(self):
        h = os.path.join(self.pasta, "historico")
        arqs = sorted(n for n in os.listdir(h) if n.startswith("nav_v"))
        for n in arqs[:-HISTORICO_MAX]:
            try:
                os.remove(os.path.join(h, n))
            except OSError:
                pass

    # ─── planejador ───────────────────────────
    def planejador(self):
        """Planejador sobre a planta + áreas SALVAS (não o rascunho do editor).
        Refeito só quando a versão muda (~0,3 s)."""
        png, meta = self.planta_png(), self.planta()
        if png is None or meta is None:
            return None
        doc = self.carregar()
        if self._plan is None or self._plan[0] != doc["versao"]:
            from slam.planejador import Planta, Planejador
            self._plan = (doc["versao"],
                          Planejador(Planta.de_arquivos(png, meta), doc["areas"],
                                     self.margem_m))
        return self._plan[1]

    def poi(self, nome: str):
        return next((p for p in self.carregar()["pois"] if p["nome"] == nome), None)

    # ─── trava de edição ──────────────────────
    def editar(self, acao: str, quem: str):
        """acao: 'inicio' | 'batida' | 'fim'. Devolve (ok, msg)."""
        agora = self._clock()
        with self._lock:
            ativa = self._edicao is not None and self._edicao["ate"] > agora
            if acao == "fim":
                self._edicao = None
                return True, "edição encerrada"
            if acao in ("inicio", "batida"):
                if ativa and self._edicao["quem"] != quem:
                    return False, f"{self._edicao['quem']} está editando agora"
                self._edicao = {"quem": quem, "ate": agora + EDICAO_EXPIRA_S}
                return True, "editando"
        return False, "ação inválida"

    def editando(self) -> bool:
        """A missão pergunta isto antes de começar."""
        with self._lock:
            return self._edicao is not None and self._edicao["ate"] > self._clock()
