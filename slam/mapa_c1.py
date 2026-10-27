"""
slam/mapa_c1.py
OS MAPAS DOS C1 — o mapa de referência com que os robôs SEM Aurora se
localizam, montado com a coleta do robô 1 (pacote de ambiente, Etapa B.2,
02/10/2026; contrato da V1, docs/PRD.md §0 item 2: os dois C1, 22 cm e 1,45 m).

DE ONDE VEM: as varreduras das passadas de coleta (coleta/passada_N.jsonl,
copiadas do gravador de sempre por slam/mapeamento.py), gravadas com o robô 1
JÁ LOCALIZADO no mapa salvo — a grade que o Aurora exporta não serve (bancada
de 02/10: ~9 cm contra ~5 cm deste método).

  1,43 m — o C1 DE CIMA do robô 1 ("c143", desde 22/10/2026, decisão N1): o
           mesmo sensor, na mesma altura, que os robôs sem Aurora levam.
  22 cm  — o C1 de baixo do robô 1 ("p").
  Os dois com a pose do CENTRO no instante, e só se ela tinha até
  MAPA_C1_POSE_MAX_IDADE_S (N4: andando, o Aurora às vezes atrasa a pose).
  1,45 m — (legado, 01/10) a volta do LASER DO AURORA ("a145"). O laser está
           desligado desde 01/10; o mapa c1_145 só sai de coletas antigas.

COMO: grade de 2 cm; uma célula é PAREDE se foi vista em pelo menos 3 voltas
(contam-se voltas, não pontos) — quem passou uma vez não vira parede. Método
medido em 30/09 (sala, 22 cm, ~5 cm), 01/10 (sala, 1,45 m, ~5 cm) e 02/10
(corredor, 1,45 m ~6,6 cm; os dois juntos ~2,4 cm): scripts/teste_c1_*.py.

A NOTA: monta o mapa SEM a última passada e passa por ela ACOMPANHANDO volta
a volta, como o robô sem Aurora faz (23/10, P2): só 22 cm e os dois juntos,
com as perdas. A nota "a frio" fica ao lado, como informação: localiza uma
amostra das voltas a partir da pose certa deslocada ±30 cm/±8° (só 22 cm, só
1,43 m e os dois). Voltas reais dos C1, sem rebaixar (já são o que um C1
entrega). O erro típico (mediana e p90, em cm) é a nota. Gabarito = a pose do Aurora: a
nota diz o quanto os C1 CONCORDAM com o Aurora, não o erro contra a trena.
(Coleta antiga, só com o laser: a nota de 01/10, laser rebaixado a C1.)

Saída no pacote: c1_143.png/.json e c1_22.png/.json (PNG: 0 = parede,
255 = resto; o .json traz origem, escala e o sha do mapa do Aurora).
A PLANTA sai do laser do Aurora quando ele coincide com o C1 de 1,43 m;
senão, do C1 de 1,43 m (23/10, P1b).
Nada aqui move o robô.
"""

import glob
import json
import math
import os
import random
import time

import numpy as np

from config.settings import (C1_GIRO_DEG, C1_TOPO_X_M, C1_TOPO_Y_M, C1_TOPO_GIRO_DEG,
                             C1_TOPO_SOMBRA_DEG, MAPA_C1_POSE_MAX_IDADE_S)

RES         = 0.02
MIN_VOLTAS   = 3
SIGMA        = 0.10
# Montagens em relação ao CENTRO do robô 1 (frente, esquerda, giro°, sentido).
# Laser do Aurora: a origem fica 2,5 cm à frente e 3,0 cm à direita do PONTO
# do Aurora, giro −0,4°, anti-horário (teste de 01/10); o ponto do Aurora fica
# (−5,3; +7,2) cm do centro (AURORA_BRACO_M, 30/09). Aqui a pose da volta é a
# do próprio Aurora, então usa-se o braço do LASER em relação ao PONTO.
LASER_NO_PONTO = (0.025, -0.030, -0.4, 1)
C1_NO_CENTRO   = (0.30, 0.0, C1_GIRO_DEG, -1)   # C1: 30 cm à frente, ângulo horário
C1_SOMBRA      = (150.0, 222.0)            # a coluna atrás do C1 (base nova, 20/10: 160–217°)
C1_TOPO_NO_CENTRO = (C1_TOPO_X_M, C1_TOPO_Y_M, C1_TOPO_GIRO_DEG, -1)   # C1 de cima, horário


def _gira(x, y, r_deg):
    t = math.radians(r_deg)
    c, s = math.cos(t), math.sin(t)
    return x * c - y * s, x * s + y * c


def no_sensor(ang_deg, d_m, montagem):
    """Leituras no referencial de quem carrega o sensor (x frente, y esquerda)."""
    ox, oy, oth, sentido = montagem
    a = np.radians(sentido * ang_deg + oth)
    return ox + d_m * np.cos(a), oy + d_m * np.sin(a)


# ─────────────────────────────────────────────
# LEITURA DA COLETA
# ─────────────────────────────────────────────
def ler_coleta(pasta_coleta):
    """{passada: [registro]} com o que interessa de cada linha do gravador."""
    out = {}
    for arq in sorted(glob.glob(os.path.join(pasta_coleta, "passada_*.jsonl"))):
        n = int(os.path.basename(arq)[len("passada_"):-len(".jsonl")])
        regs, vistos = [], set()
        for linha in open(arq, encoding="utf-8"):
            try:
                j = json.loads(linha)
            except ValueError:
                continue
            r = {"t": j.get("t"), "yaw": j.get("yaw")}
            # As voltas cruas vão sempre (a nota acompanhando passa por todas);
            # com a pose do centro, só se ela estava fresca (N4).
            if j.get("p"):
                c1 = np.array(j["p"], float)
                r["c1_volta"] = (c1[:, 0] / 100.0, c1[:, 1] / 1000.0)
            topo = j.get("c143")
            if isinstance(topo, dict) and topo.get("p"):
                c2 = np.array(topo["p"], float)
                r["c143_volta"] = (c2[:, 0] / 100.0, c2[:, 1] / 1000.0)
            pose = j.get("pose")
            fresca = bool(pose) and (len(pose) < 4 or pose[3] is None
                                     or pose[3] <= MAPA_C1_POSE_MAX_IDADE_S)
            if fresca:
                centro = (pose[0] / 100.0, pose[1] / 100.0, float(pose[2]))
                r["centro"] = centro
                if "c1_volta" in r:
                    r["c1"] = (*r["c1_volta"], centro)
                if "c143_volta" in r:
                    r["c143"] = (*r["c143_volta"], centro)
            a = j.get("a145")
            if a and a.get("pose") and a.get("p") and a.get("ts") not in vistos:
                vistos.add(a.get("ts"))                  # a mesma volta vem em 2 registros
                p = np.array(a["p"], float)
                q = p[:, 2] > 0 if p.shape[1] > 2 else np.ones(len(p), bool)
                x, y, _z, rumo = a["pose"]
                r["laser"] = (p[q, 0] / 100.0, p[q, 1] / 1000.0, (x, y, float(rumo)))
            if "c1_volta" in r or "c143_volta" in r or "laser" in r:
                regs.append(r)
        out[n] = regs
    return out


def pontos_laser(ang, d):
    return no_sensor(ang, d, LASER_NO_PONTO)


def pontos_c1(ang, d):
    ok = (d > 0.15) & (d < 12.0) & ~((ang > C1_SOMBRA[0]) & (ang < C1_SOMBRA[1]))
    return no_sensor(ang[ok], d[ok], C1_NO_CENTRO)


def _na_sombra_topo(ang):
    a, b = C1_TOPO_SOMBRA_DEG
    ang = ang % 360.0
    return ((ang >= a) & (ang <= b)) if a <= b else ((ang >= a) | (ang <= b))


def pontos_c143(ang, d):
    """C1 de cima. O leitor já tira o tubo e < 15 cm; tirar de novo não custa."""
    ok = (d > 0.15) & (d < 12.0) & ~_na_sombra_topo(ang)
    return no_sensor(ang[ok], d[ok], C1_TOPO_NO_CENTRO)


# ─────────────────────────────────────────────
# A GRADE
# ─────────────────────────────────────────────
def montar_grade(voltas, res=RES, min_voltas=MIN_VOLTAS):
    """voltas = [(sx, sy, (x, y, rumo))] no referencial do portador → dict."""
    if not voltas:
        return None
    mundo = []
    for sx, sy, (x, y, r) in voltas:
        px, py = _gira(sx, sy, r)
        mundo.append((x + px, y + py))
    xs = np.concatenate([m[0] for m in mundo])
    ys = np.concatenate([m[1] for m in mundo])
    if len(xs) == 0:
        return None
    minx, maxy = float(xs.min()) - 0.5, float(ys.max()) + 0.5
    W = int((xs.max() + 0.5 - minx) / res) + 1
    H = int((maxy - (ys.min() - 0.5)) / res) + 1
    cont = np.zeros((H, W), np.int32)
    for wx, wy in mundo:                                  # conta VOLTAS, não pontos
        c = ((wx - minx) / res).astype(int)
        l = ((maxy - wy) / res).astype(int)
        idx = np.unique(l * W + c)
        cont.ravel()[idx] += 1
    parede = cont >= min_voltas
    return {"parede": parede, "contagem": cont, "res": res, "min_x": round(minx, 4), "max_y": round(maxy, 4),
            "largura_px": W, "altura_px": H, "voltas": len(voltas),
            "celulas": int(parede.sum())}


def _distancia_truncada(parede, res, raio_m):
    """Distância (m) de cada célula à parede mais próxima, até raio_m (além
    disso, inf). Feito em numpy puro de propósito: o scipy da Pi (do sistema,
    1.10) não importa com o numpy 2 do .venv (medido em 02/10/2026)."""
    H, W = parede.shape
    k = int(math.ceil(raio_m / res))
    offs = sorted(((dy * dy + dx * dx), dy, dx) for dy in range(-k, k + 1)
                  for dx in range(-k, k + 1) if dy * dy + dx * dx <= k * k)
    dist = np.full((H, W), np.inf)
    for r2, dy, dx in offs:          # do mais perto ao mais longe: o 1º que acha é o mínimo
        ys0, ys1 = max(0, dy), min(H, H + dy)
        xs0, xs1 = max(0, dx), min(W, W + dx)
        viz = parede[ys0 - dy:ys1 - dy, xs0 - dx:xs1 - dx]
        alvo = dist[ys0:ys1, xs0:xs1]
        novo = viz & np.isinf(alvo)
        alvo[novo] = math.sqrt(r2) * res
    return dist


def _campo(grade):
    dist = _distancia_truncada(grade["parede"], grade["res"], 4 * SIGMA)
    return np.exp(-dist ** 2 / (2 * SIGMA ** 2))


def _amostra(grade, campo, wx, wy):
    res = grade["res"]
    c = (wx - grade["min_x"]) / res - 0.5
    l = (grade["max_y"] - wy) / res - 0.5
    c0 = np.floor(c).astype(int); l0 = np.floor(l).astype(int)
    fc = c - c0; fl = l - l0
    H, W = campo.shape
    ok = (c0 >= 0) & (c0 < W - 1) & (l0 >= 0) & (l0 < H - 1)
    v = np.zeros(np.shape(wx))
    c0, l0, fc, fl = c0[ok], l0[ok], fc[ok], fl[ok]
    v[ok] = (campo[l0, c0] * (1 - fc) * (1 - fl) + campo[l0, c0 + 1] * fc * (1 - fl)
             + campo[l0 + 1, c0] * (1 - fc) * fl + campo[l0 + 1, c0 + 1] * fc * fl)
    return v


def localizar(grupos, x0, y0, r0):
    """grupos = [(sx, sy, grade, campo)] no referencial do centro. Busca
    grosso→fino a partir de (x0, y0, r0); devolve (x, y, rumo)."""
    total = sum(len(g[0]) for g in grupos) or 1
    melhor = (-1.0, x0, y0, r0)
    for passo_xy, passo_r, raio_xy, raio_r in ((0.05, 2.0, 0.40, 12.0),
                                               (0.01, 0.5, 0.06, 2.0),
                                               (0.005, 0.25, 0.015, 0.5)):
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
    return melhor[1], melhor[2], melhor[3]


def _rebaixar(ang, d, rng, n=275, alcance=8.0):
    o = np.argsort(ang); ang, d = ang[o], d[o]
    k = np.unique(np.linspace(0, len(d) - 1, n).astype(int))
    ang, d = ang[k], d[k]
    d = d + rng.normal(0, 0.02 + 0.01 * d)
    ok = (rng.random(len(d)) > 0.10) & (d > 0.10) & (d < alcance)
    return ang[ok], d[ok]


def _centro_do_ponto(x, y, rumo, braco_aurora):
    bx, by = _gira(braco_aurora[0], braco_aurora[1], rumo)
    return x - bx, y - by


# ─────────────────────────────────────────────
# O QUE O MAPEAMENTO CHAMA
# ─────────────────────────────────────────────
def _voltas(regs, braco_aurora):
    """Listas (sx, sy, pose) para as grades. O laser vai no referencial do
    PONTO do Aurora (é a pose dele que veio com a volta); os C1, no do centro."""
    v145, v22, v143 = [], [], []
    for r in regs:
        if "laser" in r:
            ang, d, pose = r["laser"]
            sx, sy = pontos_laser(ang, d)
            v145.append((sx, sy, pose))
        if "c1" in r:
            ang, d, pose = r["c1"]
            sx, sy = pontos_c1(ang, d)
            v22.append((sx, sy, pose))
        if "c143" in r:
            ang, d, pose = r["c143"]
            sx, sy = pontos_c143(ang, d)
            v143.append((sx, sy, pose))
    return v145, v22, v143


def _resumo(e):
    e = np.array(e)
    return {"n": len(e), "mediana_cm": round(float(np.median(e)), 1),
            "p90_cm": round(float(np.percentile(e, 90)), 1),
            "acima_30cm": int((e > 30).sum())}


def nota_c1(teste, g22, g143, n=30, semente=1, campos=None):
    """Erro típico (cm) de localizar o CENTRO com as voltas reais dos C1 da
    passada de teste, nos mapas feitos sem ela: só 22, só 1,43 e os dois.
    campos = (campo22, campo143) já calculados, se houver (cada um leva ~10 s)."""
    if g22 is None and g143 is None:
        return None
    rnd = random.Random(semente)
    if campos is None:
        campos = (_campo(g22) if g22 is not None else None,
                  _campo(g143) if g143 is not None else None)
    c22, c143 = campos
    amostra = [r for r in teste if "c1" in r and "c143" in r]
    amostra = rnd.sample(amostra, min(n, len(amostra)))
    erros = {"22 cm": [], "1,43 m": [], "os dois": []}
    for r in amostra:
        a22, d22, (cx, cy, cr) = r["c1"]
        a43, d43, _ = r["c143"]
        k = np.linspace(0, len(a22) - 1, min(275, len(a22))).astype(int)
        g_22 = (*pontos_c1(a22[k], d22[k]), g22, c22) if g22 is not None else None
        k = np.linspace(0, len(a43) - 1, min(275, len(a43))).astype(int)
        g_43 = (*pontos_c143(a43[k], d43[k]), g143, c143) if g143 is not None else None
        x0, y0 = cx + rnd.uniform(-0.3, 0.3), cy + rnd.uniform(-0.3, 0.3)
        r0 = cr + rnd.uniform(-8, 8)
        for chave, grupos in (("22 cm", [g_22]), ("1,43 m", [g_43]), ("os dois", [g_22, g_43])):
            grupos = [g for g in grupos if g is not None and len(g[0])]
            if len(grupos) == (2 if chave == "os dois" else 1):
                x, y, _ = localizar(grupos, x0, y0, r0)
                erros[chave].append(math.hypot(x - cx, y - cy) * 100)
    return {k: _resumo(e) for k, e in erros.items() if e} or None


NOTA_BURACO_S = 5.0     # mais que isto sem volta: o acompanhamento recomeça
NOTA_TRECHOS  = 8       # trechos espalhados pela passada de teste…
NOTA_TRECHO_VOLTAS = 30 # …de 30 voltas seguidas cada (~280 ms por volta no PC)


def nota_acompanhando(teste, c22, c143):
    """
    A NOTA PRINCIPAL (23/10/2026, P2): como o robô sem Aurora faz — o
    Rastreador de slam/sombra.py com os dois C1 e o giro do BNO, volta a volta,
    nos mapas feitos sem a passada de teste. NOTA_TRECHOS trechos de
    NOTA_TRECHO_VOLTAS voltas seguidas, espalhados pela passada (a passada
    inteira levaria minutos na Pi). Cada trecho começa — e recomeça, se perder
    ou se a coleta tiver buraco — na pose do Aurora; o erro só é medido onde
    a pose do Aurora estava fresca. c22/c143 = (grade, campo).
    A nota a frio (nota_c1) é mais dura que a vida real: no corredor de
    22/10, 5 dos 6 erros > 30 cm foram dela.
    """
    from slam.sombra import Rastreador          # sombra importa deste módulo
    if c22 is None or c143 is None:
        return None
    voltas = [r for r in teste if "c1_volta" in r]
    if len(voltas) <= NOTA_TRECHOS * NOTA_TRECHO_VOLTAS:
        trechos = [voltas]                      # passada curta: inteira, sem repetir volta
    else:
        k = len(voltas) // NOTA_TRECHOS
        trechos = [voltas[i * k:i * k + NOTA_TRECHO_VOLTAS] for i in range(NOTA_TRECHOS)]
    erros, sem_gabarito, perdas = [], 0, 0
    for trecho in trechos:
        rs = Rastreador(c22, c143, busca_m=0.35, limiar=0.55)
        ult = None
        for r in trecho:
            t = r.get("t")
            if ult is not None and t is not None and t - ult > NOTA_BURACO_S:
                rs.pose = None
            ult = t if t is not None else ult
            centro = r.get("centro")
            if rs.pose is None or rs.perdido:
                if centro is not None:
                    rs.semear(*centro, r.get("yaw"))
                continue
            x, y, _r, _e, perdido = rs.passo(*r["c1_volta"], r.get("yaw"), r.get("c143_volta"))
            if perdido:
                continue
            if centro is None:
                sem_gabarito += 1
                continue
            erros.append(math.hypot(x - centro[0], y - centro[1]) * 100)
        perdas += rs.perdas
    if not erros:
        return None
    return {"os dois": dict(_resumo(erros), perdas=perdas, sem_gabarito=sem_gabarito,
                            trechos=len(trechos))}


def nota(teste, g145, g22, braco_aurora, n=30, semente=1):
    """Erro típico (cm) de localizar o CENTRO com o que um C1 entrega."""
    if g145 is None:
        return None
    rng = np.random.default_rng(semente)
    rnd = random.Random(semente)
    c145, c22 = _campo(g145), (_campo(g22) if g22 is not None else None)
    amostra = [r for r in teste if "laser" in r]
    amostra = rnd.sample(amostra, min(n, len(amostra)))
    erros = {"1,45 m": [], "os dois": []}
    for r in amostra:
        ang, d, (ax, ay, ar) = r["laser"]
        cx, cy = _centro_do_ponto(ax, ay, ar, braco_aurora)
        a2, d2 = _rebaixar(ang, d, rng)
        # laser do ponto do Aurora → referencial do centro (mesmo rumo)
        lx, ly = no_sensor(a2, d2, LASER_NO_PONTO)
        bx, by = braco_aurora
        lx, ly = lx + bx, ly + by
        x0, y0 = cx + rnd.uniform(-0.3, 0.3), cy + rnd.uniform(-0.3, 0.3)
        r0 = ar + rnd.uniform(-8, 8)
        x, y, _ = localizar([(lx, ly, g145, c145)], x0, y0, r0)
        erros["1,45 m"].append(math.hypot(x - cx, y - cy) * 100)
        if c22 is not None and "c1" in r:
            ca, cd, (px, py, pr) = r["c1"]
            ca, cd = _rebaixar(ca, cd, rng, alcance=12.0)
            sx, sy = pontos_c1(ca, cd)
            # leituras do instante do C1 → referencial do centro no instante do laser
            wx, wy = _gira(sx, sy, pr)
            wx, wy = px + wx - cx, py + wy - cy
            ux, uy = _gira(wx, wy, -ar)
            x, y, _ = localizar([(lx, ly, g145, c145), (ux, uy, g22, c22)], x0, y0, r0)
            erros["os dois"].append(math.hypot(x - cx, y - cy) * 100)
    return {k: _resumo(e) for k, e in erros.items() if e}


def _gravar(grade, base, mapa_sha256, altura):
    from PIL import Image
    img = np.where(grade["parede"], 0, 255).astype(np.uint8)
    Image.fromarray(img, mode="L").save(base + ".png", optimize=True)
    meta = {k: grade[k] for k in ("res", "min_x", "max_y", "largura_px", "altura_px",
                                  "voltas", "celulas")}
    meta.update(mapa_sha256=mapa_sha256, altura=altura, min_voltas=MIN_VOLTAS,
                gerado_em=time.strftime("%Y-%m-%d %H:%M:%S"))
    with open(base + ".json", "w", encoding="utf-8") as f:
        json.dump(meta, f, indent=2, ensure_ascii=False)
    return meta


# ─────────────────────────────────────────────
# A PLANTA (02/10/2026, depois do SIGSEGV do SDK às 17:00)
# ─────────────────────────────────────────────
PLANTA_RES       = 0.05
PLANTA_LIVRE_MIN = 4        # célula livre = atravessada por feixes em 4+ voltas (L1, 23/10)
PLANTA_MANCHA_MIN = 8       # mancha de parede solta com menos células sai (~14×14 cm; L1)
PLANTA_FANTASMA_MAX = 0.12  # mancha parede em < 12 % das voltas que a viram sai (L2, 26/10)
PLANTA_ALCANCE_M = 8.0      # além disto o feixe não marca "livre"
PLANTA_VOLTA_ENCOSTA = 0.70    # volta do laser "encosta" no C1 de cima: 70 % dos pontos
PLANTA_DIVERGE_MAX   = 0.02    # mais que 2 % das voltas sem encostar: o laser divergiu


def _planta(regs, chave, res, passo_voltas, passo_feixes):
    """A planta de UMA fonte ("laser" ou "c143") → (img, grade das paredes) ou None."""
    montagem, pontos = ((LASER_NO_PONTO, pontos_laser) if chave == "laser"
                        else (C1_TOPO_NO_CENTRO, pontos_c143))
    voltas, origens = [], []
    for r in regs:
        if chave in r:
            ang, d, pose = r[chave]
            sx, sy = pontos(ang, d)
            voltas.append((sx, sy, pose))
            origens.append((ang, d, pose))
    g = montar_grade(voltas, res=res)
    if g is None:
        return None
    H, W, minx, maxy = g["altura_px"], g["largura_px"], g["min_x"], g["max_y"]
    livre = np.zeros((H, W), np.int32)
    passos = np.arange(0.0, PLANTA_ALCANCE_M, res / 2)
    for ang, d, (x, y, rumo) in origens[::passo_voltas]:
        ang, d = ang[::passo_feixes], np.minimum(d[::passo_feixes], PLANTA_ALCANCE_M)
        ox, oy, oth, sentido = montagem
        gx, gy = _gira(ox, oy, rumo)
        x0, y0 = x + gx, y + gy                                  # origem do sensor no mundo
        dirs = np.radians(rumo + sentido * ang + oth)
        t = passos[None, :]
        dentro = t < (d[:, None] - res)                          # para antes da parede
        px = (x0 + t * np.cos(dirs)[:, None])[dentro]
        py = (y0 + t * np.sin(dirs)[:, None])[dentro]
        c = ((px - minx) / res).astype(int); l = ((maxy - py) / res).astype(int)
        ok = (c >= 0) & (c < W) & (l >= 0) & (l < H)
        idx = np.unique(l[ok] * W + c[ok])
        livre.ravel()[idx] += 1
    # a parede conta TODAS as voltas; o livre, uma a cada passo_voltas
    return _limpar_planta(livre >= PLANTA_LIVRE_MIN, g["parede"],
                          g["contagem"], livre * passo_voltas), g


def _manchas(parede):
    """Cada mancha de parede (8-vizinhos) como lista de (linha, coluna). Busca
    em largura só pelas células de parede (numpy puro: o scipy da Pi não
    importa com o numpy do .venv)."""
    H, W = parede.shape
    visto = np.zeros_like(parede)
    for i0, j0 in zip(*np.nonzero(parede)):
        if visto[i0, j0]:
            continue
        visto[i0, j0] = True
        fila, k = [(i0, j0)], 0
        while k < len(fila):
            i, j = fila[k]
            k += 1
            for di in (-1, 0, 1):
                for dj in (-1, 0, 1):
                    a, b = i + di, j + dj
                    if 0 <= a < H and 0 <= b < W and parede[a, b] and not visto[a, b]:
                        visto[a, b] = True
                        fila.append((a, b))
        yield fila


def _manchas_pequenas(parede, minimo):
    """Células de parede em manchas com menos de `minimo` células."""
    fora = np.zeros_like(parede)
    for m in _manchas(parede):
        if len(m) < minimo:
            fora[tuple(np.array(m).T)] = True
    return fora


def _manchas_fantasma(parede, voltas_parede, voltas_livre, maximo):
    """L2 (26/10): mancha que foi parede em menos de `maximo` das voltas que
    passaram por ela é gente que cruzou a coleta (o feixe a atravessou nas
    outras). No maker-corredor: fantasmas 1–8 %, paredes e colunas 24–61 %."""
    fora = np.zeros_like(parede)
    for m in _manchas(parede):
        k = tuple(np.array(m).T)
        p, l = voltas_parede[k].sum(), voltas_livre[k].sum()
        if p < maximo * max(p + l, 1):
            fora[k] = True
    return fora


def _limpar_planta(livre, parede, voltas_parede=None, voltas_livre=None):
    """L1 (aprovada em 23/10): a planta "cheia de borrões" do maker-corredor.
    Livre só com PLANTA_LIVRE_MIN voltas (já vem em `livre`); manchas de parede
    soltas menores que PLANTA_MANCHA_MIN somem; ponta de livre com 1 célula de
    largura (no máximo 1 vizinho livre em 4) vira desconhecido. Parede de
    verdade fica, inclusive as da escada do maker-corredor. L2 (26/10): com
    as contagens, sai também a mancha fantasma (_manchas_fantasma)."""
    parede = parede & ~_manchas_pequenas(parede, PLANTA_MANCHA_MIN)
    if voltas_parede is not None:
        parede = parede & ~_manchas_fantasma(parede, voltas_parede, voltas_livre,
                                             PLANTA_FANTASMA_MAX)
    livre = livre & ~parede
    p = np.pad(livre, 1)
    viz = (p[:-2, 1:-1].astype(np.int8) + p[2:, 1:-1] + p[1:-1, :-2] + p[1:-1, 2:])
    livre = livre & (viz >= 2)
    img = np.full(livre.shape, 128, np.uint8)
    img[livre] = 255
    img[parede] = 0
    return img


def divergencia_laser(regs, topo):
    """Fração das voltas do LASER que não encostam nas paredes do C1 de cima,
    cada uma na pose que veio com ela (menos de PLANTA_VOLTA_ENCOSTA dos pontos
    até 6 m a ~10 cm de uma parede). Pose atrasada desloca a volta INTEIRA;
    um móvel que só o laser vê mexe em poucos pontos. Medido em 22/10: sala
    0 % das voltas, corredor com o Aurora lento 4,9–9,2 %."""
    _img, g = topo
    campo = _campo(g)
    ruins = total = 0
    for r in regs:
        if "laser" not in r:
            continue
        ang, d, (x, y, rumo) = r["laser"]
        k = d < 6.0
        sx, sy = pontos_laser(ang[k][::3], d[k][::3])
        if len(sx) < 20:
            continue
        px, py = _gira(sx, sy, rumo)
        total += 1
        ruins += float(np.mean(_amostra(g, campo, x + px, y + py) > 0.6)) < PLANTA_VOLTA_ENCOSTA
    return ruins / total if total else 0.0


def gerar_planta(regs, pacote_dir, mapa_sha256, nome_mapa, res=PLANTA_RES,
                 passo_voltas=2, passo_feixes=3):
    """
    A planta sobre a qual o operador desenha e o planejador traça a rota, feita
    das voltas da coleta com a pose ao vivo. PNG como o do Aurora: 0 = parede,
    255 = livre, 128 = desconhecido (slam/planejador.py: LIMIAR_OCUPADO 80,
    LIMIAR_LIVRE 200). Vantagem medida em 02/10: a planta exportada pelo Aurora
    diferia ~9 cm da pose ao vivo; esta é feita COM a pose ao vivo.

    A FONTE (23/10/2026, P1b): com o laser do Aurora E o C1 de cima, faz as
    duas e confere volta a volta o laser contra a do C1 de cima
    (divergencia_laser). Coincidem → a do laser (~2.000 pontos por volta, mais
    nítida). Divergem → a do C1 de cima, com aviso: a pose que vem com a volta
    do laser é a do Aurora, não a do instante da volta, e com o Aurora lento
    duplicou o corredor em 22/10 (a do C1 de cima saiu certa). Só uma das
    fontes → ela.
    """
    from PIL import Image
    from sensors.aurora_mapa import eixo_das_paredes, picos
    laser = (_planta(regs, "laser", res, passo_voltas, passo_feixes)
             if any("laser" in r for r in regs) else None)
    # o C1 tem ~430 pontos por volta, não ~2.000: todos os feixes
    topo = (_planta(regs, "c143", res, passo_voltas, 1)
            if any("c143" in r for r in regs) else None)
    if laser is None and topo is None:
        return None
    div, aviso = None, None
    if laser is not None and topo is not None:
        div = divergencia_laser(regs, topo)
        if div > PLANTA_DIVERGE_MAX:
            pct = f"{div * 100:.1f}".replace(".", ",")
            aviso = (f"a planta do laser do Aurora divergiu do C1 de cima ({pct} % "
                     f"das voltas fora do lugar) — usada a do C1 de cima")
            Image.fromarray(laser[0], mode="L").save(
                os.path.join(pacote_dir, "planta_laser_divergente.png"), optimize=True)
    usar_laser = laser is not None and (topo is None or div <= PLANTA_DIVERGE_MAX)
    img, g = laser if usar_laser else topo
    H, W, minx, maxy = g["altura_px"], g["largura_px"], g["min_x"], g["max_y"]
    Image.fromarray(img, mode="L").save(os.path.join(pacote_dir, "planta.png"), optimize=True)
    i, j = np.nonzero(img == 0)                     # as paredes que ficaram na planta (L1/L2)
    ocup = np.stack([minx + (j + .5) * res, (maxy - (i + .5) * res)], 1)
    ang_p = eixo_das_paredes(ocup, res) if len(ocup) else 0.0
    meta = {"mapa": nome_mapa, "mapa_sha256": mapa_sha256, "res": res,
            "min_x": minx, "min_y": round(maxy - H * res, 4), "max_y": maxy,
            "largura_px": W, "altura_px": H, "eixo_paredes_deg": ang_p,
            "paredes": ([{"eixo_deg": ang_p, "posicoes_m": picos(ocup, ang_p, res)},
                         {"eixo_deg": ang_p + 90, "posicoes_m": picos(ocup, ang_p + 90, res)}]
                        if len(ocup) else []),
            "ocupadas": int(len(ocup)), "livres": int((img == 255).sum()),
            "origem": ("coleta (laser do Aurora + pose ao vivo)" if usar_laser
                       else "coleta (C1 de 1,43 m + pose ao vivo)"),
            "divergencia_laser_pct": None if div is None else round(div * 100, 2),
            "aviso": aviso,
            "gerada_em": time.strftime("%Y-%m-%d %H:%M:%S")}
    with open(os.path.join(pacote_dir, "planta.json"), "w", encoding="utf-8") as f:
        json.dump(meta, f, indent=2, ensure_ascii=False)
    return {"ocupadas": meta["ocupadas"], "livres": meta["livres"],
            "fonte": "laser" if usar_laser else "C1 de 1,43 m",
            "divergencia_laser_pct": meta["divergencia_laser_pct"], "aviso": aviso}


def gerar_mapas(pacote_dir, braco_aurora=(-0.053, 0.072), n_nota=30, fazer_planta=True):
    """
    Chamado no fim do mapeamento (gerar_mapas_fn), com o robô parado. Grava os
    dois mapas no pacote e devolve o resumo que vai para a ficha.
    """
    t0 = time.monotonic()
    try:
        os.nice(10)                       # não disputar a CPU com o loop de 50 Hz
    except (AttributeError, OSError):
        pass
    ficha = json.load(open(os.path.join(pacote_dir, "ficha.json"), encoding="utf-8"))
    sha = ficha.get("mapa_sha256")
    passadas = ler_coleta(os.path.join(pacote_dir, "coleta"))
    todos = [r for n in sorted(passadas) for r in passadas[n]]
    v145, v22, v143 = _voltas(todos, braco_aurora)
    g145, g22, g143 = montar_grade(v145), montar_grade(v22), montar_grade(v143)
    res = {"1,43 m": None, "22 cm": None, "nota": None}
    pid = os.path.basename(os.path.normpath(pacote_dir)).replace(".parcial", "")
    # fazer_planta=False: pacote que já tem planta com áreas desenhadas em cima
    # (ex.: a Sala do lab, planta do Aurora) — só os mapas dos C1.
    res["planta"] = (gerar_planta(todos, pacote_dir, sha, f"{pid}/mapa.stcm")
                     if fazer_planta else "mantida")
    if res["planta"] is None:
        res["motivo_planta"] = "sem voltas do C1 de cima nem do laser do Aurora — planta não gerada"

    def _resumo_grade(g, nome, altura):
        return {k: v for k, v in _gravar(g, os.path.join(pacote_dir, nome), sha, altura).items()
                if k in ("voltas", "celulas")}
    if g143 is not None:
        res["1,43 m"] = _resumo_grade(g143, "c1_143", "1,43 m")
    else:
        res["motivo_143"] = "nenhuma volta do C1 de cima com pose fresca (FROTA_LIDAR_TOPO_PORT?)"
    if g145 is not None:                              # coleta antiga, com o laser
        res["1,45 m"] = _resumo_grade(g145, "c1_145", "1,45 m")
    if g22 is not None:
        res["22 cm"] = _resumo_grade(g22, "c1_22", "22 cm")
    else:
        res["motivo_22"] = "nenhuma varredura do C1 com pose na coleta"
    # A planta fina (27/10/2026): onde o operador desenha, em traço de 2 cm.
    try:
        from slam.planta_fina import gerar_fino
        res["fino"] = gerar_fino(pacote_dir)
    except Exception as e:                      # nunca derruba os mapas
        res["fino"] = None
        res["motivo_fino"] = f"planta fina não gerada: {e}"
    # A nota: mapa SEM a última passada, teste NELA.
    if len(passadas) >= 2 and (g143 is not None or g145 is not None):
        ult = max(passadas)
        antes = [r for n in sorted(passadas) if n != ult for r in passadas[n]]
        a145, a22, a143 = _voltas(antes, braco_aurora)
        if g143 is not None:
            g22a, g143a = montar_grade(a22), montar_grade(a143)
            f22 = _campo(g22a) if g22a is not None else None
            f143 = _campo(g143a) if g143a is not None else None
            res["nota"] = nota_acompanhando(passadas[ult],
                                            (g22a, f22) if g22a is not None else None,
                                            (g143a, f143) if g143a is not None else None)
            res["nota_modo"] = "acompanhando"
            res["nota_a_frio"] = nota_c1(passadas[ult], g22a, g143a, n=n_nota,
                                         campos=(f22, f143))
        else:
            res["nota"] = nota(passadas[ult], montar_grade(a145), montar_grade(a22),
                               braco_aurora, n=n_nota)
    res["segundos"] = round(time.monotonic() - t0, 1)
    return res


def gerar_mapas_em_processo(pasta, braco_aurora=(-0.053, 0.072), limite_s=900,
                            fazer_planta=True):
    """
    O que o SERVIÇO chama: gera num PROCESSO à parte. O cálculo tem laços em
    Python que segurariam o GIL e poderiam atrasar o loop de 50 Hz de
    segurança, se rodassem numa thread do serviço. Medido na Pi em 02/10/2026,
    num processo à parte, com o serviço no ar: 33 s para 46 min de coleta,
    jitter máximo do loop 2,35 ms, nenhum ciclo atrasado.
    """
    import subprocess
    import sys
    raiz = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    cmd = [sys.executable, "-W", "ignore", "-m", "slam.mapa_c1", pasta,
           json.dumps(list(braco_aurora))] + ([] if fazer_planta else ["--sem-planta"])
    r = subprocess.run(cmd, cwd=raiz, capture_output=True, text=True, timeout=limite_s)
    if r.returncode != 0:
        raise RuntimeError(f"gerador saiu com {r.returncode}: {r.stderr.strip()[-300:]}")
    return json.loads(r.stdout.strip().splitlines()[-1])


if __name__ == "__main__":
    import sys
    braco = tuple(json.loads(sys.argv[2])) if len(sys.argv) > 2 else (-0.053, 0.072)
    print(json.dumps(gerar_mapas(sys.argv[1], braco_aurora=braco,
                                 fazer_planta="--sem-planta" not in sys.argv),
                     ensure_ascii=False))
