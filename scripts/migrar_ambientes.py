#!/usr/bin/env python3
"""
scripts/migrar_ambientes.py — 02/10/2026 (pacote de ambiente, Etapa A).

Cria data/ambientes/ a partir dos arquivos de hoje, uma vez, na Pi:
  - sala_lab_20260925 ← o mapa, a planta, as áreas/POIs (com histórico) e a
    fita do config/settings.py. Fica PRONTO e ATIVO.
  - corredor_20261001 ← o mapa e a planta do corredor (01/10). Fica RASCUNHO:
    falta medir a fita (e desenhar áreas/POIs).

Só COPIA: os arquivos antigos ficam onde estão. Pacote que já existe não é
tocado, então rodar de novo não muda nada. Recusa mapa cujo sha não confere.

O serviço só passa a usar os pacotes quando REINICIAR (sudo systemctl restart
frota-robo). Depois: "Localizar na fita" e uma missão base → POI → base para
provar que a sala ficou igual.

Uso:  python3 scripts/migrar_ambientes.py [--simular]
"""
import argparse
import os
import sys

_RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _RAIZ not in sys.path:
    sys.path.insert(0, _RAIZ)

import config.settings as S                       # noqa: E402
from slam.ambientes import Ambientes, migrar      # noqa: E402

CORREDOR = {
    "id": "corredor_20261001", "nome": "Corredor",
    "mapa": os.path.join(S.DATA_DIR, "aurora", "mapas", "corredor_20261001.stcm"),
    "mapa_sha256": "935f630d7929aa805c6b8733bd6b3351c3a3b1df46a1798bdde45f3efe159b9c",
    "planta_json": os.path.join(S.DATA_DIR, "aurora", "mapas", "corredor_20261001_planta.json"),
    "nav_dir": None, "fita": None,
}


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    ap.add_argument("--simular", action="store_true", help="só mostra o que faria")
    args = ap.parse_args()

    sala = {"id": "sala_lab_20260925", "nome": "Sala do lab",
            "mapa": S.AURORA_MAPA, "mapa_sha256": S.AURORA_MAPA_SHA256,
            "planta_json": S.AURORA_PLANTA_JSON, "nav_dir": S.NAV_DIR,
            "fita": S.AURORA_FITA}
    extras = [CORREDOR] if os.path.isfile(CORREDOR["mapa"]) else []
    if not extras:
        print(f"(corredor não encontrado em {CORREDOR['mapa']} — fica de fora)")

    print(f"destino: {S.AMBIENTES_DIR}")
    for it in [sala, *extras]:
        print(f"  {it['id']}: mapa {it['mapa']} ({it['mapa_sha256'][:8]}), "
              f"planta {'sim' if it['planta_json'] and os.path.isfile(it['planta_json']) else 'não'}, "
              f"áreas {'sim' if it['nav_dir'] and os.path.isdir(it['nav_dir']) else 'não'}, "
              f"fita {'sim' if it['fita'] else 'não'}")
    if args.simular:
        print("--simular: nada foi gravado.")
        return 0
    try:
        for linha in migrar(S.AMBIENTES_DIR, sala, extras):
            print("  " + linha)
    except ValueError as e:
        print(f"RECUSADO: {e}")
        return 2
    print("\nresultado:")
    for p in Ambientes(S.AMBIENTES_DIR).listar():
        print(f"  {'*' if p['ativo'] else ' '} {p['id']}: {p['estado']}"
              + (f" — {'; '.join(p['motivos'])}" if p["motivos"] else ""))
    print("\nO serviço passa a usar os pacotes depois de: sudo systemctl restart frota-robo")
    return 0


if __name__ == "__main__":
    sys.exit(main())
