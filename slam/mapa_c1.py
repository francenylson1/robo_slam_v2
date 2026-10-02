"""
slam/mapa_c1.py
OS MAPAS DOS C1 — o mapa de referência com que os robôs SEM Aurora se
localizam, montado com a coleta do robô 1 (pacote de ambiente, Etapa B.2,
02/10/2026; contrato da V1, docs/PRD.md §0 item 2: os dois C1, 22 cm e 1,45 m).

DE ONDE VEM: as varreduras das passadas de coleta (coleta/passada_N.jsonl,
copiadas do gravador de sempre por slam/mapeamento.py), gravadas com o robô 1
JÁ LOCALIZADO no mapa salvo — a grade que o Aurora exporta não serve (bancada
de 02/10: ~9 cm contra ~5 cm deste método).

  1,45 m — a volta do LASER DO AURORA ("a145": ~2.000 pontos, a pose do próprio
           Aurora na hora da volta). O mapa NÃO é rebaixado ao C1: é o melhor
           possível; quem lê menos é o C1 do outro robô.
  22 cm  — o C1 do próprio robô 1 ("p", com a pose do CENTRO no instante).

COMO: grade de 2 cm; uma célula é PAREDE se foi vista em pelo menos 3 voltas
(contam-se voltas, não pontos) — quem passou uma vez não vira parede. Método
medido em 30/09 (sala, 22 cm, ~5 cm), 01/10 (sala, 1,45 m, ~5 cm) e 02/10
(corredor, 1,45 m ~6,6 cm; os dois juntos ~2,4 cm): scripts/teste_c1_*.py.

A NOTA: monta o mapa SEM a última passada e localiza uma amostra das voltas
dela, rebaixadas ao que um C1 entrega (275 pontos, 8 m, ruído de 2 cm + 1%,
10% de feixes perdidos), a partir da pose certa deslocada ±30 cm/±8°. O erro
típico (mediana e p90, em cm) é a nota. Gabarito = a pose do Aurora: a nota
diz o quanto os C1 CONCORDAM com o Aurora, não o erro contra a trena.

Saída no pacote: c1_145.png/.json e c1_22.png/.json (PNG: 0 = parede,
255 = resto; o .json traz origem, escala e o sha do mapa do Aurora).
Nada aqui move o robô.
"""

import glob
import json
import math
import os
import random
import time

import numpy as np

RES          = 0.02
MIN_VOLTAS   = 3
SIGMA        = 0.10
# Montagens em relação ao CENTRO do robô 1 (frente, esquerda, giro°, sentido).
# Laser do Aurora: a origem fica 2,5 cm à frente e 3,0 cm à direita do PONTO
# do Aurora, giro −0,4°, anti-horário (teste de 01/10); o ponto do Aurora fica
# (−5,3; +7,2) cm do centro (AURORA_BRACO_M, 30/09). Aqui a pose da volta é a
# do próprio Aurora, então usa-se o braço do LASER em relação ao PONTO.
LASER_NO_PONTO = (0.025, -0.030, -0.4, 1)
C1_NO_CENTRO   = (0.30, 0.0, 0.0, -1)      # C1: 30 cm à frente, ângulo horário
C1_SOMBRA      = (140.0, 210.0)            # a coluna atrás do C1 (21/09)


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
            r = {"t": j.get("t")}
            pose = j.get("pose")
            if pose and j.get("p"):
                c1 = np.array(j["p"], float)
                r["c1"] = (c1[:, 0] / 100.0, c1[:, 1] / 1000.0,
                           (pose[0] / 100.0, pose[1] / 100.0, float(pose[2])))
            a = j.get("a145")
            if a and a.get("pose") and a.get("p") and a.get("ts") not in vistos:
                vistos.add(a.get("ts"))                  # a mesma volta vem em 2 registros
                p = np.array(a["p"], float)
                q = p[:, 2] > 0 if p.shape[1] > 2 else np.ones(len(p), bool)
                x, y, _z, rumo = a["pose"]
                r["laser"] = (p[q, 0] / 100.0, p[q, 1] / 1000.0, (x, y, float(rumo)))
            if "c1" in r or "laser" in r:
                regs.append(r)
        out[n] = regs
    return out


def pontos_laser(ang, d):
    return no_sensor(ang, d, LASER_NO_PONTO)


def pontos_c1(ang, d):
    ok = (d > 0.15) & (d < 12.0) & ~((ang > C1_SOMBRA[0]) & (ang < C1_SOMBRA[1]))
    return no_sensor(ang[ok], d[ok], C1_NO_CENTRO)


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
    return {"parede": parede, "res": res, "min_x": round(minx, 4), "max_y": round(maxy, 4),
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
    """Listas (sx, sy, pose) para as duas grades. O laser vai no referencial do
    PONTO do Aurora (é a pose dele que veio com a volta)."""
    v145, v22 = [], []
    for r in regs:
        if "laser" in r:
            ang, d, pose = r["laser"]
            sx, sy = pontos_laser(ang, d)
            v145.append((sx, sy, pose))
        if "c1" in r:
            ang, d, pose = r["c1"]
            sx, sy = pontos_c1(ang, d)
            v22.append((sx, sy, pose))
    return v145, v22


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
    out = {}
    for k, e in erros.items():
        if e:
            e = np.array(e)
            out[k] = {"n": len(e), "mediana_cm": round(float(np.median(e)), 1),
                      "p90_cm": round(float(np.percentile(e, 90)), 1),
                      "acima_30cm": int((e > 30).sum())}
    return out


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


def gerar_mapas(pacote_dir, braco_aurora=(-0.053, 0.072), n_nota=30):
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
    v145, v22 = _voltas(todos, braco_aurora)
    g145, g22 = montar_grade(v145), montar_grade(v22)
    res = {"1,45 m": None, "22 cm": None, "nota": None}
    if g145 is not None:
        res["1,45 m"] = {k: v for k, v in _gravar(g145, os.path.join(pacote_dir, "c1_145"),
                                                   sha, "1,45 m").items()
                         if k in ("voltas", "celulas")}
    else:
        res["motivo_145"] = "nenhuma volta do laser do Aurora na coleta (laser desligado?)"
    if g22 is not None:
        res["22 cm"] = {k: v for k, v in _gravar(g22, os.path.join(pacote_dir, "c1_22"),
                                                  sha, "22 cm").items()
                        if k in ("voltas", "celulas")}
    else:
        res["motivo_22"] = "nenhuma varredura do C1 com pose na coleta"
    # A nota: mapa SEM a última passada, teste NELA.
    if len(passadas) >= 2 and g145 is not None:
        ult = max(passadas)
        antes = [r for n in sorted(passadas) if n != ult for r in passadas[n]]
        a145, a22 = _voltas(antes, braco_aurora)
        res["nota"] = nota(passadas[ult], montar_grade(a145), montar_grade(a22),
                           braco_aurora, n=n_nota)
    res["segundos"] = round(time.monotonic() - t0, 1)
    return res


def gerar_mapas_em_processo(pasta, braco_aurora=(-0.053, 0.072), limite_s=900):
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
           json.dumps(list(braco_aurora))]
    r = subprocess.run(cmd, cwd=raiz, capture_output=True, text=True, timeout=limite_s)
    if r.returncode != 0:
        raise RuntimeError(f"gerador saiu com {r.returncode}: {r.stderr.strip()[-300:]}")
    return json.loads(r.stdout.strip().splitlines()[-1])


if __name__ == "__main__":
    import sys
    braco = tuple(json.loads(sys.argv[2])) if len(sys.argv) > 2 else (-0.053, 0.072)
    print(json.dumps(gerar_mapas(sys.argv[1], braco_aurora=braco), ensure_ascii=False))
