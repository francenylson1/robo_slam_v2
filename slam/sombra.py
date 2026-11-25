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
              no campo de verossimilhança do mapa de 22 cm E no de 1,43 m ao
              mesmo tempo (cada volta no mapa da sua altura; 22/10/2026, N3),
              como a nota de qualidade. Sem o C1 de cima, só o de 22 cm.
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

from slam.mapa_c1 import _campo, _amostra, _gira, pontos_c1, pontos_c143, C1_NO_CENTRO, C1_SOMBRA

BNO_SENTIDO = -1.0          # Δrumo do Aurora = −Δyaw do BNO
# 25/11/2026: as rodas seguram de leve. Com o centro da fusão, a busca desconta
# PRIOR_RODAS × d² (d em m) de cada pose: 10 cm custam 0,01 de encaixe. Onde o
# mapa é plano ao longo do caminho (M5–M4, 24/11: pés de mesa trocados decidiam
# a pose), as rodas desempatam: pior erro 23 → 4 cm. Com evidência clara o C1
# ainda corrige (Aurora como régua, 23/10, 765 m com rodas +5 %: > 20 cm de 54
# para 22). 2 ou 4 já seguram demais (128 / 306 voltas > 20 cm). 0 = desligado.
PRIOR_RODAS = float(os.environ.get("FROTA_C1_PRIOR_RODAS", "1.0") or 0)


def carregar_grade(base):
    """c1_22 / c1_143 do pacote → (grade, campo), ou None se não houver."""
    from PIL import Image
    if not (os.path.isfile(base + ".png") and os.path.isfile(base + ".json")):
        return None
    meta = json.load(open(base + ".json", encoding="utf-8"))
    img = np.array(Image.open(base + ".png").convert("L"))
    grade = dict(meta, parede=(img < 128))
    return grade, _campo(grade)


class CampoRapido:
    """O campo de um mapa pronto para a busca AO VIVO (17/11/2026). A mesma
    interpolação bilinear de mapa_c1._amostra, sem máscara nem cópias: o campo
    ganha uma borda de zeros (MARGEM_M) e cada leitura é um índice só no vetor
    achatado, em float32. No replay do robô 2 (~7 voltas/s) a busca original
    levava ~280 ms por volta no PC; a volta do C1 chega a cada ~140 ms."""
    MARGEM_M = 1.0

    def __init__(self, grade, campo):
        res = float(grade["res"])
        m = int(math.ceil(self.MARGEM_M / res))
        H, W = campo.shape
        f = np.zeros((H + 2 * m, W + 2 * m), np.float32)
        f[m:m + H, m:m + W] = campo
        self.f = f.ravel()
        self.W, self.H = W + 2 * m, H + 2 * m
        self.inv = 1.0 / res
        self.c_off = -grade["min_x"] * self.inv - 0.5 + m     # coluna = x·inv + c_off
        self.l_off = grade["max_y"] * self.inv - 0.5 + m      # linha  = l_off − y·inv

    def amostra(self, wx, wy):
        c = np.clip(wx * self.inv + self.c_off, 0.0, self.W - 2.001)
        l = np.clip(self.l_off - wy * self.inv, 0.0, self.H - 2.001)
        c0 = c.astype(np.int32)
        l0 = l.astype(np.int32)
        fc = (c - c0).astype(np.float32)
        fl = (l - l0).astype(np.float32)
        i = l0 * self.W + c0
        f = self.f
        a = f[i] + (f[i + 1] - f[i]) * fc
        b = f[i + self.W] + (f[i + self.W + 1] - f[i + self.W]) * fc
        return a + (b - a) * fl


def _busca(grupos, x0, y0, r0, etapas, prior=0.0, centro=None):
    """Busca grosso→fino. Com centro (a previsão das rodas + BNO) e prior > 0,
    cada pose candidata perde prior × (distância ao centro, m)²: as rodas
    seguram DE LEVE (25/11/2026). Devolve o encaixe SEM a penalidade."""
    total = sum(len(g[0]) for g in grupos) or 1
    melhor = (-1e9, x0, y0, r0)
    nota = -1.0
    usa_prior = prior > 0.0 and centro is not None
    for passo_xy, passo_r, raio_xy, raio_r in etapas:
        _, cx, cy, cr = melhor
        dxs = np.arange(-raio_xy, raio_xy + 1e-9, passo_xy)
        gx, gy = np.meshgrid(cx + dxs, cy + dxs)
        gx, gy = gx.ravel(), gy.ravel()
        pen = prior * ((gx - centro[0]) ** 2 + (gy - centro[1]) ** 2) if usa_prior else 0.0
        for r in np.arange(cr - raio_r, cr + raio_r + 1e-9, passo_r):
            s = np.zeros(len(gx))
            for g in grupos:
                px, py = _gira(g[0], g[1], r)
                wx, wy = gx[:, None] + px[None, :], gy[:, None] + py[None, :]
                v = g[2].amostra(wx, wy) if len(g) == 3 else _amostra(g[2], g[3], wx, wy)
                s += v.sum(axis=1)
            s /= total
            sp = s - pen
            i = int(np.argmax(sp))
            if sp[i] > melhor[0]:
                melhor = (float(sp[i]), gx[i], gy[i], r)
                nota = float(s[i])
    return (nota,) + melhor[1:]


class Rastreador:

    def __init__(self, g22, g143=None, *, busca_m=0.15, busca_deg=4.0,
                 limiar=0.60, salto_m=0.45, max_pontos=275, prior_rodas=PRIOR_RODAS):
        self.g22, self.g143 = g22, g143
        self.prior_rodas = prior_rodas
        self.r22 = CampoRapido(*g22) if g22 is not None else None
        self.r143 = CampoRapido(*g143) if g143 is not None else None
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
        # 17/11/2026: a etapa do meio era 1 cm em ±6 cm e ±1,5° (1.183 poses, o
        # grosso do tempo). 2 cm em ±4 cm e ±1° acha o mesmo: no replay do robô 2
        # (2.138 voltas) mesmo fim (3,6 cm), 0 perdas, de 99 para 30 ms por volta.
        return ((0.05, 1.0, b, raio_r), (0.02, 0.5, 0.04, 1.0), (0.005, 0.25, 0.01, 0.5))

    def _sub(self, sx, sy):
        if len(sx) > self.max_pontos:
            k = np.linspace(0, len(sx) - 1, self.max_pontos).astype(int)
            return sx[k], sy[k]
        return sx, sy

    def passo(self, ang_deg, d_m, yaw=None, topo=None, centro=None):
        """Uma varredura do C1 (ângulos em graus, como o C1 entrega; distâncias
        em m) e, se houver, a do C1 de cima: topo = (ângulos, distâncias).
        centro = (x, y) previsto pelas rodas + BNO (fusão): a busca parte dele
        e não da última pose do C1 (18/11: preso num encaixe vizinho).
        Devolve (x, y, rumo, encaixe, perdido)."""
        if self.pose is None:
            return None
        x, y, r = self.pose
        if centro is not None:
            x, y = float(centro[0]), float(centro[1])
        giro = 0.0
        if yaw is not None and self.yaw is not None:
            giro = BNO_SENTIDO * (((yaw - self.yaw) + 180.0) % 360.0 - 180.0)
        self.yaw = yaw if yaw is not None else self.yaw
        sx, sy = self._sub(*pontos_c1(np.asarray(ang_deg, float), np.asarray(d_m, float)))
        grupos = [(sx, sy, self.r22)] if len(sx) >= 20 else []
        if topo is not None and self.g143 is not None:
            tx, ty = self._sub(*pontos_c143(np.asarray(topo[0], float), np.asarray(topo[1], float)))
            if len(tx) >= 20:
                grupos.append((tx, ty, self.r143))
        if not grupos:
            return x, y, r, self.encaixe, self.perdido
        enc, nx, ny, nr = _busca(grupos, x, y, r + giro,
                                 self._etapas(self.busca_deg + abs(giro) * 0.3),
                                 self.prior_rodas, centro)
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
