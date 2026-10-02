#!/usr/bin/env python3
"""
scripts/refazer_mapas_c1.py — 02/10/2026.

Refaz, a partir da coleta guardada no pacote (coleta/passada_N.jsonl), a
PLANTA e os mapas dos C1 de um ambiente, e atualiza a ficha. Para pacotes
feitos antes de a planta sair da coleta (ex.: Sala 2, mapeada em 02/10 às
17:00, quando o SDK caiu ao gerar a planta) ou depois de mudar o gerador.

Roda num processo à parte (o mesmo do serviço). Pode rodar com o serviço no
ar: não fala com o Aurora. Ambiente ATIVO: a planta nova só vale depois de
reiniciar o serviço.

Uso:  python3 scripts/refazer_mapas_c1.py <id do ambiente>
"""
import json
import os
import sys

_RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _RAIZ not in sys.path:
    sys.path.insert(0, _RAIZ)

import config.settings as S                                  # noqa: E402
from slam.ambientes import Ambientes                         # noqa: E402
from slam.mapa_c1 import gerar_mapas_em_processo             # noqa: E402


def main():
    if len(sys.argv) != 2:
        print(__doc__)
        return 2
    amb = Ambientes(S.AMBIENTES_DIR)
    c = amb.caminhos(sys.argv[1])
    if c is None or not os.path.isdir(os.path.join(c["pasta"], "coleta")):
        print(f"ambiente {sys.argv[1]!r} sem pasta de coleta")
        return 2
    r = gerar_mapas_em_processo(c["pasta"], braco_aurora=S.AURORA_BRACO_M)
    ficha = json.load(open(c["ficha"], encoding="utf-8"))
    ficha["c1"] = r
    tmp = c["ficha"] + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(ficha, f, indent=2, ensure_ascii=False)
    os.replace(tmp, c["ficha"])
    print(json.dumps(r, ensure_ascii=False, indent=1))
    a = amb.avaliar(sys.argv[1])
    print(f"estado: {a['estado']}" + (f" — {'; '.join(a['motivos'])}" if a["motivos"] else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
