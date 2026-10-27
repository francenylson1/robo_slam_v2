"""
slam/planta_fina.py — a PLANTA FINA, onde o operador desenha (27/10/2026).

A planta da rota (planta.png, células de 5 cm) soma todas as voltas da coleta,
cada uma com 2–5 cm de erro de pose: cada parede vira uma faixa de 10–20 cm e,
desenhando em cima dela, "2–3 mm na tela viravam 50–80 cm no chão" (P5 do
maker-corredor). A planta fina é o mapa do C1 de cima (2 cm, só células vistas
em 3+ voltas) em traço fino — pilares de 15×10 cm, recuos de porta e a escada
aparecem — mais as PAREDES MEDIDAS: o centro de cada faixa, achado por
histograma nos dois eixos da sala (posição a ~1 cm), com começo e fim.

A rota e o vigia continuam na planta.png (mais conservadora). Esta é só para
desenhar áreas e POIs com medida.

Gera no pacote: fino.png (RGBA: C1 de cima em azul, C1 de 22 cm em vermelho
onde o de cima não viu; o resto transparente) e fino.json (georreferência +
eixo + paredes). Numpy e PIL, ~1 s; roda no processo do gerador de mapas.
    python3 -m slam.planta_fina <pacote>      (pacotes antigos)
"""
import json
import math
import os
import time

import numpy as np

FINO_COR_TOPO = (120, 165, 255, 255)
FINO_COR_22 = (235, 95, 85, 200)
FINO_PASSO_EIXO = 0.1       # graus, na busca do eixo das paredes
FINO_FAIXA_M = 0.06         # pontos a até 6 cm do centro pertencem à parede
FINO_PICO_MIN = 40          # pontos (janela de 9 cm) para ser candidata a parede
FINO_PONTOS_MIN = 15
FINO_BURACO_M = 0.20        # vão maior que isto parte a parede em dois trechos
FINO_TRECHO_MIN_M = 0.30
FINO_TIQUE_M = 0.45         # trecho perpendicular curto encostado numa parede longa:
FINO_LONGA_M = 1.0          # é a espessura da faixa, não uma parede


def _ler(pacote, nome):
    base = os.path.join(pacote, nome)
    if not (os.path.isfile(base + ".png") and os.path.isfile(base + ".json")):
        return None
    from PIL import Image
    meta = json.load(open(base + ".json", encoding="utf-8"))
    img = np.array(Image.open(base + ".png").convert("L"))
    return meta, img


def _pontos(meta, img):
    lin, col = np.nonzero(img < 128)
    return meta["min_x"] + col * meta["res"], meta["max_y"] - lin * meta["res"]


def _uv(x, y, eixo_deg):
    a = math.radians(eixo_deg)
    return x * math.cos(a) + y * math.sin(a), -x * math.sin(a) + y * math.cos(a)


def eixo_paredes(x, y):
    """O ângulo (0–90°) que deixa as paredes mais "em pé" nos histogramas."""
    def nitidez(d):
        s = 0.0
        for q in _uv(x, y, d):
            h, _ = np.histogram(q, bins=np.arange(q.min(), q.max() + 0.02, 0.02))
            s += float((h.astype(float) ** 2).sum())
        return s
    grosso = max(np.arange(0.0, 90.0, 1.0), key=nitidez)
    return float(max(np.arange(grosso - 1.0, grosso + 1.0 + 1e-9, FINO_PASSO_EIXO), key=nitidez))


def paredes(x, y, eixo_deg):
    """Trechos de parede: {"fam": "u"|"v", "pos", "de", "ate"} em metros.
    fam "u" = parede de u constante (corre ao longo de v), e vice-versa."""
    u, v = _uv(x, y, eixo_deg)
    usado = np.zeros(len(x), bool)
    trechos = []
    for fam, p, q in (("u", u, v), ("v", v, u)):
        h, e = np.histogram(p, bins=np.arange(p.min() - 0.05, p.max() + 0.06, 0.01))
        hs = np.convolve(h, np.ones(9), "same")
        picos = [i for i in range(5, len(hs) - 5)
                 if hs[i] == hs[i - 5:i + 6].max() and hs[i] >= FINO_PICO_MIN]
        for i in picos:
            pos = e[i] + 0.005
            sel = np.nonzero((np.abs(p - pos) < FINO_FAIXA_M) & ~usado)[0]
            if len(sel) < FINO_PONTOS_MIN:
                continue
            o = sel[np.argsort(q[sel])]
            qq = q[o]
            for g in np.split(np.arange(len(o)), np.nonzero(np.diff(qq) > FINO_BURACO_M)[0] + 1):
                if len(g) < FINO_PONTOS_MIN or qq[g[-1]] - qq[g[0]] < FINO_TRECHO_MIN_M:
                    continue
                idx = o[g]
                usado[idx] = True
                trechos.append({"fam": fam, "pos": round(float(np.median(p[idx])), 3),
                                "de": round(float(qq[g[0]]), 3), "ate": round(float(qq[g[-1]]), 3)})
    longas = [t for t in trechos if t["ate"] - t["de"] >= FINO_LONGA_M]

    def tique(t):
        if t["ate"] - t["de"] >= FINO_TIQUE_M:
            return False
        return any(L["fam"] != t["fam"] and L["de"] - 0.1 <= t["pos"] <= L["ate"] + 0.1
                   and min(abs(t["de"] - L["pos"]), abs(t["ate"] - L["pos"])) < 0.30
                   for L in longas)
    return [t for t in trechos if not tique(t)]


FINO_FRACAO_MIN = 0.12      # a L3 da planta (slam/mapa_c1.py), célula a célula, a 2 cm
FINO_ALCANCE_M = 8.0


def limpar_por_fracao(pacote, meta, img, chave="c143"):
    """L3 na planta fina (27/10/2026): com a coleta do pacote, conta por célula
    as voltas do C1 de cima que BATERAM e as que ATRAVESSARAM; fica parede só
    quem barrou o feixe em FINO_FRACAO_MIN das vezes. Na porta do
    maker-corredor sai o fantasma de quem andou ao lado do robô (4–5 %) e a
    espessura falsa atrás das paredes; a superfície real (15–60 %) fica — é o
    traço fino. chave "c1" = o C1 de 22 cm (pernas de gente na coleta).
    Sem coleta, devolve a máscara como veio."""
    parede = img < 128
    pasta = os.path.join(pacote, "coleta")
    if not os.path.isdir(pasta):
        return parede, None
    from slam import mapa_c1 as M
    regs = [r for n, p in sorted(M.ler_coleta(pasta).items()) for r in p if chave in r]
    if not regs:
        return parede, None
    H, W = parede.shape
    res, minx, maxy = meta["res"], meta["min_x"], meta["max_y"]
    bate = np.zeros(H * W, np.int32)
    passa = np.zeros(H * W, np.int32)
    ox, oy, oth, sentido = M.C1_TOPO_NO_CENTRO if chave == "c143" else M.C1_NO_CENTRO
    sombra = (M._na_sombra_topo if chave == "c143"
              else lambda a: (a > M.C1_SOMBRA[0]) & (a < M.C1_SOMBRA[1]))
    passos = np.arange(0.0, FINO_ALCANCE_M, res)[None, :]
    for r in regs:
        ang, d, (x, y, rumo) = r[chave]
        ok = (d > 0.15) & (d < 12.0) & ~sombra(ang)
        ang, d = ang[ok], d[ok]
        gx, gy = M._gira(ox, oy, rumo)
        x0, y0 = x + gx, y + gy
        dirs = np.radians(rumo + sentido * ang + oth)
        cs, sn = np.cos(dirs), np.sin(dirs)

        def idx(wx, wy):
            c = ((wx - minx) / res).astype(int); l = ((maxy - wy) / res).astype(int)
            k = (c >= 0) & (c < W) & (l >= 0) & (l < H)
            return np.unique(l[k] * W + c[k])
        h = idx(x0 + d * cs, y0 + d * sn)
        bate[h] += 1
        dentro = passos < np.minimum(d, FINO_ALCANCE_M)[:, None] - 2 * res
        p = np.setdiff1d(idx((x0 + passos * cs[:, None])[dentro], (y0 + passos * sn[:, None])[dentro]),
                         h, assume_unique=True)
        passa[p] += 1
    bate, passa = bate.reshape(H, W), passa.reshape(H, W)
    limpa = parede & (bate >= FINO_FRACAO_MIN * (bate + passa))
    return limpa, int(parede.sum() - limpa.sum())


def gerar_fino(pacote):
    """Grava fino.png + fino.json no pacote. None se não há mapa do C1 de cima."""
    from PIL import Image
    topo = _ler(pacote, "c1_143") or _ler(pacote, "c1_145")
    if topo is None:
        return None
    meta, img = topo
    parede, tirou = limpar_por_fracao(pacote, meta, img)
    img = np.where(parede, 0, 255).astype(np.uint8)
    H, W = img.shape
    rgba = np.zeros((H, W, 4), np.uint8)
    baixo = _ler(pacote, "c1_22")
    if baixo is not None:                      # o C1 de 22 cm, na grade do de cima
        m22, img22 = baixo
        img22 = np.where(limpar_por_fracao(pacote, m22, img22, "c1")[0], 0, 255).astype(np.uint8)
        bx, by = _pontos(m22, img22)
        col = np.round((bx - meta["min_x"]) / meta["res"]).astype(int)
        lin = np.round((meta["max_y"] - by) / meta["res"]).astype(int)
        ok = (col >= 0) & (col < W) & (lin >= 0) & (lin < H)
        rgba[lin[ok], col[ok]] = FINO_COR_22
    rgba[img < 128] = FINO_COR_TOPO
    Image.fromarray(rgba, mode="RGBA").save(os.path.join(pacote, "fino.png"), optimize=True)
    x, y = _pontos(meta, img)
    eixo = eixo_paredes(x, y)
    doc = {"res": meta["res"], "min_x": meta["min_x"], "max_y": meta["max_y"],
           "largura_px": W, "altura_px": H, "mapa_sha256": meta.get("mapa_sha256"),
           "fonte": "1,43 m" if os.path.isfile(os.path.join(pacote, "c1_143.png")) else "1,45 m",
           "eixo_deg": round(eixo, 1), "paredes": paredes(x, y, eixo),
           "l3_tirou": tirou, "gerado_em": time.strftime("%Y-%m-%d %H:%M:%S")}
    with open(os.path.join(pacote, "fino.json"), "w", encoding="utf-8") as f:
        json.dump(doc, f, ensure_ascii=False)
    return {"eixo_deg": doc["eixo_deg"], "paredes": len(doc["paredes"]), "l3_tirou": tirou}


if __name__ == "__main__":
    import sys
    print(json.dumps(gerar_fino(sys.argv[1])))
