"""
scripts/simula_c1_145.py — 01/10/2026.
Uso (no PC): python scripts/simula_c1_145.py <pasta>, com a planta do Aurora
(lab_metade_20260925_planta.png/json) e arquivos .jsonl do gravador (qualquer
linha com "t" e "pose"; usa as das 16-17 h). Resultado de 01/10 (poses de
30/09): ~1,4-2,0 cm de mediana, p90 2,9-3,7 cm — OTIMISTA: o mundo é o próprio
mapa. A medida real vem do laser do Aurora gravado no campo "a145".

Simulação: C1 a 1,45 m (plano do laser do Aurora) localizando no mapa 2D do Aurora.
Mundo = a própria planta do Aurora (otimista: mapa e mundo são idênticos).
Varreduras sintéticas em poses REAIS do robô (Aurora, 30/09, 16-17 h).
Mesmo localizador do teste de 30/09: campo de verossimilhança σ 10 cm, busca em grade
partindo de ±30 cm/±8° (local) e de ±1 m/±30° (robô "quase perdido").
"""
import json, math, random, sys, time
import numpy as np
from PIL import Image
from scipy import ndimage

AQUI = sys.argv[1] if len(sys.argv) > 1 else "."
random.seed(1); rng = np.random.default_rng(1)
pl = json.load(open(f"{AQUI}/lab_metade_20260925_planta.json"))
img = np.array(Image.open(f"{AQUI}/lab_metade_20260925_planta.png"))
RES, MINX, MAXY = pl["res"], pl["min_x"], pl["max_y"]
H, W = img.shape
parede = img < 100
dist_parede = ndimage.distance_transform_edt(~parede) * RES
CAMPO = np.exp(-(dist_parede ** 2) / (2 * 0.10 ** 2))

N_FEIXES = 275           # medido no C1: ~275 pontos por volta
SIGMA_R = 0.02           # ruído de distância (2 cm) + 1% da distância
PERDA = 0.10             # 10% dos feixes sem retorno


def raycast(x, y, rumo_deg, alcance):
    ang = np.radians(rumo_deg) + np.linspace(0, 2 * np.pi, N_FEIXES, endpoint=False)
    ang += rng.uniform(0, 2 * np.pi / N_FEIXES)
    passos = np.arange(0.05, alcance, 0.01)
    px = x + np.outer(np.cos(ang), passos); py = y + np.outer(np.sin(ang), passos)
    col = ((px - MINX) / RES).astype(int); lin = ((MAXY - py) / RES).astype(int)
    fora = (col < 0) | (col >= W) | (lin < 0) | (lin >= H)
    bate = np.zeros_like(fora)
    bate[~fora] = parede[lin[~fora], col[~fora]]
    tem = bate.any(axis=1)
    idx = bate.argmax(axis=1)
    d = passos[idx]
    rel = ang - np.radians(rumo_deg)
    return rel[tem], d[tem]


def ruido(rel, d, pessoas=0, x=0, y=0, rumo=0):
    d = d + rng.normal(0, SIGMA_R + 0.01 * d)
    ok = rng.random(len(d)) > PERDA
    # pessoas: tronco ~45 cm a 1–4 m do robô, tapam o feixe (retorno no tronco)
    for _ in range(pessoas):
        pa = rng.uniform(0, 2 * np.pi); pd = rng.uniform(1.0, 4.0)
        meia = math.atan2(0.225, pd)
        dif = np.abs((rel - pa + np.pi) % (2 * np.pi) - np.pi)
        tapa = (dif < meia) & (d > pd)
        d = np.where(tapa, pd + rng.normal(0, 0.02, len(d)), d)
    return rel[ok], d[ok]


def nota(rel, d, x, y, r):
    t = math.radians(r)
    wx = x + d * np.cos(rel + t); wy = y + d * np.sin(rel + t)
    col = ((wx - MINX) / RES).astype(int); lin = ((MAXY - wy) / RES).astype(int)
    ok = (col >= 0) & (col < W) & (lin >= 0) & (lin < H)
    v = np.zeros(len(wx)); v[ok] = CAMPO[lin[ok], col[ok]]
    return v.mean()


def buscar(rel, d, x0, y0, r0, etapas):
    melhor = (-1, x0, y0, r0)
    for passo_xy, passo_r, raio_xy, raio_r in etapas:
        cx, cy, cr = melhor[1:]
        for dx in np.arange(-raio_xy, raio_xy + 1e-9, passo_xy):
            for dy in np.arange(-raio_xy, raio_xy + 1e-9, passo_xy):
                for drr in np.arange(-raio_r, raio_r + 1e-9, passo_r):
                    s = nota(rel, d, cx + dx, cy + dy, cr + drr)
                    if s > melhor[0]:
                        melhor = (s, cx + dx, cy + dy, cr + drr)
    return melhor


LOCAL = ((0.05, 2.0, 0.40, 12.0), (0.01, 0.5, 0.06, 2.0))
PERDIDO = ((0.10, 4.0, 1.20, 36.0), (0.03, 1.0, 0.15, 5.0), (0.01, 0.5, 0.04, 1.5))

poses = []
import glob
for l in (l for f in sorted(glob.glob(f"{AQUI}/*.jsonl")) for l in open(f, encoding="utf-8")):
    try:
        j = json.loads(l)
    except ValueError:
        continue
    if j.get("pose") and 16 <= int(time.strftime("%H", time.localtime(j["t"]))) <= 17:
        p = j["pose"]; poses.append((p[0] / 100, p[1] / 100, p[2]))
amostra = random.sample(poses, 80)
print(f"{len(poses)} poses reais (16-17 h); amostra de {len(amostra)}")

cenarios = [("alcance 12 m", 12.0, 0, LOCAL, 80), ("alcance 8 m", 8.0, 0, LOCAL, 80),
            ("8 m + 3 pessoas", 8.0, 3, LOCAL, 80), ("8 m + 6 pessoas", 8.0, 6, LOCAL, 80),
            ("8 m, quase perdido (±1 m/±30°)", 8.0, 0, PERDIDO, 30)]
for nome, alc, pes, etapas, n in cenarios:
    e_xy, e_r, expl = [], [], []
    for (x, y, r) in amostra[:n]:
        rel, d = raycast(x, y, r, alc)
        rel, d = ruido(rel, d, pes, x, y, r)
        amp = 1.0 if etapas is PERDIDO else 0.3
        ar = 30 if etapas is PERDIDO else 8
        x0, y0, r0 = x + random.uniform(-amp, amp), y + random.uniform(-amp, amp), r + random.uniform(-ar, ar)
        s, bx, by, br = buscar(rel, d, x0, y0, r0, etapas)
        e_xy.append(math.hypot(bx - x, by - y) * 100)
        e_r.append(abs(((br - r + 180) % 360) - 180))
        expl.append(len(d))
    e = np.array(e_xy)
    print(f"{nome:32s} n={n:3d} pts/varr {np.median(expl):4.0f} | erro mediana {np.median(e):4.1f} cm, "
          f"p90 {np.percentile(e, 90):5.1f} cm, ≤10 cm {np.mean(e <= 10) * 100:3.0f}% | rumo mediana {np.median(e_r):3.1f}°, p90 {np.percentile(e_r, 90):3.1f}°",
          flush=True)
