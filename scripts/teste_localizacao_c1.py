"""
Teste de localização pelo C1 a 22 cm, fora do robô (30/09/2026).
Uso (no PC): copie para uma pasta as horas do gravador (HH.jsonl), a planta
(*_planta.png/json) e o nav.json, e rode: python scripts/teste_localizacao_c1.py <pasta>
Resultado de 30/09: mapa gravado pelo próprio C1 → ~5 cm (ver SESSAO_2026-09-30).

Pergunta: com o que o C1 vê a 22 cm, o robô acharia a própria posição comparando
a varredura com um MAPA? Gabarito: a pose do Aurora (centro do robô) gravada
junto de cada varredura.

Mapas comparados:
  P  = só paredes (planta do laser do Aurora, a 1,45 m)
  PA = paredes + ÁREAS PROIBIDAS preenchidas (a ideia do professor: leitura
       que termina dentro de uma área ou numa parede está "explicada")

Método: para cada varredura, parte da pose do Aurora deslocada de propósito
(até ±30 cm e ±8°) e procura, numa busca em grade, a pose em que as leituras
mais caem sobre parede/área (campo de verossimilhança, σ = 10 cm). O erro entre
a pose achada e a do Aurora diz a precisão que o C1 daria.
"""
import glob, json, math, random, sys
import numpy as np
from PIL import Image, ImageDraw
from scipy import ndimage

AQUI = sys.argv[1] if len(sys.argv) > 1 else "."
C1_FRENTE_M = 0.30                 # C1 na borda frontal, 30 cm à frente do centro
SIGMA = 0.10
random.seed(30)

pl = json.load(open(f"{AQUI}/lab_metade_20260925_planta.json"))
img = np.array(Image.open(f"{AQUI}/lab_metade_20260925_planta.png"))
RES, MINX, MAXY = pl["res"], pl["min_x"], pl["max_y"]
H, W = img.shape
parede = img < 100
nav = json.load(open(f"{AQUI}/nav.json"))

areas_img = Image.new("L", (W, H), 0)
dr = ImageDraw.Draw(areas_img)
for a in nav["areas"]:
    dr.polygon([((x - MINX) / RES, (MAXY - y) / RES) for x, y in a["pontos"]], fill=1)
areas = np.array(areas_img).astype(bool)


def campo(ocup):
    d = ndimage.distance_transform_edt(~ocup) * RES
    return np.exp(-(d ** 2) / (2 * SIGMA ** 2)), d


borda = areas & ~ndimage.binary_erosion(areas, iterations=2)       # faixa de 10 cm na borda
CAMPOS = {"P": campo(parede), "PA": campo(parede | areas), "PAb": campo(parede | borda)}


def carregar():
    out = []
    for f in sorted(glob.glob(f"{AQUI}/1[2-7].jsonl")):
        for l in open(f):
            try:
                d = json.loads(l)
            except ValueError:
                continue
            p = d.get("pose")
            if not p or not d.get("p"):
                continue
            ang = np.array([q[0] for q in d["p"]], float) / 100.0
            dist = np.array([q[1] for q in d["p"]], float) / 1000.0
            ok = (dist > 0.15) & (dist < 12.0) & ~((ang > 140) & (ang < 210))
            out.append((d["t"], p[0] / 100, p[1] / 100, p[2], ang[ok], dist[ok]))
    return out


def pontos(ang, dist, x, y, rumo, sentido):
    a = np.radians(sentido * ang)            # robô: x frente, y esquerda
    px = C1_FRENTE_M + dist * np.cos(a)
    py = dist * np.sin(a)
    t = math.radians(rumo)
    return (x + px * math.cos(t) - py * math.sin(t),
            y + px * math.sin(t) + py * math.cos(t))


def nota(mapa, wx, wy):
    f = CAMPOS[mapa][0]
    col = ((wx - MINX) / RES).astype(int)
    lin = ((MAXY - wy) / RES).astype(int)
    ok = (col >= 0) & (col < W) & (lin >= 0) & (lin < H)
    v = np.zeros(len(wx))
    v[ok] = f[lin[ok], col[ok]]
    return v.mean()


def explicadas(mapa, wx, wy, lim=0.15):
    d = CAMPOS[mapa][1]
    col = np.clip(((wx - MINX) / RES).astype(int), 0, W - 1)
    lin = np.clip(((MAXY - wy) / RES).astype(int), 0, H - 1)
    return float((d[lin, col] <= lim).mean())


dados = carregar()
# Mapa gravado pelo PRÓPRIO C1 (com a pose do Aurora): monta com as horas 12–14 e
# testa nas 16–17 (outras horas: cadeiras e caixas podem ter mudado).
def _mapa_c1(regs):
    cont = np.zeros((H, W), int)
    for t, x, y, r, ang, dist in regs:
        wx, wy = pontos(ang, dist, x, y, r, -1)
        col = ((wx - MINX) / RES).astype(int); lin = ((MAXY - wy) / RES).astype(int)
        ok = (col >= 0) & (col < W) & (lin >= 0) & (lin < H)
        np.add.at(cont, (lin[ok], col[ok]), 1)
    return cont >= 5
import time as _t
_h = lambda t: int(_t.strftime("%H", _t.localtime(t)))
treino = [r for r in dados if 12 <= _h(r[0]) <= 14]
dados = [r for r in dados if _h(r[0]) >= 16]
CAMPOS["C1"] = campo(_mapa_c1(treino))
print(f"mapa do C1 montado com {len(treino)} varreduras (12–14 h); teste com {len(dados)} (16–17 h)")
# parado = pose quase igual à anterior e à seguinte (1 leitura por segundo)
parado = []
for i, r in enumerate(dados):
    viz = [dados[j] for j in (i - 1, i + 1) if 0 <= j < len(dados)]
    parado.append(all(math.hypot(r[1] - v[1], r[2] - v[2]) < 0.01 and abs(r[3] - v[3]) < 0.5
                      and abs(r[0] - v[0]) < 1.6 for v in viz))
print(f"{len(dados)} varreduras com pose; {sum(parado)} com o robô parado")

# 1) Convenção do ângulo do C1 (horário ou anti-horário): a certa explica mais.
amostra = random.sample(range(len(dados)), 200)
for s in (-1, +1):
    e = np.mean([explicadas("PA", *pontos(dados[i][4], dados[i][5], *dados[i][1:4], s)) for i in amostra])
    print(f"sentido {s:+d}: {e * 100:.0f}% das leituras caem a ≤15 cm de parede/área")
SENT = max((-1, +1), key=lambda s: np.mean([nota("PA", *pontos(dados[i][4], dados[i][5], *dados[i][1:4], s)) for i in amostra]))
print(f"→ sentido do C1 adotado: {SENT:+d}")

for m in ("P", "PA"):
    e = [explicadas(m, *pontos(r[4], r[5], *r[1:4], SENT)) for r in dados[::5]]
    print(f"mapa {m:2s}: leituras explicadas (≤15 cm) mediana {np.median(e) * 100:.0f}%, "
          f"p10 {np.percentile(e, 10) * 100:.0f}%")


def buscar(mapa, ang, dist, x0, y0, r0):
    melhor = (-1, x0, y0, r0)
    for passo_xy, passo_r, raio_xy, raio_r in ((0.05, 2.0, 0.40, 12.0), (0.01, 0.5, 0.06, 2.0)):
        cx, cy, cr = melhor[1:] if melhor[0] >= 0 else (x0, y0, r0)
        for dx in np.arange(-raio_xy, raio_xy + 1e-9, passo_xy):
            for dy in np.arange(-raio_xy, raio_xy + 1e-9, passo_xy):
                for drr in np.arange(-raio_r, raio_r + 1e-9, passo_r):
                    s = nota(mapa, *pontos(ang, dist, cx + dx, cy + dy, cr + drr, SENT))
                    if s > melhor[0]:
                        melhor = (s, cx + dx, cy + dy, cr + drr)
    return melhor


# 2) Precisão: parte de um chute errado (±30 cm, ±8°) e vê aonde a busca chega.
idx_p = [i for i, p in enumerate(parado) if p]
idx_m = [i for i, p in enumerate(parado) if not p]
sel = random.sample(idx_p, min(60, len(idx_p))) + random.sample(idx_m, min(60, len(idx_m)))
res = {m: {"parado": [], "andando": []} for m in CAMPOS}
for n, i in enumerate(sel):
    t, x, y, r, ang, dist = dados[i]
    x0, y0, r0 = x + random.uniform(-.3, .3), y + random.uniform(-.3, .3), r + random.uniform(-8, 8)
    for m in CAMPOS:
        s, bx, by, br = buscar(m, ang, dist, x0, y0, r0)
        err = math.hypot(bx - x, by - y)
        res[m]["parado" if parado[i] else "andando"].append((err, abs(((br - r + 180) % 360) - 180)))
    if n % 20 == 0:
        print(f"  {n}/{len(sel)}", flush=True)

for m in CAMPOS:
    for k in ("parado", "andando"):
        v = res[m][k]
        if not v:
            continue
        e = np.array([a for a, _ in v]) * 100
        g = np.array([b for _, b in v])
        print(f"mapa {m:2s} {k:8s} n={len(v):3d}: erro de posição mediana {np.median(e):4.1f} cm, "
              f"p90 {np.percentile(e, 90):4.1f} cm, ≤10 cm {np.mean(e <= 10) * 100:3.0f}%, "
              f"≤20 cm {np.mean(e <= 20) * 100:3.0f}% | rumo mediana {np.median(g):3.1f}°")
