"""
scripts/teste_c1_145_real.py — 01/10/2026.
Uso (no PC):
  py scripts/teste_c1_145_real.py <pasta com planta + nav.json> <HH.jsonl> [...]

Pergunta: um C1 a 1,45 m localizaria o robô no mapa do Aurora? Agora com o
LASER REAL do Aurora (campo "a145" do gravador, desde 01/10), não com a planta
fazendo de mundo (scripts/simula_c1_145.py, ~2 cm, otimista por construção).

Gabarito: a pose do PRÓPRIO Aurora gravada com cada volta. Atenção: o Aurora se
localiza com esse mesmo laser (mais câmeras); o teste mede se um localizador
simples, só com o que um C1 entregaria, chega à mesma pose — não mede o erro
do Aurora contra a trena.

Passos:
  1. Braço do laser: onde fica a origem das leituras em relação à pose do
     Aurora (frente, esquerda, giro) e o sentido do ângulo — por busca, com a
     pose do Aurora fixa, maximizando o encaixe das leituras nas paredes.
  2. Cada volta (~2.400 pontos) é "rebaixada" ao que um C1 entrega: 275 pontos,
     alcance 8/10/12 m; numa variante, ruído de 2 cm + 1% e 10% de feixes
     perdidos (o mesmo da simulação).
  3. Localizador = o de 30/09 e da simulação: campo de verossimilhança
     (σ 10 cm) na planta do Aurora, busca em grade a partir da pose do
     gabarito deslocada ±30 cm/±8° (local) ou ±1 m/±30° (quase perdido).
  4. 22 + 145 juntos: só com o robô parado (a varredura do C1 e a volta do
     Aurora não são do mesmo instante), as leituras do C1 de baixo somam-se às
     de cima.
"""
import glob, json, math, random, sys, time
import numpy as np
from PIL import Image

AQUI = sys.argv[1]
ARQS = sys.argv[2:]
random.seed(1); rng = np.random.default_rng(1)

pl = json.load(open(f"{AQUI}/lab_metade_20260925_planta.json"))
img = np.array(Image.open(f"{AQUI}/lab_metade_20260925_planta.png"))
RES, MINX, MAXY = pl["res"], pl["min_x"], pl["max_y"]
H, W = img.shape
parede = img < 100
from scipy import ndimage
DIST = ndimage.distance_transform_edt(~parede) * RES
SIGMA = 0.10
CAMPO = np.exp(-(DIST ** 2) / (2 * SIGMA ** 2))
C1_FRENTE_M = 0.30          # C1 de baixo: 30 cm à frente do centro
C1_SOMBRA = (140, 210)      # graus, sentido horário do C1


def campo(wx, wy):
    """Campo nas coordenadas do mundo, interpolação bilinear; fora = 0."""
    c = (wx - MINX) / RES - 0.5
    l = (MAXY - wy) / RES - 0.5
    c0 = np.floor(c).astype(int); l0 = np.floor(l).astype(int)
    fc = c - c0; fl = l - l0
    ok = (c0 >= 0) & (c0 < W - 1) & (l0 >= 0) & (l0 < H - 1)
    v = np.zeros(np.shape(wx))
    c0, l0, fc, fl = c0[ok], l0[ok], fc[ok], fl[ok]
    v[ok] = (CAMPO[l0, c0] * (1 - fc) * (1 - fl) + CAMPO[l0, c0 + 1] * fc * (1 - fl)
             + CAMPO[l0 + 1, c0] * (1 - fc) * fl + CAMPO[l0 + 1, c0 + 1] * fc * fl)
    return v


# ─── dados ─────────────────────────────────────────────────────────────
voltas, vistos = [], set()
for f in ARQS:
    for linha in open(f, encoding="utf-8"):
        try:
            j = json.loads(linha)
        except ValueError:
            continue
        a = j.get("a145")
        if not a or not a.get("pose") or not a.get("p") or not j.get("pose"):
            continue                       # só depois do "Localizar na fita"
        if a["ts"] in vistos:
            continue                       # a mesma volta pode vir em 2 registros
        vistos.add(a["ts"])
        p = np.array(a["p"], float)
        q = p[:, 2] > 0
        c1 = np.array(j.get("p") or [[0, 0]], float)
        voltas.append({
            "t": j["t"], "ts": a["ts"], "idade_c1": a["idade_s"],
            "pose": a["pose"],             # x, y, z (m), rumo (°) do Aurora
            "ang": p[q, 0] / 100.0, "d": p[q, 1] / 1000.0,
            "c1_pose": j["pose"],          # centro, cm/°, no instante do C1
            "c1_ang": c1[:, 0] / 100.0, "c1_d": c1[:, 1] / 1000.0,
        })
voltas.sort(key=lambda v: v["ts"])
# velocidade pela pose do Aurora entre voltas vizinhas
for i, v in enumerate(voltas):
    o = voltas[i - 1] if i else voltas[min(1, len(voltas) - 1)]
    dt = abs(v["ts"] - o["ts"]) / 1e9 or 1.0
    v["vel"] = math.hypot(v["pose"][0] - o["pose"][0], v["pose"][1] - o["pose"][1]) / dt
    v["giro"] = abs(((v["pose"][3] - o["pose"][3] + 180) % 360) - 180) / dt
print(f"{len(voltas)} voltas do laser do Aurora com pose válida "
      f"({time.strftime('%H:%M', time.localtime(voltas[0]['t']))}–"
      f"{time.strftime('%H:%M', time.localtime(voltas[-1]['t']))}); "
      f"pontos por volta: mediana {np.median([len(v['d']) for v in voltas]):.0f}")
paradas = [v for v in voltas if v["vel"] < 0.01 and v["giro"] < 1]
print(f"  paradas (< 1 cm/s e < 1°/s): {len(paradas)}; andando: {len(voltas) - len(paradas)}")


def no_sensor(ang, d, braco):
    """Leituras no referencial da pose do Aurora (x frente, y esquerda)."""
    ox, oy, oth, sentido = braco
    a = np.radians(sentido * ang + oth)
    return ox + d * np.cos(a), oy + d * np.sin(a)


def nota(sx, sy, x, y, rumo):
    t = math.radians(rumo)
    return campo(x + sx * math.cos(t) - sy * math.sin(t),
                 y + sx * math.sin(t) + sy * math.cos(t)).mean()


# ─── 1. braço do laser ─────────────────────────────────────────────────
amostra_b = random.sample(voltas, min(150, len(voltas)))
sub = []
for v in amostra_b:
    k = np.linspace(0, len(v["d"]) - 1, 400).astype(int)
    sub.append((v["ang"][k], v["d"][k], v["pose"]))


def nota_braco(b):
    s = 0.0
    for ang, d, (x, y, _z, r) in sub:
        sx, sy = no_sensor(ang, d, b)
        s += nota(sx, sy, x, y, r)
    return s / len(sub)


melhor = None
for sentido in (1, -1):
    for oth in np.arange(-6, 6.01, 2.0):
        for ox in np.arange(-0.15, 0.151, 0.05):
            for oy in np.arange(-0.15, 0.151, 0.05):
                s = nota_braco((ox, oy, oth, sentido))
                if melhor is None or s > melhor[0]:
                    melhor = (s, (ox, oy, oth, sentido))
for passo_xy, passo_t, raio_xy, raio_t in ((0.01, 0.5, 0.05, 2.0), (0.005, 0.1, 0.01, 0.5)):
    s0, (cx, cy, ct, sen) = melhor
    for ox in np.arange(cx - raio_xy, cx + raio_xy + 1e-9, passo_xy):
        for oy in np.arange(cy - raio_xy, cy + raio_xy + 1e-9, passo_xy):
            for oth in np.arange(ct - raio_t, ct + raio_t + 1e-9, passo_t):
                s = nota_braco((ox, oy, oth, sen))
                if s > melhor[0]:
                    melhor = (s, (ox, oy, oth, sen))
BRACO = melhor[1]
print(f"\n1. braço do laser: frente {BRACO[0]*100:+.1f} cm, esquerda {BRACO[1]*100:+.1f} cm, "
      f"giro {BRACO[2]:+.1f}°, sentido {'anti-horário' if BRACO[3] > 0 else 'horário'} "
      f"(encaixe médio {melhor[0]:.3f}; sem braço: {nota_braco((0, 0, 0, BRACO[3])):.3f})")


# ─── 2-3. rebaixar e localizar ─────────────────────────────────────────
def rebaixar(v, alcance, ruido, n=275):
    ang, d = v["ang"], v["d"]
    o = np.argsort(ang); ang, d = ang[o], d[o]
    k = np.unique(np.linspace(0, len(d) - 1, n).astype(int))
    ang, d = ang[k], d[k]
    if ruido:
        d = d + rng.normal(0, 0.02 + 0.01 * d)
        ok = rng.random(len(d)) > 0.10
        ang, d = ang[ok], d[ok]
    ok = (d > 0.10) & (d < alcance)
    return ang[ok], d[ok]


def buscar(sx, sy, x0, y0, r0, etapas):
    melhor = (-1.0, x0, y0, r0)
    for passo_xy, passo_r, raio_xy, raio_r in etapas:
        _, cx, cy, cr = melhor
        dxs = np.arange(-raio_xy, raio_xy + 1e-9, passo_xy)
        gx, gy = np.meshgrid(cx + dxs, cy + dxs)
        gx, gy = gx.ravel(), gy.ravel()
        for r in np.arange(cr - raio_r, cr + raio_r + 1e-9, passo_r):
            t = math.radians(r)
            px = sx * math.cos(t) - sy * math.sin(t)
            py = sx * math.sin(t) + sy * math.cos(t)
            s = campo(gx[:, None] + px[None, :], gy[:, None] + py[None, :]).mean(axis=1)
            i = int(np.argmax(s))
            if s[i] > melhor[0]:
                melhor = (float(s[i]), gx[i], gy[i], r)
    return melhor


LOCAL = ((0.05, 2.0, 0.40, 12.0), (0.01, 0.5, 0.06, 2.0), (0.005, 0.25, 0.015, 0.5))
PERDIDO = ((0.10, 4.0, 1.20, 36.0), (0.03, 1.0, 0.15, 5.0), (0.01, 0.5, 0.04, 1.5),
           (0.005, 0.25, 0.015, 0.5))


def gabarito_laser(v):
    """Pose da ORIGEM das leituras no mapa = pose do Aurora ⊕ braço."""
    x, y, _z, r = v["pose"]
    t = math.radians(r)
    return (x + BRACO[0] * math.cos(t) - BRACO[1] * math.sin(t),
            y + BRACO[0] * math.sin(t) + BRACO[1] * math.cos(t), r)


def rodar(nome, voltas_cen, alcance, ruido, etapas, extra_c1=False):
    e_xy, e_r, npts = [], [], []
    amp, ar = (1.0, 30.0) if etapas is PERDIDO else (0.30, 8.0)
    for v in voltas_cen:
        if alcance is None:
            ang, d = v["ang"], v["d"]
        else:
            ang, d = rebaixar(v, alcance, ruido)
        # leituras no referencial da ORIGEM do laser (braço já aplicado no gabarito)
        sx, sy = no_sensor(ang, d, (0, 0, BRACO[2], BRACO[3]))
        if extra_c1:
            sx, sy = juntar_c1(v, sx, sy)
        gx, gy, gr = gabarito_laser(v)
        x0, y0 = gx + random.uniform(-amp, amp), gy + random.uniform(-amp, amp)
        r0 = gr + random.uniform(-ar, ar)
        _s, bx, by, br = buscar(sx, sy, x0, y0, r0, etapas)
        e_xy.append(math.hypot(bx - gx, by - gy) * 100)
        e_r.append(abs(((br - gr + 180) % 360) - 180))
        npts.append(len(sx))
    e = np.array(e_xy); er = np.array(e_r)
    linha = (f"{nome:44s} n={len(e):3d} pts {np.median(npts):5.0f} | mediana {np.median(e):4.1f} cm, "
             f"p90 {np.percentile(e, 90):5.1f} cm, máx {e.max():5.1f}, ≤10 cm {np.mean(e <= 10) * 100:3.0f}% "
             f"| rumo med {np.median(er):3.1f}°, p90 {np.percentile(er, 90):3.1f}°")
    print(linha, flush=True)
    return {"nome": nome, "n": len(e), "pts": float(np.median(npts)),
            "mediana_cm": round(float(np.median(e)), 1), "p90_cm": round(float(np.percentile(e, 90)), 1),
            "max_cm": round(float(e.max()), 1), "ate10_pct": round(float(np.mean(e <= 10) * 100)),
            "rumo_med": round(float(np.median(er)), 1), "rumo_p90": round(float(np.percentile(er, 90)), 1)}


def juntar_c1(v, sx, sy):
    """Soma as leituras do C1 de baixo (robô parado), no referencial da origem do laser."""
    cx_cm, cy_cm, cr, _idade = v["c1_pose"]
    ang, d = v["c1_ang"], v["c1_d"]
    ok = (d > 0.15) & (d < 12.0) & ~((ang > C1_SOMBRA[0]) & (ang < C1_SOMBRA[1]))
    ang, d = ang[ok], d[ok]
    k = np.unique(np.linspace(0, len(d) - 1, min(275, len(d))).astype(int)) if len(d) else []
    ang, d = ang[k], d[k]
    a = np.radians(-ang)                               # C1: sentido horário
    px, py = C1_FRENTE_M + d * np.cos(a), d * np.sin(a)  # no centro do robô
    t = math.radians(cr)
    wx = cx_cm / 100 + px * math.cos(t) - py * math.sin(t)
    wy = cy_cm / 100 + px * math.sin(t) + py * math.cos(t)
    gx, gy, gr = gabarito_laser(v)                     # mundo → origem do laser
    tg = math.radians(gr)
    dx, dy = wx - gx, wy - gy
    lx = dx * math.cos(tg) + dy * math.sin(tg)
    ly = -dx * math.sin(tg) + dy * math.cos(tg)
    return np.concatenate([sx, lx]), np.concatenate([sy, ly])


print("\n2-3. localização (erro da origem do laser contra o gabarito):")
N = 200
am = random.sample(voltas, min(N, len(voltas)))
am_and = [v for v in am if v["vel"] >= 0.03 or v["giro"] >= 5]
res = []
res.append(rodar("volta inteira do Aurora (referência)", am, None, False, LOCAL))
for alc in (12.0, 10.0, 8.0):
    res.append(rodar(f"C1: 275 pts, {alc:.0f} m", am, alc, False, LOCAL))
res.append(rodar("C1: 275 pts, 8 m, ruído do C1", am, 8.0, True, LOCAL))
res.append(rodar("  só andando (≥3 cm/s ou ≥5°/s)", am_and, 8.0, True, LOCAL))
res.append(rodar("C1: 8 m, ruído, quase perdido (±1 m/±30°)", am[:60], 8.0, True, PERDIDO))
pr = random.sample(paradas, min(120, len(paradas)))
res.append(rodar("parado: só 1,45 m (8 m, ruído)", pr, 8.0, True, LOCAL))
res.append(rodar("parado: 22 cm + 1,45 m (8 m, ruído)", pr, 8.0, True, LOCAL, extra_c1=True))

json.dump({"braco": BRACO, "voltas": len(voltas), "paradas": len(paradas), "res": res},
          open(f"{AQUI}/resultado_c1_145_real.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
print(f"\nGravado: {AQUI}/resultado_c1_145_real.json")
