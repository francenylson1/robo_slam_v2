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
# A FOLHA muda de lugar: na coleta de 23/10 ela estava aberta ~75° e o C1 de
# cima a gravou como uma "parede" de ~1 m saindo do batente para dentro da
# sala, fechando a passagem (o Prof. mediu 85 cm livres com ela encostada). O
# mapa guarda a folha onde ela estava num dia; a porta limpa da planta da rota
# a área por onde a folha gira — o vão × PORTA_FOLHA_FATOR × o vão, dos dois
# lados (a folha é um pouco maior que o vão livre, por causa do batente). Folha
# atravessada de verdade é obstáculo do momento: o bumper ao vivo cuida.
PORTA_FOLHA_FATOR = 1.25


def porta_geometria(p, fundo=PORTA_FUNDO_M, alcance=PORTA_ALCANCE_M):
    """Centro, largura, direção do vão (t), normal (n) e os pontos antes/depois."""
    (ax, ay), (bx, by) = p["a"], p["b"]
    largura = math.hypot(bx - ax, by - ay)
    tx, ty = (bx - ax) / largura, (by - ay) / largura
    nx, ny = -ty, tx
    cx, cy = (ax + bx) / 2, (ay + by) / 2
    meio = fundo / 2 + alcance
    return {"c": (cx, cy), "largura": largura, "t": (tx, ty), "n": (nx, ny),
            "meio": meio, "giro_folha": max(fundo / 2, PORTA_FOLHA_FATOR * largura),
            "lados": ((cx - nx * meio, cy - ny * meio), (cx + nx * meio, cy + ny * meio))}


def _local(pl, g, l0, l1, c0, c1):
    """Coordenadas (s ao longo do vão, n atravessando) das células da janela."""
    lin, col = np.mgrid[l0:l1, c0:c1]
    x = pl.min_x + (col + 0.5) * pl.res - g["c"][0]
    y = pl.max_y - (lin + 0.5) * pl.res - g["c"][1]
    return x * g["t"][0] + y * g["t"][1], x * g["n"][0] + y * g["n"][1]


def _janela(pl, g):
    r = g["largura"] / 2 + max(g["meio"], g["giro_folha"]) + pl.res
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
                 portas=()):
        self.pl = planta
        self.margem_m = margem_m
        self.tolerancia_m = tolerancia_m
        bloq = planta.grade != LIVRE           # parede e desconhecido
        for a in areas:
            _rasterizar(planta, a["pontos"], bloq)
        # O vão da porta e a área por onde a folha gira são chão: o que a
        # coleta gravou ali (a folha num ângulo, manchas no batente) sai.
        self.portas = [porta_geometria(p) for p in portas]
        for g in self.portas:
            l0, l1, c0, c1 = _janela(planta, g)
            s, n = _local(planta, g, l0, l1, c0, c1)
            vao = (np.abs(s) < g["largura"] / 2 - planta.res) & (np.abs(n) <= g["giro_folha"])
            bloq[l0:l1, c0:c1][vao] = False
        self.bloqueio = bloq
        self.dist = _distancia(bloq, planta.res)
        self.proibido = self.dist < margem_m
        # o vigia da missão só para abaixo disto (NAV_TOLERANCIA_M, 26/10)
        self.limite = self.dist < margem_m - tolerancia_m
        self._reta_proibida = self.dist < margem_m + FOLGA_RETA_M
        # A faixa no eixo de cada porta, com a margem de passagem.
        self._porta_vigia = np.zeros_like(self.proibido)
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

    def na_porta(self, x: float, y: float) -> bool:
        """Centro do robô no trecho reto de alguma porta (passa devagar)."""
        for g in self.portas:
            dx, dy = x - g["c"][0], y - g["c"][1]
            if (abs(dx * g["t"][0] + dy * g["t"][1]) <= g["largura"] / 2
                    and abs(dx * g["n"][0] + dy * g["n"][1]) <= g["meio"]):
                return True
        return False

    # ─────────────────────────────────────────
    def livre(self, x: float, y: float) -> bool:
        lin, col = self.pl.celula(x, y)
        return self.pl.dentro(lin, col) and not self.proibido[lin, col]

    def passavel(self, x: float, y: float) -> bool:
        """Para a reta de um trecho já planejado: livre, ou dentro da porta no
        desvio que o vigia aceita (o robô chega ao ponto antes dela com 3–8 cm
        de erro e a reta até o ponto depois não fica exatamente no eixo)."""
        lin, col = self.pl.celula(x, y)
        return self.pl.dentro(lin, col) and (not self.proibido[lin, col]
                                             or bool(self._porta_vigia[lin, col]))

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
        return self._alinhar_portas(pontos), ""

    def _ve_porta(self, u, v) -> bool:
        """Reta que liga a rota a um ponto antes/depois de porta: fora da faixa
        da porta, folga ≥ margem − tolerância/2 (no maker-corredor, logo depois
        da porta, parede e armário a 1,15 m: com 0,50 cheio só sobrava uma
        escada de trechos curtos; o vigia para em 0,42 — sobram 4 cm)."""
        (la, ca), (lb, cb) = self.pl.celula(*u), self.pl.celula(*v)
        n = int(max(abs(lb - la), abs(cb - ca)) * 4) + 1
        for k in range(n + 1):
            c = (int(round(la + (lb - la) * k / n)), int(round(ca + (cb - ca) * k / n)))
            if not self._porta_vigia[c] and self.dist[c] < self.margem_m - self.tolerancia_m / 2:
                return False
        return True

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
                i = next((i for i in range(k + 1) if self._ve_porta(pontos[i], p1)), None)
                j = next((j for j in range(len(pontos) - 1, k, -1)
                          if self._ve_porta(p2, pontos[j])), None)
                if i is not None and j is not None and self._ve_porta(p1, p2):
                    novo = pontos[:i + 1] + [p1, p2] + pontos[j:]
                    pontos = [novo[0]] + [p for q, p in enumerate(novo[1:], 1)
                                          if math.dist(p, novo[q - 1]) > 1e-6]
                break
        return pontos

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
