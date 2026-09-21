"""
Reconstroi, em coordenadas cartesianas, a superficie fixa vista pelo LIDAR
atras do sensor, e ajusta uma reta a ela.

Se a face da coluna frontal e' perpendicular ao eixo do robo, a NORMAL dessa
reta aponta para 180 graus exatos no referencial do LIDAR quando o sensor
esta alinhado. Qualquer desvio e' a rotacao de montagem do sensor.

Referencial: x = direita, y = frente. angulo 0 = frente, horario.
"""
import math
import os
import statistics
import sys
import time

sys.path.insert(0, os.path.expanduser("~/robo_slam_v2"))

from sensors.safety_bumper import _C1Lidar
from config.settings import LIDAR_BAUDRATE

N = int(sys.argv[1]) if len(sys.argv) > 1 else 300

bins = [[] for _ in range(360)]
total = 0
lidar = _C1Lidar("/dev/ttyUSB0", baudrate=LIDAR_BAUDRATE)
try:
    lidar.stop(); lidar.clean_input()
    for scan in lidar.iter_scans(max_buf_meas=5000):
        for _, ang, dmm in scan:
            if dmm > 0:
                bins[int(round(ang)) % 360].append(dmm / 10.0)
        total += 1
        if total >= N:
            break
finally:
    try: lidar.stop(); lidar.stop_motor(); lidar.disconnect()
    except Exception: pass

print("varreduras: %d" % total)

# superficie fixa: graus com mediana < 15 cm e presenca solida
sup = []
for g in range(120, 240):
    i = g % 360
    if len(bins[i]) >= 0.6 * total:
        m = statistics.median(bins[i])
        if m < 15:
            th = math.radians(g)
            sup.append((g, m, m * math.sin(th), m * math.cos(th)))

g0, g1 = sup[0][0], sup[-1][0]
print("superficie fixa: %d a %d graus (%d graus)" % (g0, g1, g1 - g0 + 1))
print()
print("%6s %9s %9s %9s" % ("grau", "dist", "x(cm)", "y(cm)"))
for g, d, x, y in sup:
    if g % 4 == 0 or g in (g0, g1):
        print("%6d %8.2f %9.2f %9.2f" % (g, d, x, y))

ys = [p[3] for p in sup]
print()
print("y varia de %.2f a %.2f cm  (uma face PLANA perpendicular ao eixo daria y constante)"
      % (min(ys), max(ys)))

# protuberancia = pontos bem mais proximos que a mediana das bordas
ymed = statistics.median(ys)
prot = [p for p in sup if p[3] > ymed + 0.30]      # y menos negativo = mais perto
if prot:
    print("protuberancia (mais proxima que a face) em %d a %d graus, ate %.2f cm mais perto"
          % (prot[0][0], prot[-1][0], max(p[3] for p in prot) - ymed))

# ---- ajuste da reta somente na face plana (excluindo a protuberancia)
face = [p for p in sup if p[3] <= ymed + 0.30]
n = len(face)
sx = sum(p[2] for p in face); sy = sum(p[3] for p in face)
mx, my = sx / n, sy / n
sxx = sum((p[2] - mx) ** 2 for p in face)
sxy = sum((p[2] - mx) * (p[3] - my) for p in face)
syy = sum((p[3] - my) ** 2 for p in face)
# direcao principal da reta (autovetor do maior autovalor)
theta = 0.5 * math.atan2(2 * sxy, sxx - syy)
dirx, diry = math.cos(theta), math.sin(theta)
# normal = perpendicular; escolhe a que aponta do sensor para a face (y negativo)
nx, ny = -diry, dirx
if ny > 0:
    nx, ny = -nx, -ny
bearing = math.degrees(math.atan2(nx, ny)) % 360
resid = [abs((p[2] - mx) * nx + (p[3] - my) * ny) for p in face]
import statistics as _st
_sr = _st.pstdev(resid) if len(resid) > 1 else 0.0
_sx = _st.pstdev([p[2] for p in face])
_sig = math.degrees(_sr / (_sx * math.sqrt(len(face)))) if _sx > 0 else float("nan")

print()
print("=" * 62)
print("AJUSTE DA FACE PLANA  (%d pontos, protuberancia excluida)" % n)
print("=" * 62)
print("normal da face aponta para: %.1f graus" % bearing)
print("desvio em relacao aos 180 graus esperados: %+.1f graus" % (bearing - 180))
print("distancia da face ao sensor: %.2f cm" % abs(my * ny + mx * nx))
print("residuo PERPENDICULAR medio: %.3f cm (desvio padrao %.3f cm)" % (sum(resid)/len(resid), _sr))
print("incerteza do angulo da normal: +-%.1f graus" % _sig)
print()
xs = [p[2] for p in face]
print("largura vista da coluna: %.2f cm   (desenho: 4,73 cm)" % (max(xs) - min(xs)))
print("centro lateral da coluna: %+.2f cm em relacao ao eixo do sensor" % ((max(xs) + min(xs)) / 2))
