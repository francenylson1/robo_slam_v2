"""
slam/sombra.py
O LOCALIZADOR C1 — a posição do robô calculada só com o que um robô SEM Aurora
tem: o C1, o mapa dos C1 do pacote (slam/mapa_c1.py) e o BNO. No robô 1 roda
em MODO SOMBRA, ao lado do Aurora, só para medir (decidido com o professor em
02/10/2026, S1–S4; contrato da V1, objetivo 1.2). Nada aqui move o robô.

COMO ACOMPANHA (varredura após varredura):
  previsão  — rumo anterior + o quanto o BNO girou (o BNO gira no sentido
              CONTRÁRIO ao rumo do Aurora: razão −0,99 em 337 giros, 01/10);
              a posição fica onde estava (não há odometria: os Hall não dão o
              sentido). O mapa decide o quanto o robô andou.
  correção  — busca local grosso→fino em torno da previsão (±busca_m, ±busca_deg),
              no campo de verossimilhança do mapa de 22 cm (e no de 1,45 m,
              quando houver), como a nota de qualidade.
  perdido   — encaixe abaixo do limiar ou salto maior que salto_m. No robô 1 o
              serviço recoloca a sombra na pose do Aurora e conta a perda; no
              robô 2 "perdido" vai querer dizer parar.

Só cálculo: sem threads, sem SDK, sem GPIO. Quem roda isto num processo à
parte é slam/sombra_proc.py (os laços em Python segurariam o GIL do loop de
50 Hz).
"""

import json
import math
import os

import numpy as np

from slam.mapa_c1 import _campo, _amostra, _gira, pontos_c1, C1_NO_CENTRO, C1_SOMBRA

BNO_SENTIDO = -1.0          # Δrumo do Aurora = −Δyaw do BNO


def carregar_grade(base):
    """c1_22 / c1_145 do pacote → (grade, campo), ou None se não houver."""
    from PIL import Image
    if not (os.path.isfile(base + ".png") and os.path.isfile(base + ".json")):
        return None
    meta = json.load(open(base + ".json", encoding="utf-8"))
    img = np.array(Image.open(base + ".png").convert("L"))
    grade = dict(meta, parede=(img < 128))
    return grade, _campo(grade)


def _busca(grupos, x0, y0, r0, etapas):
    total = sum(len(g[0]) for g in grupos) or 1
    melhor = (-1.0, x0, y0, r0)
    for passo_xy, passo_r, raio_xy, raio_r in etapas:
        _, cx, cy, cr = melhor
        dxs = np.arange(-raio_xy, raio_xy + 1e-9, passo_xy)
        gx, gy = np.meshgrid(cx + dxs, cy + dxs)
        gx, gy = gx.ravel(), gy.ravel()
        for r in np.arange(cr - raio_r, cr + raio_r + 1e-9, passo_r):
            s = np.zeros(len(gx))
            for sx, sy, grade, campo in grupos:
                px, py = _gira(sx, sy, r)
                s += _amostra(grade, campo, gx[:, None] + px[None, :],
                              gy[:, None] + py[None, :]).sum(axis=1)
            s /= total
            i = int(np.argmax(s))
            if s[i] > melhor[0]:
                melhor = (float(s[i]), gx[i], gy[i], r)
    return melhor


class Rastreador:

    def __init__(self, g22, g145=None, *, busca_m=0.15, busca_deg=4.0,
                 limiar=0.60, salto_m=0.45, max_pontos=275):
        self.g22, self.g145 = g22, g145
        self.busca_m, self.busca_deg = busca_m, busca_deg
        self.limiar, self.salto_m = limiar, salto_m
        self.max_pontos = max_pontos
        self.pose = None            # (x, y, rumo) do CENTRO, referencial do mapa
        self.yaw = None             # último yaw do BNO (graus)
        self.encaixe = None
        self.perdido = True
        self.perdas = 0

    def semear(self, x, y, rumo, yaw=None):
        self.pose, self.yaw = (float(x), float(y), float(rumo)), yaw
        self.perdido, self.encaixe = False, None

    def _etapas(self, raio_r):
        b = self.busca_m
        return ((0.05, 1.0, b, raio_r), (0.01, 0.5, 0.06, 1.5), (0.005, 0.25, 0.015, 0.5))

    def passo(self, ang_deg, d_m, yaw=None):
        """Uma varredura do C1 (ângulos em graus, como o C1 entrega; distâncias
        em m). Devolve (x, y, rumo, encaixe, perdido)."""
        if self.pose is None:
            return None
        x, y, r = self.pose
        giro = 0.0
        if yaw is not None and self.yaw is not None:
            giro = BNO_SENTIDO * (((yaw - self.yaw) + 180.0) % 360.0 - 180.0)
        self.yaw = yaw if yaw is not None else self.yaw
        ang, d = np.asarray(ang_deg, float), np.asarray(d_m, float)
        if len(ang) > self.max_pontos:
            k = np.linspace(0, len(ang) - 1, self.max_pontos).astype(int)
            ang, d = ang[k], d[k]
        sx, sy = pontos_c1(ang, d)
        if len(sx) < 20:
            return x, y, r, self.encaixe, self.perdido
        g, c = self.g22
        enc, nx, ny, nr = _busca([(sx, sy, g, c)], x, y, r + giro,
                                 self._etapas(self.busca_deg + abs(giro) * 0.3))
        salto = math.hypot(nx - x, ny - y)
        self.encaixe = round(enc, 3)
        if enc < self.limiar or salto > self.salto_m:
            if not self.perdido:
                self.perdas += 1
            self.perdido = True
            return x, y, r + giro, self.encaixe, True
        self.perdido = False
        self.pose = (nx, ny, (nr + 180.0) % 360.0 - 180.0)
        return self.pose + (self.encaixe, False)


_ = (C1_NO_CENTRO, C1_SOMBRA)
