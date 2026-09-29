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
    """Distância (m) de cada célula ao bloqueio mais próximo — chanfro 3-4."""
    INF = 1 << 30
    h, w = bloq.shape
    d = np.where(bloq, 0, INF).astype(np.int64)
    # borda da grade conta como bloqueio (fora do mapa não se anda)
    d[0, :] = 0; d[-1, :] = 0; d[:, 0] = 0; d[:, -1] = 0
    for lin in range(1, h):             # ida
        linha, acima = d[lin], d[lin - 1]
        for col in range(1, w - 1):
            v = min(linha[col], acima[col] + 3, acima[col - 1] + 4,
                    acima[col + 1] + 4, linha[col - 1] + 3)
            linha[col] = v
    for lin in range(h - 2, -1, -1):    # volta
        linha, abaixo = d[lin], d[lin + 1]
        for col in range(w - 2, 0, -1):
            v = min(linha[col], abaixo[col] + 3, abaixo[col - 1] + 4,
                    abaixo[col + 1] + 4, linha[col + 1] + 3)
            linha[col] = v
    return d.astype(float) / 3.0 * res


class Planejador:

    def __init__(self, planta: Planta, areas, margem_m: float):
        self.pl = planta
        self.margem_m = margem_m
        bloq = planta.grade != LIVRE           # parede e desconhecido
        for a in areas:
            _rasterizar(planta, a["pontos"], bloq)
        self.bloqueio = bloq
        self.dist = _distancia(bloq, planta.res)
        self.proibido = self.dist < margem_m
        self._reta_proibida = self.dist < margem_m + FOLGA_RETA_M

    # ─────────────────────────────────────────
    def livre(self, x: float, y: float) -> bool:
        lin, col = self.pl.celula(x, y)
        return self.pl.dentro(lin, col) and not self.proibido[lin, col]

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
        if self.proibido[s]:
            return None, (f"o robô está perto demais de um obstáculo ou área "
                          f"(folga {self.dist[s] * 100:.0f} cm, margem "
                          f"{self.margem_m * 100:.0f} cm)")
        if self.proibido[g]:
            return None, (f"o destino está perto demais de um obstáculo ou área "
                          f"(folga {self.dist[g] * 100:.0f} cm)")

        caminho = self._astar(s, g)
        if caminho is None:
            return None, "não há caminho livre até o destino"
        pontos = [pl.centro(*c) for c in self._encurtar(caminho)]
        pontos[0] = tuple(origem)
        pontos[-1] = tuple(destino)
        return pontos, ""

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

    def _visivel(self, a, b) -> bool:
        """Segmento reto entre centros de células sem tocar célula proibida
        (amostrado a cada 1/4 de célula)."""
        (la, ca), (lb, cb) = a, b
        n = int(max(abs(lb - la), abs(cb - ca)) * 4) + 1
        for k in range(n + 1):
            t = k / n
            l = int(round(la + (lb - la) * t))
            c = int(round(ca + (cb - ca) * t))
            if self._reta_proibida[l, c]:
                return False
        return True

    def _encurtar(self, rota):
        """Linha de visada: de cada ponto, pula para o mais distante visível.
        Vizinhos na rota do A* ficam sempre ligados (o A* já os aprovou)."""
        out = [rota[0]]
        i = 0
        while i < len(rota) - 1:
            j = len(rota) - 1
            while j > i + 1 and not self._visivel(rota[i], rota[j]):
                j -= 1
            out.append(rota[j])
            i = j
        return out


def comprimento(pontos) -> float:
    return sum(math.hypot(b[0] - a[0], b[1] - a[1]) for a, b in zip(pontos, pontos[1:]))
