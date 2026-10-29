"""
slam/corpo.py — o CORPO do robô contra a planta fina (28/10/2026).

O planejador trata o robô como um PONTO (o centro) e cresce os obstáculos pela
margem de 50 cm, que já cobre o círculo que ele varre girando parado (36,6 cm).
Na PORTA a margem cai para 30 cm e isso deixa de valer: em 28/10 o robô 1
encostou de frente na parede da folha, no canto da sala do maker-corredor, num
ponto de giro a ~27 cm dela. Aqui o robô é o RETÂNGULO de verdade, conferido
contra os pontos da planta fina (C1 de cima e de 22 cm, 2 cm, depois da L3) —
a melhor medida das superfícies que o sistema tem.

Usado só onde a margem não protege (os pontos da porta): girar parado, girar
sobre uma roda (pivô) e chegar de frente (o bumper precisa de espaço).
"""
import math

import numpy as np

# Robô 1 (42 × 60 cm, rodas no centro). Bitola medida pelo Prof. em 28/10/2026:
# 30,5 cm do meio de um pneu ao meio do outro.
ROBO_FRENTE_M = 0.30
ROBO_TRAS_M = 0.30
ROBO_MEIA_LARGURA_M = 0.21
ROBO_BITOLA_M = 0.305
# Folga mínima do corpo às superfícies da planta fina (localização ~3–5 cm).
CORPO_FOLGA_M = 0.05
# Chegando de frente a um ponto da porta: espaço livre à frente do robô. O
# bumper da porta (MISSAO_BUMPER_PORTA_M, 20 cm) só age se passar do ponto.
CORPO_FRENTE_LIVRE_M = 0.25
CORPO_PASSO_GIRO_DEG = 3.0
# Folga acima disto não muda a escolha da manobra: os pontos mais longe que
# isto do que o corpo varre nem entram na conta (velocidade, 28/10).
CORPO_FOLGA_CONTA_M = 0.15
_RAIO_CORPO = math.hypot(max(0.30, 0.30), 0.21)


def pontos_fino(png, meta, vizinhos_min=2):
    """(N, 2) com o centro de cada célula marcada da planta fina; ponto solto
    (menos de vizinhos_min marcados em volta, 3×3) é ruído e sai."""
    from PIL import Image
    a = np.array(Image.open(png).convert("RGBA"))[:, :, 3] > 0
    p = np.pad(a, 1).astype(np.int8)
    viz = sum(p[1 + dl:p.shape[0] - 1 + dl, 1 + dc:p.shape[1] - 1 + dc]
              for dl in (-1, 0, 1) for dc in (-1, 0, 1)) - a
    lin, col = np.nonzero(a & (viz >= vizinhos_min))
    r = meta["res"]
    return np.column_stack([meta["min_x"] + (col + 0.5) * r, meta["max_y"] - (lin + 0.5) * r])


class Corpo:

    def __init__(self, pontos):
        self.p = np.asarray(pontos, float).reshape(-1, 2)

    def _perto(self, x, y, r):
        q = self.p
        k = (np.abs(q[:, 0] - x) < r) & (np.abs(q[:, 1] - y) < r)
        return q[k]

    def local(self, x, y, r):
        """Só os pontos a até r (quadrado) de (x, y): a manobra de uma porta
        confere centenas de poses — com a planta inteira (~40 mil pontos)
        levava ~5 s no PC e travou o loop de 50 Hz na Pi (28/10, 12:16)."""
        return Corpo(self._perto(x, y, r))

    def distancias(self, poses) -> float:
        """Menor distância do retângulo a um ponto, em várias poses (x, y, rumo) de uma vez."""
        q = self.p
        if not len(q) or not len(poses):
            return 9.0                 # nada perto: folga além do que se conta
        P = np.asarray(poses, float)
        a = np.radians(P[:, 2])[:, None]
        dx, dy = q[None, :, 0] - P[:, 0:1], q[None, :, 1] - P[:, 1:2]
        u = dx * np.cos(a) + dy * np.sin(a)
        v = -dx * np.sin(a) + dy * np.cos(a)
        du = np.maximum(np.maximum(-ROBO_TRAS_M - u, u - ROBO_FRENTE_M), 0.0)
        dv = np.maximum(np.abs(v) - ROBO_MEIA_LARGURA_M, 0.0)
        return float(np.hypot(du, dv).min())

    def distancia(self, x, y, rumo_deg, frente=ROBO_FRENTE_M) -> float:
        """Menor distância (m) do retângulo do robô a um ponto (0 = encostou).
        frente maior que ROBO_FRENTE_M estende a frente (espaço do bumper)."""
        q = self._perto(x, y, max(frente, ROBO_TRAS_M) + 1.0)
        if not len(q):
            return 9.0
        a = math.radians(rumo_deg)
        dx, dy = q[:, 0] - x, q[:, 1] - y
        u = dx * math.cos(a) + dy * math.sin(a)
        v = -dx * math.sin(a) + dy * math.cos(a)
        du = np.maximum(np.maximum(-ROBO_TRAS_M - u, u - frente), 0.0)
        dv = np.maximum(np.abs(v) - ROBO_MEIA_LARGURA_M, 0.0)
        return float(np.hypot(du, dv).min())

    def frente(self, x, y, rumo_deg) -> float:
        """Espaço livre à frente: distância de um ponto à faixa da largura do
        robô, entre a frente e a frente + CORPO_FRENTE_LIVRE_M."""
        q = self._perto(x, y, ROBO_FRENTE_M + CORPO_FRENTE_LIVRE_M + 0.5)
        if not len(q):
            return 9.0
        a = math.radians(rumo_deg)
        dx, dy = q[:, 0] - x, q[:, 1] - y
        u = dx * math.cos(a) + dy * math.sin(a)
        v = -dx * math.sin(a) + dy * math.cos(a)
        na_faixa = (np.abs(v) <= ROBO_MEIA_LARGURA_M) & (u >= ROBO_FRENTE_M)
        return float((u[na_faixa] - ROBO_FRENTE_M).min()) if na_faixa.any() else 9.0

    def giro(self, x, y, rumo0, rumo1) -> float:
        """Menor distância do corpo girando PARADO de rumo0 a rumo1 (pelo menor lado)."""
        d = _dif(rumo1, rumo0)
        n = max(1, int(abs(d) / CORPO_PASSO_GIRO_DEG))
        sub = self._circulo(x, y, _RAIO_CORPO + CORPO_FOLGA_CONTA_M)
        return sub.distancias([(x, y, rumo0 + d * k / n) for k in range(n + 1)])

    def pivo(self, x, y, rumo0, giro_deg) -> float:
        """Menor distância do corpo girando giro_deg (+ = à esquerda) sobre uma
        RODA (a de dentro parada), saindo de (x, y, rumo0)."""
        d = giro_deg
        n = max(1, int(abs(d) / CORPO_PASSO_GIRO_DEG))
        cx, cy = centro_pivo(x, y, rumo0, d)
        r = math.hypot(ROBO_BITOLA_M / 2 + ROBO_MEIA_LARGURA_M, ROBO_FRENTE_M)
        sub = self._circulo(cx, cy, r + CORPO_FOLGA_CONTA_M)
        return sub.distancias([pose_pivo(x, y, rumo0, d * k / n) for k in range(n + 1)])

    def arco(self, x, y, rumo0, giro_deg, raio) -> float:
        """Menor distância do corpo numa CURVA: o centro anda num arco de
        raio `raio`, saindo de (x, y, rumo0) e virando giro_deg (+ = à
        esquerda). raio = meia bitola é o pivô; a curva da porta (29/10)."""
        n = max(2, int(abs(giro_deg) / CORPO_PASSO_GIRO_DEG))
        cx, cy = centro_arco(x, y, rumo0, giro_deg, raio)
        r = raio + math.hypot(ROBO_MEIA_LARGURA_M, max(ROBO_FRENTE_M, ROBO_TRAS_M))
        sub = self._circulo(cx, cy, r + CORPO_FOLGA_CONTA_M)
        return sub.distancias([pose_arco(x, y, rumo0, giro_deg * k / n, raio)
                               for k in range(n + 1)])

    def _circulo(self, x, y, r):
        q = self._perto(x, y, r)
        return Corpo(q[(q[:, 0] - x) ** 2 + (q[:, 1] - y) ** 2 <= r * r])


def _dif(a, b):
    return (a - b + 180.0) % 360.0 - 180.0


def pose_pivo(x, y, rumo0, giro_deg):
    """Pose do centro depois de girar giro_deg (+ = esquerda) sobre a roda de
    dentro, partindo de (x, y, rumo0). Devolve (x, y, rumo)."""
    a = math.radians(rumo0)
    lado = 1.0 if giro_deg >= 0 else -1.0          # roda esquerda (+) ou direita (−)
    r = ROBO_BITOLA_M / 2
    cx, cy = x - lado * r * math.sin(a), y + lado * r * math.cos(a)
    b = a + math.radians(giro_deg)
    return cx + lado * r * math.sin(b), cy - lado * r * math.cos(b), math.degrees(b)


def centro_arco(x, y, rumo0, giro_deg, raio):
    """Centro da curva de raio `raio` que sai de (x, y, rumo0) virando para o
    lado de giro_deg (+ = esquerda)."""
    a = math.radians(rumo0)
    lado = 1.0 if giro_deg >= 0 else -1.0
    return x - lado * raio * math.sin(a), y + lado * raio * math.cos(a)


def pose_arco(x, y, rumo0, giro_deg, raio):
    """Pose do centro depois de virar giro_deg numa curva de raio `raio`."""
    cx, cy = centro_arco(x, y, rumo0, giro_deg, raio)
    lado = 1.0 if giro_deg >= 0 else -1.0
    b = math.radians(rumo0 + giro_deg)
    return cx + lado * raio * math.sin(b), cy - lado * raio * math.cos(b), rumo0 + giro_deg


def inicio_arco(fim, rumo_fim, giro_deg, raio):
    """O ponto onde começa a curva que, virando giro_deg, termina em `fim`
    com rumo_fim (o inverso de pose_arco)."""
    lado = 1.0 if giro_deg >= 0 else -1.0
    a, b = math.radians(rumo_fim), math.radians(rumo_fim - giro_deg)
    cx, cy = fim[0] - lado * raio * math.sin(a), fim[1] + lado * raio * math.cos(a)
    return cx + lado * raio * math.sin(b), cy - lado * raio * math.cos(b)


def centro_pivo(x, y, rumo0, giro_deg):
    a = math.radians(rumo0)
    lado = 1.0 if giro_deg >= 0 else -1.0
    r = ROBO_BITOLA_M / 2
    return x - lado * r * math.sin(a), y + lado * r * math.cos(a)


def encaixar_porta(pontos, a, b, fundo=0.30, busca=0.25):
    """Batentes desenhados à mão → as FACES dos batentes na planta fina, na
    mesma direção. Pega os pontos na faixa da parede (|n| ≤ fundo/2), acha o
    maior vão ao longo da porta que contém o meio desenhado (± busca) e devolve
    (a, b, deslocamento_m, vao_m) — ou None se a planta fina não mostra o vão."""
    (ax, ay), (bx, by) = a, b
    L = math.hypot(bx - ax, by - ay)
    if L < 1e-6:
        return None
    t = ((bx - ax) / L, (by - ay) / L)
    n = (-t[1], t[0])
    cx, cy = (ax + bx) / 2, (ay + by) / 2
    q = np.asarray(pontos, float).reshape(-1, 2)
    dx, dy = q[:, 0] - cx, q[:, 1] - cy
    s = dx * t[0] + dy * t[1]
    nn = dx * n[0] + dy * n[1]
    s = np.sort(s[(np.abs(nn) <= fundo / 2) & (np.abs(s) <= L / 2 + 0.6)])
    if len(s) < 4:
        return None
    s = np.concatenate([[-L / 2 - 0.6], s, [L / 2 + 0.6]])
    vaos = np.diff(s)
    k = int(np.argmax(np.where((s[:-1] < busca) & (s[1:] > -busca), vaos, -1.0)))
    e, d = float(s[k]), float(s[k + 1])
    if d - e <= 0.3 or e <= -L / 2 - 0.59 or d >= L / 2 + 0.59:
        return None
    meio = (e + d) / 2
    na = [cx + t[0] * e, cy + t[1] * e]
    nb = [cx + t[0] * d, cy + t[1] * d]
    return na, nb, meio, d - e
