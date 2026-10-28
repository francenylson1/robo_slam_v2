"""
slam/planejador.py
Planejador de rota: da pose do robô até um POI, sem entrar nas áreas proibidas.

O QUE ELE USA (decisões de 28 e 29/09/2026):
  - a PLANTA do mapa (grade de 5 cm, gerada por scripts/aurora_planta.py):
    parede = bloqueado; e o que o laser nunca viu (cinza, fora da sala) também
    é bloqueado — o robô só planeja por onde se sabe que é chão livre;
  - as ÁREAS PROIBIDAS desenhadas pelo operador (slam/mapa_nav.py);
  - a MARGEM (NAV_MARGEM_M): o robô é tratado como um PONTO (o centro de giro,
    onde fica o Aurora) e todo obstáculo cresce pela margem. A margem já inclui
    o raio que ele varre ao girar parado (36,6 cm) + a folga de localização.

COMO:
  1. grade de bloqueio (parede, desconhecido, áreas);
  2. distância de cada célula ao bloqueio mais próximo (chanfro 3-4);
  3. célula com distância < margem = proibida para o CENTRO do robô;
  4. A* em 8 direções; o custo cresce perto dos obstáculos, então a rota
     prefere o meio dos corredores em vez de raspar na margem;
  5. a rota em escada vira poucos trechos RETOS (linha de visada sobre a
     grade proibida): o robô gira parado em cada ponto e anda reto até o
     próximo — é assim que a missão usa (decisão 5 de 29/09).

Só calcula. Não move nada, não fala com o Aurora.
"""

import heapq
import math

import numpy as np

LIVRE, OCUPADO, DESCONHECIDO = 0, 1, 2
# Com l2p_mapping=True o ocupado vem ESCURO (conferido em 28/09).
LIMIAR_OCUPADO = 80
LIMIAR_LIVRE = 200
# Perto do obstáculo o passo custa mais: até PREFERE_M de folga além da
# margem, o custo sobe até (1 + PESO_FOLGA).
PREFERE_M = 0.50
PESO_FOLGA = 2.0
# Ao encurtar a rota em trechos retos, a reta tende a raspar nas quinas da
# margem. Os trechos retos pedem esta folga a mais, quando ela existe.
FOLGA_RETA_M = 0.05
# Trecho menor que isso vira um giro a mais por quase nada: some, se der.
TRECHO_MINIMO_M = 0.15
# PORTA (27/10/2026, aprovada pelo Prof.): a margem de 0,50 de cada lado pede
# um vão de 1,00 m — a porta de 85 cm do maker-corredor nunca passava. Numa
# PORTA desenhada (os dois batentes), uma faixa estreita no EIXO dela fica
# liberada com a margem de PASSAGEM: meia largura do robô (0,21 no robô 1,
# 0,23 na frota Ø46) + folga de localização. Atravessa em RETA: a rota é
# forçada a um ponto PORTA_ALCANCE_M antes e outro depois, no eixo, e não
# gira dentro do vão.
PORTA_MARGEM_M = 0.30        # folga mínima do centro, para planejar na faixa
PORTA_VIGIA_M = 0.26         # o vigia só para abaixo disto, dentro da porta
PORTA_FAIXA_M = 0.075        # meia largura da faixa da rota: 3 células de 5 cm, ligada mesmo inclinada
PORTA_FAIXA_VIGIA_M = 0.10   # desvio lateral aceito pelo vigia (bumper ok até ±10 cm)
PORTA_FUNDO_M = 0.30         # parede da porta (20 cm medidos) + folga
PORTA_ALCANCE_M = 0.60       # o ponto antes/depois, além da parede
PORTA_EMENDA_M = 0.30        # a faixa passa disto além deles, até o chão livre
# A ZONA DA PORTA (28/10/2026): o vão × (os pontos antes/depois + 10 cm — o
# robô para alguns cm antes). Nela: 8 %, bumper de 12 cm (opção A do Prof.),
# o vigia só para abaixo de PORTA_VIGIA_M, e a reta que liga a rota a um ponto
# da porta só pede o limite do vigia de fora (margem − tolerância). No
# maker-corredor, entre a parede e o armário, a ligação ao ponto da sala passa
# a 0,45–0,48: a regra antiga (0,46 no planejador, 0,50 na missão) era
# DIFERENTE nos dois e a missão recusava a rota que o planejador fez (28/10).
# Agora planejador e missão perguntam a mesma coisa: reta_passavel().
PORTA_ZONA_FOLGA_M = 0.20
# A TRAVESSIA pode sair do meio do vão até isto, para longe do que estiver
# mais perto (fica dentro do desvio que o vigia aceita, PORTA_FAIXA_VIGIA_M).
PORTA_DESVIO_MAX_M = 0.08
# O PIVÔ pode terminar até isto ao lado do eixo (o trecho até o outro ponto
# sai inclinado ~2°): com a bitola medida (30,5 cm, 28/10) o arco é curto e o
# ponto de chegada, no eixo, deixava 24,5 cm à frente — abaixo dos 25.
PORTA_PIVO_AFASTA_M = (0.0, 0.02, 0.04)
# A FOLHA: até 28/10 a porta limpava da planta a área por onde a folha gira
# (vão × 1,25 × vão), para tirar a folha gravada aberta ~75° na coleta de 23/10.
# Isso apagou também a PAREDE onde a folha encosta, e o robô encostou nela de
# frente (28/10, 10:16). Saiu: a L3 já tira a folha de 23/10, e a porta só
# limpa o VÃO (manchas no batente). Folha atravessada é obstáculo do momento.


def porta_geometria(p, fundo=PORTA_FUNDO_M, alcance=PORTA_ALCANCE_M):
    """Centro, largura, direção do vão (t), normal (n) e os pontos antes/depois."""
    (ax, ay), (bx, by) = p["a"], p["b"]
    largura = math.hypot(bx - ax, by - ay)
    tx, ty = (bx - ax) / largura, (by - ay) / largura
    nx, ny = -ty, tx
    cx, cy = (ax + bx) / 2, (ay + by) / 2
    meio = fundo / 2 + alcance
    return {"c": (cx, cy), "largura": largura, "t": (tx, ty), "n": (nx, ny),
            "meio": meio, "meio_fundo": fundo / 2,
            "lados": ((cx - nx * meio, cy - ny * meio), (cx + nx * meio, cy + ny * meio))}


def _local(pl, g, l0, l1, c0, c1):
    """Coordenadas (s ao longo do vão, n atravessando) das células da janela."""
    lin, col = np.mgrid[l0:l1, c0:c1]
    x = pl.min_x + (col + 0.5) * pl.res - g["c"][0]
    y = pl.max_y - (lin + 0.5) * pl.res - g["c"][1]
    return x * g["t"][0] + y * g["t"][1], x * g["n"][0] + y * g["n"][1]


def _janela(pl, g):
    r = g["largura"] / 2 + max(g["meio"], g["meio_fundo"]) + pl.res
    (la, ca), (lb, cb) = pl.celula(g["c"][0] - r, g["c"][1] + r), pl.celula(g["c"][0] + r, g["c"][1] - r)
    return max(la, 0), min(lb + 1, pl.h), max(ca, 0), min(cb + 1, pl.w)


class Planta:
    """A grade da planta e a conversão célula ↔ metros (a mesma do editor)."""

    def __init__(self, cinza: np.ndarray, meta: dict):
        self.res   = float(meta["res"])
        self.min_x = float(meta["min_x"])
        self.max_y = float(meta["max_y"])
        self.h, self.w = cinza.shape
        g = np.full(cinza.shape, DESCONHECIDO, dtype=np.uint8)
        g[cinza < LIMIAR_OCUPADO] = OCUPADO
        g[cinza > LIMIAR_LIVRE] = LIVRE
        self.grade = g

    @classmethod
    def de_arquivos(cls, png: str, meta: dict):
        from PIL import Image
        return cls(np.array(Image.open(png).convert("L")), meta)

    def celula(self, x: float, y: float):
        """(linha, coluna) da imagem; topo da imagem = +y."""
        return (int(math.floor((self.max_y - y) / self.res)),
                int(math.floor((x - self.min_x) / self.res)))

    def centro(self, lin: int, col: int):
        return (self.min_x + (col + 0.5) * self.res,
                self.max_y - (lin + 0.5) * self.res)

    def dentro(self, lin: int, col: int) -> bool:
        return 0 <= lin < self.h and 0 <= col < self.w


def _rasterizar(pl: Planta, pontos, bloq: np.ndarray):
    """Marca como bloqueadas as células cujo centro está dentro do polígono."""
    xs = [p[0] for p in pontos]
    ys = [p[1] for p in pontos]
    l0, c0 = pl.celula(min(xs), max(ys))
    l1, c1 = pl.celula(max(xs), min(ys))
    l0, c0 = max(l0, 0), max(c0, 0)
    l1, c1 = min(l1, pl.h - 1), min(c1, pl.w - 1)
    n = len(pontos)
    for lin in range(l0, l1 + 1):
        y = pl.max_y - (lin + 0.5) * pl.res
        # interseções da linha horizontal com os lados (regra par-ímpar)
        cortes = []
        for i in range(n):
            (xa, ya), (xb, yb) = pontos[i], pontos[(i + 1) % n]
            if (ya > y) != (yb > y):
                cortes.append(xa + (y - ya) * (xb - xa) / (yb - ya))
        cortes.sort()
        for k in range(0, len(cortes) - 1, 2):
            ca = max(c0, int(math.ceil((cortes[k] - pl.min_x) / pl.res - 0.5)))
            cb = min(c1, int(math.floor((cortes[k + 1] - pl.min_x) / pl.res - 0.5)))
            if cb >= ca:
                bloq[lin, ca:cb + 1] = True
    # O CONTORNO também bloqueia, amostrado a cada 1/4 de célula: sem isso,
    # uma área mais fina que uma célula (uma divisória desenhada fina) não
    # tem nenhum centro de célula dentro e sumia (pego pelo harness em 29/09).
    for i in range(n):
        (xa, ya), (xb, yb) = pontos[i], pontos[(i + 1) % n]
        passos = int(math.hypot(xb - xa, yb - ya) / (pl.res / 4)) + 1
        for k in range(passos + 1):
            t = k / passos
            lin, col = pl.celula(xa + (xb - xa) * t, ya + (yb - ya) * t)
            if pl.dentro(lin, col):
                bloq[lin, col] = True


def _distancia(bloq: np.ndarray, res: float) -> np.ndarray:
    """Distância (m) de cada célula ao bloqueio mais próximo — chanfro 3-4.
    Linha a linha em numpy (26/10): o laço célula a célula levava 1,1 s na Pi
    segurando o GIL, e os leitores dos C1 transbordavam (bumper sem dado →
    missão cancelada "algo à frente"). Dentro da linha, v[c] = min(t[c],
    v[c-1] + 3) é 3c + mínimo acumulado de t[k] - 3k: o mesmo resultado."""
    INF = 1 << 30
    h, w = bloq.shape
    d = np.where(bloq, 0, INF).astype(np.int64)
    # borda da grade conta como bloqueio (fora do mapa não se anda)
    d[0, :] = 0; d[-1, :] = 0; d[:, 0] = 0; d[:, -1] = 0
    passo = 3 * np.arange(w - 1, dtype=np.int64)
    for lin in range(1, h):             # ida
        linha, acima = d[lin], d[lin - 1]
        t = linha[:-1].copy()
        t[1:] = np.minimum.reduce([t[1:], acima[1:-1] + 3, acima[:-2] + 4, acima[2:] + 4])
        linha[:-1] = passo + np.minimum.accumulate(t - passo)
    for lin in range(h - 2, -1, -1):    # volta (da direita para a esquerda)
        linha, abaixo = d[lin], d[lin + 1]
        t = linha[1:][::-1].copy()
        t[1:] = np.minimum.reduce([t[1:], abaixo[1:-1][::-1] + 3,
                                   abaixo[:-2][::-1] + 4, abaixo[2:][::-1] + 4])
        linha[1:] = (passo + np.minimum.accumulate(t - passo))[::-1]
    return d.astype(float) / 3.0 * res


class Planejador:

    def __init__(self, planta: Planta, areas, margem_m: float, tolerancia_m: float = 0.0,
                 portas=(), obstaculos=None):
        """obstaculos: (N, 2) pontos das superfícies (a planta fina) para
        conferir o CORPO do robô nos pontos da porta; sem eles, o centro das
        células bloqueadas da planta (mais grosso, mais conservador)."""
        self.pl = planta
        self.margem_m = margem_m
        self.tolerancia_m = tolerancia_m
        bloq = planta.grade != LIVRE           # parede e desconhecido
        for a in areas:
            _rasterizar(planta, a["pontos"], bloq)
        # O vão da porta é chão: manchas que a coleta gravou no batente saem.
        self.portas = [porta_geometria(p) for p in portas]
        for g in self.portas:
            l0, l1, c0, c1 = _janela(planta, g)
            s, n = _local(planta, g, l0, l1, c0, c1)
            vao = (np.abs(s) < g["largura"] / 2 - planta.res) & (np.abs(n) <= g["meio_fundo"])
            bloq[l0:l1, c0:c1][vao] = False
        self.bloqueio = bloq
        self._obstaculos = obstaculos
        self._corpo = None
        self._pivos = {}
        self.dist = _distancia(bloq, planta.res)
        self.proibido = self.dist < margem_m
        # o vigia da missão só para abaixo disto (NAV_TOLERANCIA_M, 26/10)
        self.limite = self.dist < margem_m - tolerancia_m
        self._reta_proibida = self.dist < margem_m + FOLGA_RETA_M
        # A faixa no eixo de cada porta, com a margem de passagem.
        self._porta_vigia = np.zeros_like(self.proibido)
        self._porta_passa = np.zeros_like(self.proibido)
        for g in self.portas:
            l0, l1, c0, c1 = _janela(planta, g)
            s, n = _local(planta, g, l0, l1, c0, c1)
            d = self.dist[l0:l1, c0:c1]
            # vai um pouco além dos pontos antes/depois: encosta no chão livre
            dentro = np.abs(n) <= g["meio"] + PORTA_EMENDA_M
            faixa = dentro & (np.abs(s) <= PORTA_FAIXA_M) & (d >= PORTA_MARGEM_M)
            self.proibido[l0:l1, c0:c1][faixa] = False
            self._reta_proibida[l0:l1, c0:c1][faixa] = False
            vigia = dentro & (np.abs(s) <= PORTA_FAIXA_VIGIA_M) & (d >= PORTA_VIGIA_M)
            self.limite[l0:l1, c0:c1][vigia] = False
            self._porta_vigia[l0:l1, c0:c1][vigia] = True
            zona = ((np.abs(s) <= g["largura"] / 2 + PORTA_ZONA_FOLGA_M)
                    & (np.abs(n) <= g["meio"] + PORTA_ZONA_FOLGA_M))
            self.limite[l0:l1, c0:c1][zona & (d >= PORTA_VIGIA_M)] = False
            passa = vigia | (zona & (d >= margem_m - tolerancia_m))
            self._porta_passa[l0:l1, c0:c1][passa] = True
            # Na zona o centro anda até o limite do vigia (28/10: sem a limpeza
            # da folha, a chegada pelo lado da sala tem 0,43–0,48 de folga). O
            # CORPO de quem gira ali é conferido na manobra (slam/corpo.py).
            self.proibido[l0:l1, c0:c1][passa] = False
            self._reta_proibida[l0:l1, c0:c1][passa] = False

    def na_porta(self, x: float, y: float, folga: float = PORTA_ZONA_FOLGA_M) -> bool:
        """Centro do robô na zona de alguma porta (passa devagar, bumper curto)."""
        for g in self.portas:
            dx, dy = x - g["c"][0], y - g["c"][1]
            if (abs(dx * g["t"][0] + dy * g["t"][1]) <= g["largura"] / 2 + folga
                    and abs(dx * g["n"][0] + dy * g["n"][1]) <= g["meio"] + folga):
                return True
        return False

    # ─────────────────────────────────────────
    def livre(self, x: float, y: float) -> bool:
        lin, col = self.pl.celula(x, y)
        return self.pl.dentro(lin, col) and not self.proibido[lin, col]

    def passavel(self, x: float, y: float) -> bool:
        """Para a reta de um trecho: livre, ou na zona da porta (no eixo, no
        desvio que o vigia aceita; fora do eixo, até o limite do vigia)."""
        lin, col = self.pl.celula(x, y)
        return self.pl.dentro(lin, col) and (not self.proibido[lin, col]
                                             or bool(self._porta_passa[lin, col]))

    def reta_passavel(self, a, b) -> bool:
        """A reta a → b, amostrada a cada 2 cm, toda passável. A MESMA pergunta
        no planejador (ligação à porta) e na missão (antes de cada trecho).
        Quem PARTE da faixa de tolerância (parou alguns cm fora do ponto, num
        corredor justo) pode sair dela pela reta, desde que fora do limite do
        vigia — como _sair_da_faixa; depois de entrar no livre, tudo passável."""
        n = int(math.hypot(b[0] - a[0], b[1] - a[1]) / 0.02) + 1
        saindo = True
        for k in range(n + 1):
            x, y = a[0] + (b[0] - a[0]) * k / n, a[1] + (b[1] - a[1]) * k / n
            if self.passavel(x, y):
                saindo = False
            elif not (saindo and self.seguro(x, y)):
                return False
        return True

    def seguro(self, x: float, y: float) -> bool:
        """Centro do robô fora do limite do vigia (margem − tolerância)."""
        lin, col = self.pl.celula(x, y)
        return self.pl.dentro(lin, col) and not self.limite[lin, col]

    def folga(self, x: float, y: float) -> float:
        """Distância (m) do ponto ao obstáculo/área mais próximo."""
        lin, col = self.pl.celula(x, y)
        return float(self.dist[lin, col]) if self.pl.dentro(lin, col) else 0.0

    def planejar(self, origem, destino):
        """
        origem, destino: (x, y) em metros. Devolve (pontos, motivo):
        pontos = [(x, y), ...] do centro do robô, começando na origem e
        terminando no destino; ou (None, motivo) se não há caminho.
        """
        pl = self.pl
        s = pl.celula(*origem)
        g = pl.celula(*destino)
        if not pl.dentro(*s):
            return None, "o robô está fora da planta"
        if not pl.dentro(*g):
            return None, "o destino está fora da planta"
        saida = None
        if self.proibido[s]:
            # Parado na faixa de tolerância (o vigia deixou): primeiro sai dela
            # pela reta mais curta até fora da margem, depois a rota normal.
            saida = None if self.limite[s] else self._sair_da_faixa(s)
            if saida is None:
                return None, (f"o robô está perto demais de um obstáculo ou área "
                              f"(folga {self.dist[s] * 100:.0f} cm, margem "
                              f"{self.margem_m * 100:.0f} cm)")
        if self.proibido[g]:
            return None, (f"o destino está perto demais de um obstáculo ou área "
                          f"(folga {self.dist[g] * 100:.0f} cm)")

        caminho = self._astar(saida or s, g)
        if caminho is None:
            return None, "não há caminho livre até o destino"
        pontos = [pl.centro(*c) for c in self._encurtar(caminho)]
        if saida is not None:
            pontos.insert(0, tuple(origem))
        pontos[0] = tuple(origem)
        pontos[-1] = tuple(destino)
        pontos, motivo = self._alinhar_portas(pontos)
        return (pontos, "") if pontos is not None else (None, motivo)

    def _ve_porta(self, u, v) -> bool:
        """Reta que liga a rota a um ponto antes/depois de porta."""
        return self.reta_passavel(u, v)

    @staticmethod
    def _no_canal(g, q):
        dx, dy = q[0] - g["c"][0], q[1] - g["c"][1]
        return (abs(dx * g["t"][0] + dy * g["t"][1]) <= g["largura"] / 2
                and abs(dx * g["n"][0] + dy * g["n"][1]) < g["meio"] - 0.05)

    def _alinhar_portas(self, pontos):
        """Trecho que cruza uma porta vira: ponto ANTES → ponto DEPOIS, no eixo,
        sem vértice (giro) dentro do vão; liga cada um ao vértice mais distante
        da rota que ele enxerga (_ve_porta) e some com a escada entre eles. Se
        nada liga, fica a rota do A* (que já atravessa pela faixa do eixo)."""
        for g in self.portas:
            cx, cy = g["c"]
            meia = g["largura"] / 2
            a = (cx - g["t"][0] * meia, cy - g["t"][1] * meia)
            b = (cx + g["t"][0] * meia, cy + g["t"][1] * meia)
            for k in range(len(pontos) - 1):
                if not _cruza(pontos[k], pontos[k + 1], a, b):
                    continue
                # de que lado está quem vem: o ponto do mesmo lado vem primeiro
                lado = ((pontos[k][0] - cx) * g["n"][0] + (pontos[k][1] - cy) * g["n"][1]) < 0
                p1, p2 = g["lados"] if lado else g["lados"][::-1]
                # um vértice DENTRO da zona, entre a porta e o ponto, não serve:
                # a rota iria até ele e voltaria ao ponto (28/10, maker-corredor)
                def fora(q, e):
                    return e or not self._no_canal(g, q)
                i = next((i for i in range(k + 1)
                          if fora(pontos[i], i == 0) and self._ve_porta(pontos[i], p1)), None)
                j = next((j for j in range(len(pontos) - 1, k, -1)
                          if fora(pontos[j], j == len(pontos) - 1) and self._ve_porta(p2, pontos[j])), None)
                if i is not None and j is not None and self._ve_porta(p1, p2):
                    meio, motivo = self._manobra(g, pontos[i], p1, p2, pontos[j],
                                                 pontos[i - 1] if i > 0 else None,
                                                 pontos[j + 1] if j + 1 < len(pontos) else None)
                    if meio is None:
                        return None, motivo
                    novo = pontos[:i + 1] + meio + pontos[j:]
                    pontos = [novo[0]] + [p for q, p in enumerate(novo[1:], 1)
                                          if math.dist(p, novo[q - 1]) > 1e-6]
                break
        return pontos, ""

    # ─── o CORPO na porta (28/10/2026) ─────────
    def corpo(self):
        from slam.corpo import Corpo
        if self._corpo is None:
            pts = self._obstaculos
            if pts is None:                       # sem planta fina: as células
                l, c = np.nonzero(self.bloqueio)
                pts = np.column_stack([self.pl.min_x + (c + 0.5) * self.pl.res,
                                       self.pl.max_y - (l + 0.5) * self.pl.res])
            self._corpo = Corpo(pts)
        return self._corpo

    def pivo(self, a, b):
        """O trecho a → b é um GIRO SOBRE UMA RODA planejado aqui? Devolve
        {"rumo0", "giro"} (graus; giro + = à esquerda) ou None."""
        return self._pivos.get((round(a[0], 3), round(a[1], 3), round(b[0], 3), round(b[1], 3)))

    def _manobra(self, g, q, p1, p2, r, q0=None, r1=None):
        """Como passar pela porta g vindo de q, entrando por p1, saindo por p2,
        indo para r. Em cada lado: GIRAR PARADO no ponto (se o corpo cabe e a
        frente fica livre ao chegar) ou GIRAR SOBRE UMA RODA: chega de lado a
        um ponto ao lado do eixo, gira sobre a roda de dentro e termina no
        eixo, de frente para a porta (o canto do maker-corredor, 28/10). Testa
        a travessia deslocada até PORTA_DESVIO_MAX_M e fica com a de mais folga.
        q0/r1: os vértices antes de q e depois de r — o giro parado em q e em
        r também é conferido quando a folga do centro ali é menor que a margem.
        Devolve (pontos entre q e r, "") ou (None, motivo)."""
        from slam.corpo import CORPO_FOLGA_M, CORPO_FRENTE_LIVRE_M, ROBO_BITOLA_M
        corpo = self.corpo()
        R = ROBO_BITOLA_M / 2
        L = math.dist(p1, p2)
        u = ((p2[0] - p1[0]) / L, (p2[1] - p1[1]) / L)
        hu = math.degrees(math.atan2(u[1], u[0]))

        def rumo(a, b):
            return math.degrees(math.atan2(b[1] - a[1], b[0] - a[0]))

        def lado(p, x):          # perpendicular ao eixo, para o lado de x
            w = (-u[1], u[0])
            return w if (x[0] - p[0]) * w[0] + (x[1] - p[1]) * w[1] >= 0 else (-w[0], -w[1])

        def frente(p, h):        # a frente livre ao chegar, como folga do corpo
            return corpo.frente(*p, h) - CORPO_FRENTE_LIVRE_M + CORPO_FOLGA_M

        def giro_em(v, h0, h1):  # giro parado num vértice que a margem não protege
            if h0 is None or h1 is None or self.folga(*v) >= self.margem_m:
                return 9.0
            return corpo.giro(*v, h0, h1)
        hq0 = rumo(q0, q) if q0 is not None and math.dist(q0, q) > 0.05 else None
        hr1 = rumo(r, r1) if r1 is not None and math.dist(r, r1) > 0.05 else None

        def entrada(p):
            """[(pontos, folga, pivô)] para chegar de q e ficar no eixo, rumo hu."""
            op = []
            if self._ve_porta(q, p):
                if math.dist(q, p) > 0.05:
                    f = min(frente(p, rumo(q, p)), corpo.giro(*p, rumo(q, p), hu),
                            giro_em(q, hq0, rumo(q, p)))
                else:
                    f = corpo.giro(*p, hu, hu)
                op.append(([p], f, None))
            w = lado(p, q)
            h0 = math.degrees(math.atan2(-w[1], -w[0]))
            giro = (hu - h0 + 180.0) % 360.0 - 180.0
            for d in PORTA_PIVO_AFASTA_M:
                a_ = (p[0] + w[0] * (R + d), p[1] + w[1] * (R + d))
                e_ = (p[0] + u[0] * R + w[0] * d, p[1] + u[1] * R + w[1] * d)
                if math.dist(q, a_) <= 0.05 or not (self._ve_porta(q, a_) and self._ve_porta(e_, p2)):
                    continue
                f = min(frente(a_, rumo(q, a_)), corpo.giro(*a_, rumo(q, a_), h0),
                        corpo.pivo(*a_, h0, giro), giro_em(q, hq0, rumo(q, a_)),
                        corpo.giro(*e_, hu, rumo(e_, p2)))
                op.append(([a_, e_], f, (a_, e_, h0, giro)))
            return op

        def saida(p):
            """[(pontos, folga, pivô)] para sair do eixo (rumo hu) em p e ir a r."""
            op = []
            if self._ve_porta(p, r):
                f = frente(p, hu)
                if math.dist(p, r) > 0.05:
                    f = min(f, corpo.giro(*p, hu, rumo(p, r)), giro_em(r, rumo(p, r), hr1))
                op.append(([p], f, None))
            w = lado(p, r)
            hw = math.degrees(math.atan2(w[1], w[0]))
            giro = (hw - hu + 180.0) % 360.0 - 180.0
            for d in PORTA_PIVO_AFASTA_M:
                e_ = (p[0] - u[0] * R + w[0] * d, p[1] - u[1] * R + w[1] * d)
                a_ = (p[0] + w[0] * (R + d), p[1] + w[1] * (R + d))
                if math.dist(a_, r) <= 0.05 or not (self._ve_porta(a_, r) and self._ve_porta(p1, e_)):
                    continue
                f = min(frente(e_, rumo(p1, e_)), corpo.giro(*e_, rumo(p1, e_), hu),
                        corpo.pivo(*e_, hu, giro),
                        corpo.giro(*a_, hw, rumo(a_, r)), giro_em(r, rumo(a_, r), hr1))
                op.append(([e_, a_], f, (e_, a_, hu, giro)))
            return op

        melhor = None
        t = g["t"]
        for o in sorted(np.arange(-PORTA_DESVIO_MAX_M, PORTA_DESVIO_MAX_M + 1e-9, 0.02), key=abs):
            o = float(o)
            d1 = (p1[0] + t[0] * o, p1[1] + t[1] * o)
            d2 = (p2[0] + t[0] * o, p2[1] + t[1] * o)
            if not self._ve_porta(d1, d2):
                continue
            for pe, fe, ve in entrada(d1):
                for ps, fs, vs in saida(d2):
                    f = min(fe, fs)
                    # folga até 10 cm conta; empate: sem pivô, depois menos desvio
                    nota = (round(min(f, 0.10), 3), -(ve is not None) - (vs is not None), -abs(o))
                    if melhor is None or nota > melhor[0]:
                        melhor = (nota, f, pe + ps, ve, vs)
        if melhor is None or melhor[1] < CORPO_FOLGA_M:
            f = 0.0 if melhor is None else max(melhor[1], 0.0)
            return None, (f"o robô não vira na porta sem encostar (sobram {f * 100:.0f} cm "
                          f"para o corpo; precisa de {CORPO_FOLGA_M * 100:.0f})")
        for v in (melhor[3], melhor[4]):
            if v is not None:
                a_, b_, h0, giro = v
                self._pivos[(round(a_[0], 3), round(a_[1], 3), round(b_[0], 3), round(b_[1], 3))] = {
                    "rumo0": round(h0, 2), "giro": round(giro, 2)}
        return [tuple(round(v, 3) for v in q_) for q_ in melhor[2]], ""

    def _sair_da_faixa(self, s):
        """Célula fora da margem mais perto de s, até tolerância + 2 células,
        ligada a s por reta que não cruza o limite do vigia. None se não há."""
        r = int(math.ceil(self.tolerancia_m / self.pl.res)) + 2
        l0, c0 = s
        h, w = self.proibido.shape
        melhor = None
        for l in range(max(0, l0 - r), min(h, l0 + r + 1)):
            for c in range(max(0, c0 - r), min(w, c0 + r + 1)):
                if self.proibido[l, c]:
                    continue
                d = math.hypot(l - l0, c - c0)
                if d <= r and (melhor is None or d < melhor[0]):
                    n = int(d * 4) + 1
                    if all(not self.limite[int(round(l0 + (l - l0) * k / n)),
                                           int(round(c0 + (c - c0) * k / n))]
                           for k in range(n + 1)):
                        melhor = (d, (l, c))
        return None if melhor is None else melhor[1]

    # ─────────────────────────────────────────
    def _custo_celula(self, lin, col) -> float:
        extra = self.dist[lin, col] - self.margem_m
        if extra >= PREFERE_M:
            return 1.0
        return 1.0 + PESO_FOLGA * (1.0 - max(extra, 0.0) / PREFERE_M)

    def _astar(self, s, g):
        h, w = self.proibido.shape
        proib = self.proibido
        viz = [(-1, 0, 1.0), (1, 0, 1.0), (0, -1, 1.0), (0, 1, 1.0),
               (-1, -1, math.sqrt(2)), (-1, 1, math.sqrt(2)),
               (1, -1, math.sqrt(2)), (1, 1, math.sqrt(2))]
        gl, gc = g

        def heur(l, c):
            dl, dc = abs(l - gl), abs(c - gc)
            return (dl + dc) + (math.sqrt(2) - 2) * min(dl, dc)

        aberto = [(heur(*s), 0.0, s)]
        custo = {s: 0.0}
        veio = {}
        while aberto:
            _, cst, cel = heapq.heappop(aberto)
            if cel == g:
                rota = [cel]
                while cel in veio:
                    cel = veio[cel]
                    rota.append(cel)
                return rota[::-1]
            if cst > custo.get(cel, math.inf):
                continue
            l, c = cel
            for dl, dc, passo in viz:
                nl, nc = l + dl, c + dc
                if not (0 <= nl < h and 0 <= nc < w) or proib[nl, nc]:
                    continue
                # diagonal não corta quina de célula proibida
                if dl and dc and (proib[l, nc] or proib[nl, c]):
                    continue
                novo = cst + passo * self._custo_celula(nl, nc)
                if novo < custo.get((nl, nc), math.inf):
                    custo[(nl, nc)] = novo
                    veio[(nl, nc)] = cel
                    heapq.heappush(aberto, (novo + heur(nl, nc), novo, (nl, nc)))
        return None

    def _visivel(self, a, b, estrito: bool = False) -> bool:
        """Segmento reto entre centros de células sem tocar célula proibida
        (amostrado a cada 1/4 de célula). Pede a folga extra dos trechos
        retos, MENOS quando uma das pontas já está dentro dela (o robô
        parado perto de uma mesa, ou um POI perto de uma parede): aí vale só
        a margem. Sem isso, em 29/09 (P1, robô 11,6 cm fora da fita, para o
        lado da M4) toda rota começava com um trecho de 8 cm só para "sair
        da faixa" — um giro inútil."""
        (la, ca), (lb, cb) = a, b
        grade = self.proibido if (estrito or self._reta_proibida[a]
                                  or self._reta_proibida[b]) else self._reta_proibida
        n = int(max(abs(lb - la), abs(cb - ca)) * 4) + 1
        for k in range(n + 1):
            t = k / n
            l = int(round(la + (lb - la) * t))
            c = int(round(ca + (cb - ca) * t))
            if grade[l, c]:
                return False
        return True

    def _encurtar(self, rota):
        """Linha de visada: de cada ponto, pula para o mais distante visível.
        Vizinhos na rota do A* ficam sempre ligados (o A* já os aprovou).
        Depois, some com os trechos menores que TRECHO_MINIMO_M quando dá
        para ligar direto os vizinhos só pela margem."""
        out = [rota[0]]
        i = 0
        while i < len(rota) - 1:
            j = len(rota) - 1
            while j > i + 1 and not self._visivel(rota[i], rota[j]):
                j -= 1
            out.append(rota[j])
            i = j
        minimo = TRECHO_MINIMO_M / self.pl.res
        k = 1
        while k < len(out) - 1:
            curto = (math.dist(out[k - 1], out[k]) < minimo
                     or math.dist(out[k], out[k + 1]) < minimo)
            if curto and self._visivel(out[k - 1], out[k + 1], estrito=True):
                del out[k]
            else:
                k += 1
        return out


def _cruza(p1, p2, p3, p4) -> bool:
    """Os segmentos p1–p2 e p3–p4 se cruzam (tocar a ponta conta)."""
    def cruz(o, a, b):
        return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])
    d1, d2 = cruz(p3, p4, p1), cruz(p3, p4, p2)
    d3, d4 = cruz(p1, p2, p3), cruz(p1, p2, p4)
    return (d1 * d2 <= 0) and (d3 * d4 <= 0)


def comprimento(pontos) -> float:
    return sum(math.hypot(b[0] - a[0], b[1] - a[1]) for a, b in zip(pontos, pontos[1:]))
