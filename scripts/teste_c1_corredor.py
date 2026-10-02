"""
scripts/teste_c1_corredor.py — 02/10/2026.
Uso (no PC):
  py scripts/teste_c1_corredor.py data/varreduras/2026-10-01/19.jsonl [--corte HH:MM:SS]

Pergunta: no CORREDOR (~20 × 2 m, paredes paralelas), um robô sem Aurora se
localiza com os dois C1 do contrato da V1 (22 cm + 1,45 m, docs/PRD.md §0)?
É o caso difícil: as paredes laterais fixam bem a posição ATRAVÉS do corredor,
mas ao LONGO dele só as portas, os cantos e o fundo dizem onde o robô está.

Dados: as voltas gravadas em 01/10 (19:13–19:44) durante o mapeamento do
corredor. Ali o serviço rodou SEM "Localizar na fita", então "pose" vem null;
o gabarito é a pose do PRÓPRIO Aurora gravada com cada volta do laser (a145).

Método (o mesmo de scripts/teste_c1_145_real.py, mas com o mapa montado pelo
próprio robô, que é o caminho decidido — e não a planta exportada):
  1. Divide as voltas no tempo: as primeiras montam os mapas, as outras testam.
  2. Mapa de cima: leituras do laser do Aurora (a 1,45 m) na grade de 2 cm.
     Mapa de baixo: leituras do C1 a 22 cm, com a pose do centro interpolada
     entre as voltas do Aurora (só onde a interpolação é confiável).
  3. Cada volta de teste é rebaixada ao que um C1 entrega (275 pontos,
     12 m ou 8 m + ruído) e localizada por campo de verossimilhança a partir
     do gabarito deslocado (±30 cm/±8°, ou ±1 m/±30° "quase perdido").
  4. Erro do CENTRO do robô, separado em AO LONGO e ATRAVÉS do corredor.

Não cobre: C1 real a 1,45 m (vidro, peito das pessoas), gabarito = o próprio
Aurora, uma sessão só, localizador sem odometria (cada volta sozinha).
"""
import json, math, random, sys, time
import numpy as np
from scipy import ndimage

ARQ = sys.argv[1]
CORTE = None
if "--corte" in sys.argv:
    CORTE = sys.argv[sys.argv.index("--corte") + 1]
random.seed(1); rng = np.random.default_rng(1)

RES = 0.02
SIGMA = 0.10
# Montagens em relação ao CENTRO de giro (frente, esquerda, giro°, sentido).
#   Aurora: ponto da pose = centro + (−5,3; +7,2) cm (AURORA_BRACO_M, 30/09).
#   Laser do Aurora: origem 2,5 cm à frente e 3,0 cm à direita da pose do
#   Aurora, giro −0,4°, anti-horário (teste_c1_145_real.py, 01/10).
#   C1 de baixo: 30 cm à frente do centro, ângulo horário, sombra 140–210°.
AURORA_BRACO = (-0.053, 0.072)
LASER = (AURORA_BRACO[0] + 0.025, AURORA_BRACO[1] - 0.030, -0.4, 1)
C1 = (0.30, 0.0, 0.0, -1)
C1_SOMBRA = (140, 210)


def hm(t):
    return time.strftime("%H:%M:%S", time.localtime(t))


def gira(x, y, r):
    t = math.radians(r)
    return x * math.cos(t) - y * math.sin(t), x * math.sin(t) + y * math.cos(t)


# ─── dados ─────────────────────────────────────────────────────────────
regs, vistos = [], set()
for linha in open(ARQ, encoding="utf-8"):
    try:
        j = json.loads(linha)
    except ValueError:
        continue
    a = j.get("a145")
    if not a or not a.get("pose") or not a.get("p"):
        continue
    p = np.array(a["p"], float)
    q = p[:, 2] > 0
    c1 = np.array(j.get("p") or [[0, 0]], float)
    x, y, _z, r = a["pose"]
    bx, by = gira(*AURORA_BRACO, r)
    reg = {"t": j["t"], "t_laser": j["t"] - a["idade_s"], "ts": a["ts"],
           "centro": (x - bx, y - by, r),          # pose do centro no instante do laser
           "ang": p[q, 0] / 100.0, "d": p[q, 1] / 1000.0,
           "c1_ang": c1[:, 0] / 100.0, "c1_d": c1[:, 1] / 1000.0,
           "novo": a["ts"] not in vistos}
    vistos.add(a["ts"])
    regs.append(reg)
regs.sort(key=lambda v: v["t"])
voltas = [v for v in regs if v["novo"]]          # a mesma volta pode vir em 2 registros
print(f"{len(voltas)} voltas do laser do Aurora ({hm(voltas[0]['t'])}–{hm(voltas[-1]['t'])}); "
      f"{len(regs)} varreduras do C1 de baixo")

# Pose do centro no instante de cada varredura do C1: interpolada entre as
# voltas vizinhas — só se forem próximas no tempo e o robô andou pouco.
tl = np.array([v["t_laser"] for v in voltas])
for g in regs:
    i = int(np.searchsorted(tl, g["t"]))
    g["c1_centro"] = None
    if i == 0 or i >= len(voltas):
        continue
    a, b = voltas[i - 1], voltas[i]
    dt = b["t_laser"] - a["t_laser"]
    if dt <= 0 or dt > 1.6:
        continue
    (ax, ay, ar), (bx, by, br) = a["centro"], b["centro"]
    dr = ((br - ar + 180) % 360) - 180
    if math.hypot(bx - ax, by - ay) > 0.15 or abs(dr) > 5:
        continue
    f = (g["t"] - a["t_laser"]) / dt
    g["c1_centro"] = (ax + f * (bx - ax), ay + f * (by - ay), ar + f * dr)

# Eixo do corredor: direção principal das posições do centro.
P = np.array([v["centro"][:2] for v in voltas])
_, _, vt = np.linalg.svd(P - P.mean(axis=0))
EIXO = vt[0]
ao_longo = (P - P.mean(axis=0)) @ EIXO
print(f"corredor percorrido: {ao_longo.max() - ao_longo.min():.1f} m ao longo do eixo")

# ─── divisão: mapa × teste ─────────────────────────────────────────────
if CORTE:
    hh, mm, ss = (int(x) for x in CORTE.split(":"))
    lt = time.localtime(voltas[0]["t"])
    t_corte = time.mktime((lt.tm_year, lt.tm_mon, lt.tm_mday, hh, mm, ss, 0, 0, -1))
else:
    t_corte = voltas[len(voltas) // 2]["t"]
v_mapa = [v for v in voltas if v["t"] < t_corte]
v_teste = [v for v in voltas if v["t"] >= t_corte]
g_mapa = [g for g in regs if g["t"] < t_corte and g["c1_centro"]]
print(f"mapa: {len(v_mapa)} voltas até {hm(t_corte)} · teste: {len(v_teste)} voltas depois")


def no_sensor(ang, d, montagem):
    """Leituras no referencial do CENTRO (x frente, y esquerda)."""
    ox, oy, oth, sentido = montagem
    a = np.radians(sentido * ang + oth)
    return ox + d * np.cos(a), oy + d * np.sin(a)


def c1_pontos(ang, d):
    ok = (d > 0.15) & (d < 12.0) & ~((ang > C1_SOMBRA[0]) & (ang < C1_SOMBRA[1]))
    return no_sensor(ang[ok], d[ok], C1)


# ─── mapas (grade de 2 cm; parede = célula vista em ≥ 3 voltas) ─────────
def montar(lista):
    """lista de (sx, sy, pose do centro) → campo de verossimilhança."""
    xs, ys = [], []
    for sx, sy, (x, y, r) in lista:
        px, py = gira(sx, sy, r)
        xs.append(x + px); ys.append(y + py)
    xs, ys = np.concatenate(xs), np.concatenate(ys)
    minx, maxy = xs.min() - 1.0, ys.max() + 1.0
    W = int((xs.max() + 1.0 - minx) / RES) + 1
    H = int((maxy - (ys.min() - 1.0)) / RES) + 1
    cont = np.zeros((H, W), np.int32)
    for sx, sy, (x, y, r) in lista:                 # conta voltas, não pontos
        px, py = gira(sx, sy, r)
        c = ((x + px - minx) / RES).astype(int); l = ((maxy - (y + py)) / RES).astype(int)
        m = np.zeros((H, W), bool); m[l, c] = True
        cont += m
    parede = cont >= 3
    dist = ndimage.distance_transform_edt(~parede) * RES
    return {"campo": np.exp(-dist ** 2 / (2 * SIGMA ** 2)), "minx": minx, "maxy": maxy,
            "H": H, "W": W, "celulas": int(parede.sum())}


def campo(M, wx, wy):
    c = (wx - M["minx"]) / RES - 0.5
    l = (M["maxy"] - wy) / RES - 0.5
    c0 = np.floor(c).astype(int); l0 = np.floor(l).astype(int)
    fc = c - c0; fl = l - l0
    ok = (c0 >= 0) & (c0 < M["W"] - 1) & (l0 >= 0) & (l0 < M["H"] - 1)
    v = np.zeros(np.shape(wx))
    c0, l0, fc, fl = c0[ok], l0[ok], fc[ok], fl[ok]
    C = M["campo"]
    v[ok] = (C[l0, c0] * (1 - fc) * (1 - fl) + C[l0, c0 + 1] * fc * (1 - fl)
             + C[l0 + 1, c0] * (1 - fc) * fl + C[l0 + 1, c0 + 1] * fc * fl)
    return v


t0 = time.time()
CIMA = montar([(*no_sensor(v["ang"], v["d"], LASER), v["centro"]) for v in v_mapa])
BAIXO = montar([(*c1_pontos(g["c1_ang"], g["c1_d"]), g["c1_centro"]) for g in g_mapa])
print(f"mapas montados em {time.time() - t0:.0f} s: 1,45 m {CIMA['celulas']} células de parede; "
      f"22 cm {BAIXO['celulas']} (de {len(g_mapa)} varreduras com pose confiável)")


# ─── localizar ─────────────────────────────────────────────────────────
def rebaixar(ang, d, alcance, ruido, n=275):
    o = np.argsort(ang); ang, d = ang[o], d[o]
    k = np.unique(np.linspace(0, len(d) - 1, n).astype(int))
    ang, d = ang[k], d[k]
    if ruido:
        d = d + rng.normal(0, 0.02 + 0.01 * d)
        ok = rng.random(len(d)) > 0.10
        ang, d = ang[ok], d[ok]
    ok = (d > 0.10) & (d < alcance)
    return ang[ok], d[ok]


def buscar(grupos, x0, y0, r0, etapas):
    """grupos = [(sx, sy, mapa)] no referencial do centro; nota = média de todos os pontos."""
    total = sum(len(g[0]) for g in grupos)
    melhor = (-1.0, x0, y0, r0)
    for passo_xy, passo_r, raio_xy, raio_r in etapas:
        _, cx, cy, cr = melhor
        dxs = np.arange(-raio_xy, raio_xy + 1e-9, passo_xy)
        gx, gy = np.meshgrid(cx + dxs, cy + dxs)
        gx, gy = gx.ravel(), gy.ravel()
        for r in np.arange(cr - raio_r, cr + raio_r + 1e-9, passo_r):
            s = np.zeros(len(gx))
            for sx, sy, M in grupos:
                px, py = gira(sx, sy, r)
                s += campo(M, gx[:, None] + px[None, :], gy[:, None] + py[None, :]).sum(axis=1)
            s /= total
            i = int(np.argmax(s))
            if s[i] > melhor[0]:
                melhor = (float(s[i]), gx[i], gy[i], r)
    return melhor


LOCAL = ((0.05, 2.0, 0.40, 12.0), (0.01, 0.5, 0.06, 2.0), (0.005, 0.25, 0.015, 0.5))
PERDIDO = ((0.10, 4.0, 1.20, 36.0), (0.03, 1.0, 0.15, 5.0), (0.01, 0.5, 0.04, 1.5),
           (0.005, 0.25, 0.015, 0.5))

# Para o teste com o C1 de baixo: o registro da volta de teste que traz a
# varredura do C1 com pose confiável (a mesma volta pode vir em 2 registros).
c1_da_volta = {}
for g in regs:
    if g["c1_centro"]:
        c1_da_volta.setdefault(g["ts"], g)


def rodar(nome, lista, cima, baixo, etapas, trechos=False):
    """cima = (alcance, ruído) ou None; baixo = usar o C1 de 22 cm."""
    eL, eT, eR, npts, pos = [], [], [], [], []
    amp, ar = (1.0, 30.0) if etapas is PERDIDO else (0.30, 8.0)
    for v in lista:
        gx, gy, gr = v["centro"]
        grupos = []
        if cima:
            if cima == "inteira":
                ang, d = v["ang"], v["d"]
            else:
                ang, d = rebaixar(v["ang"], v["d"], *cima)
            sx, sy = no_sensor(ang, d, LASER)
            grupos.append((sx, sy, CIMA))
        if baixo:
            g = c1_da_volta.get(v["ts"])
            if g is None:
                continue
            ang, d = rebaixar(g["c1_ang"], g["c1_d"], 12.0, False)
            sx, sy = c1_pontos(ang, d)
            # Leva as leituras do instante do C1 para o instante do laser pelo
            # movimento do gabarito (no robô real: odometria/BNO; aqui < 15 cm).
            cx, cy, cr = g["c1_centro"]
            px, py = gira(sx, sy, cr)
            wx, wy = cx + px - gx, cy + py - gy
            lx, ly = gira(wx, wy, -gr)
            grupos.append((lx, ly, BAIXO))
        x0, y0 = gx + random.uniform(-amp, amp), gy + random.uniform(-amp, amp)
        r0 = gr + random.uniform(-ar, ar)
        _s, bx, by, br = buscar(grupos, x0, y0, r0, etapas)
        e = np.array([bx - gx, by - gy])
        eL.append(abs(e @ EIXO) * 100)
        eT.append(abs(e @ np.array([-EIXO[1], EIXO[0]])) * 100)
        eR.append(abs(((br - gr + 180) % 360) - 180))
        npts.append(sum(len(gp[0]) for gp in grupos))
        pos.append((np.array([gx, gy]) - P.mean(axis=0)) @ EIXO)
    eL, eT, eR = np.array(eL), np.array(eT), np.array(eR)
    eXY = np.hypot(eL, eT)
    res = {"nome": nome, "n": len(eXY), "pts": float(np.median(npts)),
           "mediana_cm": round(float(np.median(eXY)), 1), "p90_cm": round(float(np.percentile(eXY, 90)), 1),
           "max_cm": round(float(eXY.max()), 1),
           "longo_med": round(float(np.median(eL)), 1), "longo_p90": round(float(np.percentile(eL, 90)), 1),
           "trav_med": round(float(np.median(eT)), 1), "trav_p90": round(float(np.percentile(eT, 90)), 1),
           "acima_30cm": int((eXY > 30).sum()),
           "rumo_med": round(float(np.median(eR)), 1), "rumo_p90": round(float(np.percentile(eR, 90)), 1)}
    print(f"{nome:40s} n={res['n']:3d} pts {res['pts']:4.0f} | total med {res['mediana_cm']:4.1f} "
          f"p90 {res['p90_cm']:5.1f} máx {res['max_cm']:5.1f} | ao longo med {res['longo_med']:4.1f} "
          f"p90 {res['longo_p90']:5.1f} | através med {res['trav_med']:4.1f} p90 {res['trav_p90']:4.1f} "
          f"| >30 cm {res['acima_30cm']} | rumo {res['rumo_med']:.1f}°/{res['rumo_p90']:.1f}°", flush=True)
    if trechos:                                    # onde o erro mora, ao longo do corredor
        pos = np.array(pos)
        for a in np.arange(np.floor(pos.min() / 4) * 4, pos.max(), 4.0):
            k = (pos >= a) & (pos < a + 4)
            if k.sum() >= 5:
                print(f"    trecho {a:+5.0f} a {a + 4:+3.0f} m: n={k.sum():3d} | ao longo med {np.median(eL[k]):4.1f} "
                      f"p90 {np.percentile(eL[k], 90):5.1f} | através med {np.median(eT[k]):4.1f} "
                      f"p90 {np.percentile(eT[k], 90):5.1f}")
    return res


N = 200
am = random.sample(v_teste, min(N, len(v_teste)))
am_c1 = [v for v in am if v["ts"] in c1_da_volta]
print(f"\nlocalização do CENTRO nas voltas de teste ({len(am)}; {len(am_c1)} com C1 de baixo confiável):")
res = [
    rodar("volta inteira do Aurora (referência)", am, "inteira", False, LOCAL, trechos=True),
    rodar("1,45 m: 275 pts, 12 m", am, (12.0, False), False, LOCAL),
    rodar("1,45 m: 275 pts, 8 m, ruído", am, (8.0, True), False, LOCAL),
    rodar("1,45 m: 8 m, ruído, quase perdido", am[:60], (8.0, True), False, PERDIDO),
    # mesmas voltas do C1 de baixo (robô devagar): comparação justa
    rodar("volta inteira, voltas com C1", am_c1, "inteira", False, LOCAL),
    rodar("1,45 m (8 m, ruído), voltas com C1", am_c1, (8.0, True), False, LOCAL),
    rodar("22 cm sozinho", am_c1, None, True, LOCAL),
    rodar("1,45 m (8 m, ruído) com o C1 de 22 cm", am_c1, (8.0, True), True, LOCAL),
    rodar("os dois, quase perdido", am_c1[:60], (8.0, True), True, PERDIDO),
]
saida = ARQ.rsplit("/", 1)[0] + "/resultado_c1_corredor.json"
json.dump({"arquivo": ARQ, "corte": hm(t_corte), "mapa": len(v_mapa), "teste": len(v_teste),
           "eixo": EIXO.tolist(), "res": res},
          open(saida, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
print(f"\nGravado: {saida}")
