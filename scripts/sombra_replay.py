#!/usr/bin/env python3
"""
scripts/sombra_replay.py — 02/10/2026.

Roda o LOCALIZADOR C1 (slam/sombra.py) sobre varreduras GRAVADAS, como se fosse
ao vivo, e compara com a pose do Aurora gravada junto. Mede o que o modo
sombra vai medir no robô: erro varredura após varredura e quantas vezes se
perde. Use dados que NÃO montaram o mapa (senão a medida fica otimista).

Uso (no PC ou na Pi):
  py scripts/sombra_replay.py <pasta do pacote> <HH.jsonl> [...] [--busca 0.35]

O gravador guarda 1 varredura por segundo; ao vivo serão ~10. Com 1 s entre
varreduras o robô anda até ~25 cm: por isso a busca padrão aqui é maior
(0,35 m) que a do serviço (0,15 m). É o caso mais difícil.
"""
import json
import math
import sys
import time

import numpy as np

sys.path.insert(0, __file__.rsplit("scripts", 1)[0])
from slam.sombra import Rastreador, carregar_grade      # noqa: E402

args = [a for a in sys.argv[1:] if not a.startswith("--")]
busca = float(sys.argv[sys.argv.index("--busca") + 1]) if "--busca" in sys.argv else 0.35
if "--busca" in sys.argv:
    args.remove(sys.argv[sys.argv.index("--busca") + 1])
pac, arqs = args[0], args[1:]
g22 = carregar_grade(pac + "/c1_22")
rs = Rastreador(g22, busca_m=busca)

regs = []
for f in arqs:
    for linha in open(f, encoding="utf-8"):
        try:
            j = json.loads(linha)
        except ValueError:
            continue
        if j.get("p"):
            regs.append(j)
regs.sort(key=lambda j: j["t"])
print(f"{len(regs)} varreduras ({time.strftime('%H:%M', time.localtime(regs[0]['t']))}–"
      f"{time.strftime('%H:%M', time.localtime(regs[-1]['t']))}); busca ±{busca:.2f} m")

erros, sem_ref, reseeds, t0 = [], 0, 0, time.monotonic()
ult_t = None
for j in regs:
    ref = j.get("pose")
    if ult_t is not None and j["t"] - ult_t > 5:      # buraco na gravação: sem ritmo
        rs.pose = None
    ult_t = j["t"]
    if rs.pose is None or rs.perdido:
        if ref:                                       # semeia/recoloca na pose do Aurora
            if rs.pose is not None:
                reseeds += 1
            rs.semear(ref[0] / 100, ref[1] / 100, ref[2], j.get("yaw"))
        continue
    p = np.array(j["p"], float)
    x, y, r, enc, perdido = rs.passo(p[:, 0] / 100.0, p[:, 1] / 1000.0, j.get("yaw"))
    if ref is None:
        sem_ref += 1
        continue
    if not perdido:
        erros.append((math.hypot(x - ref[0] / 100, y - ref[1] / 100) * 100,
                      abs(((r - ref[2]) + 180) % 360 - 180), bool(j.get("mov"))))
dur = time.monotonic() - t0
e = np.array([a for a, _, _ in erros])
er = np.array([b for _, b, _ in erros])
em = np.array([a for a, _, m in erros if m])
print(f"varreduras acompanhadas: {len(e)} | perdas: {rs.perdas} | recolocações: {reseeds}"
      f" | sem pose do Aurora para comparar: {sem_ref}")
print(f"erro (cm): mediana {np.median(e):.1f}  p90 {np.percentile(e, 90):.1f}  "
      f"máx {e.max():.1f}  >30 cm: {(e > 30).sum()}")
if len(em):
    print(f"  andando: mediana {np.median(em):.1f}  p90 {np.percentile(em, 90):.1f}  (n={len(em)})")
print(f"rumo (°): mediana {np.median(er):.1f}  p90 {np.percentile(er, 90):.1f}")
print(f"tempo por varredura: {dur / max(1, len(regs)) * 1000:.0f} ms")
