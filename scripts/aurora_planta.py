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

Saída, DENTRO DO PACOTE DE AMBIENTE (02/10/2026; antes ia ao lado do mapa e
em 01/10 a planta do corredor foi gravada POR CIMA da planta da sala):
  data/ambientes/<id>/planta.png   — a grade, 1 pixel = RES m, topo = +y
  data/ambientes/<id>/planta.json  — origem, escala, sha do mapa e o eixo das paredes
  py scripts/aurora_planta.py --pacote corredor_20261001
Sem --pacote, usa o ambiente ATIVO. Planta já existente só é trocada com
--substituir. O mapa carregado no Aurora tem que ser o DESTE pacote.

Conversão (a mesma no servidor e no navegador):
  x = min_x + (coluna + 0,5) · res
  y = max_y − (linha  + 0,5) · res
"""

import argparse
import os
import sys
import time

_RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _RAIZ not in sys.path:
    sys.path.insert(0, _RAIZ)
from sensors.aurora_cliente_unico import exigir_servico_parado  # noqa: E402

from sensors.aurora_mapa import gerar_planta, RES  # noqa: E402


def main():
    from config.settings import AURORA_IP, AMBIENTES_DIR
    from slam.ambientes import Ambientes
    ap = argparse.ArgumentParser(description="Gera a planta do mapa carregado no Aurora.")
    ap.add_argument("--ip", default=AURORA_IP)
    ap.add_argument("--pacote", default=None,
                    help="id do ambiente (data/ambientes/<id>); sem ele, o ATIVO")
    ap.add_argument("--substituir", action="store_true",
                    help="troca uma planta que já existe no pacote")
    args = ap.parse_args()

    amb = Ambientes(AMBIENTES_DIR)
    pid = args.pacote or amb.id_ativo()
    c = amb.caminhos(pid) if pid else None
    if c is None or not os.path.isdir(c["pasta"]):
        print(f"ambiente {pid!r} não encontrado em {AMBIENTES_DIR}")
        return 2
    a = amb.avaliar(pid)
    if a["estado"] == "invalido":
        print(f"ambiente {pid} inválido: {'; '.join(a['motivos'])}")
        return 2
    destino = os.path.splitext(c["planta_json"])[0]           # .../<id>/planta
    if os.path.exists(c["planta_json"]) and not args.substituir:
        print(f"{c['planta_json']} já existe — use --substituir para trocar")
        return 2
    print(f"ambiente: {a['nome']} ({pid}), mapa {a['mapa_sha256'][:8]}")

    exigir_servico_parado()

    from slamtec_aurora_sdk import AuroraSDK

    sdk = AuroraSDK()
    sdk.connect(connection_string=args.ip)
    try:
        time.sleep(1.5)
        st, _ = sdk.data_provider.get_last_device_status()
        print(f"status do Aurora: {st} (13 = relocalizado no mapa)")
        meta = gerar_planta(sdk, destino, a["mapa_sha256"], f"{pid}/mapa.stcm", RES)
    finally:
        sdk.disconnect()

    print(f"planta: {meta['largura_px']} × {meta['altura_px']} px "
          f"({meta['largura_px'] * RES:.2f} × {meta['altura_px'] * RES:.2f} m), "
          f"{meta['ocupadas']} células ocupadas, paredes a {meta['eixo_paredes_deg']:.1f}°")
    for p in meta["paredes"]:
        print(f"  eixo {p['eixo_deg']:.1f}°: paredes em {p['posicoes_m']}")
    print(f"gravado: {destino}.png e .json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
