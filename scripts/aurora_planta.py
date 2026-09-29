#!/usr/bin/env python3
"""
scripts/aurora_planta.py
Gera a PLANTA do mapa de navegação: a imagem sobre a qual o operador desenha
as áreas proibidas e os POIs, e sobre a qual o dashboard desenha o robô.

Decisão 7 de 29/09/2026: a planta é gerada UMA VEZ, na bancada, com o serviço
parado (um cliente só no Aurora), a partir da grade 2D do mapa CARREGADO no
Aurora, e guardada junto do mapa com a origem e a escala. É a mesma referência
da pose: se o robô aparece no lugar certo da planta, mapa e pose conferem.

Vem do ~/aurora_sdk/onde_na_sala.py de 28/09 (as mesmas chamadas do SDK). Com
l2p_mapping=True o OCUPADO vem ESCURO (valor baixo), não 255 — conferido em
28/09, e duas execuções falharam antes disso.

Pré-requisitos: o mapa combinado JÁ CARREGADO e relocalizado no Aurora (a
partida pelo dashboard faz isso), e depois o serviço parado:
  sudo systemctl stop frota-rosto frota-robo

Saída, ao lado do mapa (data/aurora/mapas/):
  <mapa>_planta.png   — a grade, 1 pixel = RES m, topo da imagem = +y
  <mapa>_planta.json  — origem, escala, sha do mapa e o eixo das paredes

Conversão (a mesma no servidor e no navegador):
  x = min_x + (coluna + 0,5) · res
  y = max_y − (linha  + 0,5) · res
"""

import argparse
import json
import math
import os
import sys
import time

_RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _RAIZ not in sys.path:
    sys.path.insert(0, _RAIZ)
from sensors.aurora_cliente_unico import exigir_servico_parado  # noqa: E402

RES = 0.05


def eixo_das_paredes(ocup, res):
    """Ângulo (0–90°) em que as células ocupadas mais se alinham — as paredes."""
    import numpy as np
    melhor = (-1.0, 0.0)
    for a10 in range(0, 900):
        a = math.radians(a10 / 10)
        u = ocup @ np.array([math.cos(a), math.sin(a)])
        h, _ = np.histogram(u, bins=np.arange(u.min() - res, u.max() + 2 * res, res))
        s = float((h.astype(float) ** 2).sum())
        if s > melhor[0]:
            melhor = (s, a10 / 10)
    return melhor[1]


def picos(ocup, ang_deg, res):
    import numpy as np
    v = np.array([math.cos(math.radians(ang_deg)), math.sin(math.radians(ang_deg))])
    u = ocup @ v
    e = np.arange(u.min() - res, u.max() + 2 * res, res)
    h, _ = np.histogram(u, bins=e)
    c = e[:-1] + res / 2
    lim = 0.25 * h.max()
    return [round(float(c[k]), 3) for k in range(len(h))
            if h[k] >= lim and h[k] == h[max(0, k - 2):k + 3].max()]


def main():
    from config.settings import AURORA_IP, AURORA_MAPA, AURORA_MAPA_SHA256
    ap = argparse.ArgumentParser(description="Gera a planta do mapa carregado no Aurora.")
    ap.add_argument("--ip", default=AURORA_IP)
    args = ap.parse_args()

    exigir_servico_parado()

    import numpy as np
    from PIL import Image
    from slamtec_aurora_sdk import AuroraSDK
    from slamtec_aurora_sdk.data_types import GridMapGenerationOptions, Rect
    from slamtec_aurora_sdk.utils import wait_for_map_data

    sdk = AuroraSDK()
    sdk.connect(connection_string=args.ip)
    try:
        time.sleep(1.5)
        st, _ = sdk.data_provider.get_last_device_status()
        print(f"status do Aurora: {st} (13 = relocalizado no mapa)")
        sdk.enable_map_data_syncing(True)
        wait_for_map_data(sdk.data_provider, min_keyframes=10,
                          min_sync_ratio=0.8, max_wait_time=30.0)
        o = GridMapGenerationOptions()
        o.resolution = RES
        o.map_canvas_width = 200.0
        o.map_canvas_height = 200.0
        o.active_map_only = 1
        o.height_range_specified = 1
        o.min_height = -0.5
        o.max_height = 2.0
        gm = sdk.lidar_2d_map_builder.generate_fullmap_ondemand(
            o, wait_for_data_sync=True, timeout_ms=60000)
        d = gm.get_map_dimension()
        rect = Rect()
        rect.x, rect.y = d.min_x, d.min_y
        rect.width, rect.height = d.max_x - d.min_x, d.max_y - d.min_y
        cells, info = gm.read_cell_data(rect, resolution=RES, l2p_mapping=True)
        g = np.array(cells, dtype=np.uint8).reshape(info.cell_height, info.cell_width)
    finally:
        try:
            sdk.enable_map_data_syncing(False)
        except Exception:
            pass
        sdk.disconnect()

    # Linha 0 da grade = min_y. Na imagem, o topo é +y: inverte as linhas.
    img = np.flipud(g)
    base = os.path.splitext(AURORA_MAPA)[0]
    Image.fromarray(img, mode="L").save(base + "_planta.png", optimize=True)

    i, j = np.nonzero(g < 80)
    ocup = np.stack([d.min_x + (j + .5) * RES, d.min_y + (i + .5) * RES], 1)
    ang = eixo_das_paredes(ocup, RES)
    meta = {
        "mapa": os.path.basename(AURORA_MAPA),
        "mapa_sha256": AURORA_MAPA_SHA256,
        "res": RES,
        "min_x": round(float(d.min_x), 4),
        "min_y": round(float(d.min_y), 4),
        "max_y": round(float(d.min_y + info.cell_height * RES), 4),
        "largura_px": int(info.cell_width),
        "altura_px": int(info.cell_height),
        "eixo_paredes_deg": ang,
        "paredes": [{"eixo_deg": ang, "posicoes_m": picos(ocup, ang, RES)},
                    {"eixo_deg": ang + 90, "posicoes_m": picos(ocup, ang + 90, RES)}],
        "gerada_em": time.strftime("%Y-%m-%d %H:%M:%S"),
    }
    with open(base + "_planta.json", "w", encoding="utf-8") as f:
        json.dump(meta, f, indent=2, ensure_ascii=False)
    print(f"planta: {info.cell_width} × {info.cell_height} px "
          f"({info.cell_width * RES:.2f} × {info.cell_height * RES:.2f} m), "
          f"{len(ocup)} células ocupadas, paredes a {ang:.1f}°")
    for p in meta["paredes"]:
        print(f"  eixo {p['eixo_deg']:.1f}°: paredes em {p['posicoes_m']}")
    print(f"gravado: {base}_planta.png e .json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
