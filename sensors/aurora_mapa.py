"""
sensors/aurora_mapa.py
A PLANTA do mapa carregado no Aurora: a imagem sobre a qual o operador desenha
áreas e POIs, com a origem e a escala no .json ao lado.

Saiu do scripts/aurora_planta.py em 02/10/2026 para o serviço gerar a planta
sozinho no fim da passada 1 do mapeamento pelo painel (Etapa B). As chamadas do
SDK são as mesmas provadas em 28/09 (onde_na_sala.py) e medidas na bancada de
02/10: sincronizar 0,5 s, gerar a grade 0,1 s (5 cm).

Com l2p_mapping=True o OCUPADO vem ESCURO (valor baixo), não 255.
Conversão (a mesma no servidor e no navegador):
  x = min_x + (coluna + 0,5) · res
  y = max_y − (linha  + 0,5) · res
Só lê o Aurora: não zera, não carrega, não relocaliza.
"""

import json
import math
import time

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


def gerar_planta(sdk, destino_base: str, mapa_sha256: str, nome_mapa: str,
                 res: float = RES) -> dict:
    """
    Gera <destino_base>.png e .json a partir do mapa ATUAL do Aurora, com o
    sha do mapa a que a planta pertence. Devolve os metadados.
    """
    import numpy as np
    from PIL import Image
    from slamtec_aurora_sdk.data_types import GridMapGenerationOptions, Rect
    from slamtec_aurora_sdk.utils import wait_for_map_data

    sdk.enable_map_data_syncing(True)
    try:
        wait_for_map_data(sdk.data_provider, min_keyframes=10,
                          min_sync_ratio=0.8, max_wait_time=30.0)
        o = GridMapGenerationOptions()
        o.resolution = res
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
        cells, info = gm.read_cell_data(rect, resolution=res, l2p_mapping=True)
        g = np.array(cells, dtype=np.uint8).reshape(info.cell_height, info.cell_width)
    finally:
        try:
            sdk.enable_map_data_syncing(False)
        except Exception:
            pass

    # Linha 0 da grade = min_y. Na imagem, o topo é +y: inverte as linhas.
    Image.fromarray(np.flipud(g), mode="L").save(destino_base + ".png", optimize=True)
    i, j = np.nonzero(g < 80)
    ocup = np.stack([d.min_x + (j + .5) * res, d.min_y + (i + .5) * res], 1)
    ang = eixo_das_paredes(ocup, res) if len(ocup) else 0.0
    meta = {
        "mapa": nome_mapa,
        "mapa_sha256": mapa_sha256,
        "res": res,
        "min_x": round(float(d.min_x), 4),
        "min_y": round(float(d.min_y), 4),
        "max_y": round(float(d.min_y + info.cell_height * res), 4),
        "largura_px": int(info.cell_width),
        "altura_px": int(info.cell_height),
        "eixo_paredes_deg": ang,
        "paredes": ([{"eixo_deg": ang, "posicoes_m": picos(ocup, ang, res)},
                     {"eixo_deg": ang + 90, "posicoes_m": picos(ocup, ang + 90, res)}]
                    if len(ocup) else []),
        "ocupadas": int(len(ocup)),
        "gerada_em": time.strftime("%Y-%m-%d %H:%M:%S"),
    }
    with open(destino_base + ".json", "w", encoding="utf-8") as f:
        json.dump(meta, f, indent=2, ensure_ascii=False)
    return meta
