"""
Perfil angular de 360 graus do RPLIDAR C1 montado no robo.

Acumula varreduras e, para cada grau, calcula:
  - taxa de retorno (em quantas varreduras aquele grau devolveu algo valido)
  - mediana e minimo da distancia

Objetivo: separar o que e' estrutura FIXA do robo (retorno em quase 100% das
varreduras, sempre na mesma distancia) do que e' ambiente, e medir a extensao
real da sombra projetada pela coluna frontal.
"""
import os
import statistics
import sys
import time

sys.path.insert(0, os.path.expanduser("~/robo_slam_v2"))

from sensors.safety_bumper import _C1Lidar
from config.settings import LIDAR_BAUDRATE

N_VARREDURAS = int(sys.argv[1]) if len(sys.argv) > 1 else 200

bins = [[] for _ in range(360)]
total = 0

lidar = _C1Lidar("/dev/ttyUSB0", baudrate=LIDAR_BAUDRATE)
try:
    lidar.stop()
    lidar.clean_input()
    t0 = time.perf_counter()
    for scan in lidar.iter_scans(max_buf_meas=5000):
        for _, ang, dist_mm in scan:
            if dist_mm <= 0:
                continue
            bins[int(round(ang)) % 360].append(dist_mm / 10.0)   # cm
        total += 1
        if total >= N_VARREDURAS:
            break
    dur = time.perf_counter() - t0
finally:
    try:
        lidar.stop()
        lidar.stop_motor()
        lidar.disconnect()
    except Exception:
        pass

print("varreduras: %d em %.1fs (%.1f Hz)" % (total, dur, total / dur))
print("pontos validos: %d" % sum(len(v) for v in bins))
print()

def taxa(i):
    return 100.0 * len(bins[i]) / total

def med(i):
    return statistics.median(bins[i]) if bins[i] else None

# ---------------------------------------------------------------- panorama
print("=" * 70)
print("PANORAMA — setores de 10 graus (0 = frente do robo)")
print("=" * 70)
print("%-12s %8s %10s %10s   %s" % ("setor", "retorno", "mediana", "minimo", "barra"))
for s in range(0, 360, 10):
    idx = [(s + k) % 360 for k in range(10)]
    pts = [d for i in idx for d in bins[i]]
    tx = 100.0 * sum(len(bins[i]) for i in idx) / (total * 10)
    if pts:
        m = statistics.median(pts)
        mn = min(pts)
        barra = "#" * int(round(tx / 5))
        print("%3d-%3d graus %7.1f%% %8.1f cm %8.1f cm   %s"
              % (s, s + 9, tx, m, mn, barra))
    else:
        print("%3d-%3d graus %7.1f%% %11s %11s   %s"
              % (s, s + 9, tx, "-", "-", "<< SEM RETORNO"))

# ---------------------------------------------------------------- estrutura
print()
print("=" * 70)
print("ESTRUTURA FIXA — graus com retorno em >80%% das varreduras e < 15 cm")
print("=" * 70)
fixos = [i for i in range(360) if taxa(i) > 80 and med(i) is not None and med(i) < 15]
if fixos:
    print("graus:", ", ".join(str(i) for i in fixos))
    print("faixa: %d a %d graus (%d graus de largura)"
          % (min(fixos), max(fixos), max(fixos) - min(fixos) + 1))
    ds = [med(i) for i in fixos]
    print("distancia: %.1f a %.1f cm" % (min(ds), max(ds)))
else:
    print("nenhum")

# ---------------------------------------------------------------- sombra
print()
print("=" * 70)
print("SOMBRA — graus com retorno em menos de 20%% das varreduras")
print("=" * 70)
mudos = [i for i in range(360) if taxa(i) < 20]
if mudos:
    faixas, ini, ant = [], mudos[0], mudos[0]
    for i in mudos[1:]:
        if i == ant + 1:
            ant = i
        else:
            faixas.append((ini, ant)); ini = ant = i
    faixas.append((ini, ant))
    for a, b in faixas:
        print("  %3d a %3d graus  (%d graus)" % (a, b, b - a + 1))
else:
    print("nenhum — todos os graus devolvem dado")

# ---------------------------------------------------------------- traseira
print()
print("=" * 70)
print("DETALHE DA TRASEIRA — 140 a 220 graus, grau a grau")
print("=" * 70)
print("%6s %9s %10s %10s" % ("grau", "retorno", "mediana", "minimo"))
for k in range(140, 221):
    i = k % 360
    if bins[i]:
        print("%5d  %7.1f%% %8.1f cm %8.1f cm"
              % (k, taxa(i), med(i), min(bins[i])))
    else:
        print("%5d  %7.1f%% %11s %11s" % (k, taxa(i), "-", "-"))

# ---------------------------------------------------------------- frontal
print()
print("=" * 70)
print("ARCO DO BUMPER — 330 a 30 graus (o que a seguranca vigia)")
print("=" * 70)
arco = [(k % 360) for k in range(330, 391)]
pts = [d for i in arco for d in bins[i]]
print("menor distancia observada no arco: %.1f cm" % (min(pts) if pts else -1))
print("mediana no arco: %.1f cm" % (statistics.median(pts) if pts else -1))
perto = [i for i in arco if med(i) is not None and med(i) < 50]
print("graus do arco com mediana < 50 cm (limiar de bloqueio): %s"
      % (", ".join(str(i) for i in perto) if perto else "NENHUM — arco limpo"))
