#!/usr/bin/env python3
"""
scripts/bancada_pivo.py
Onde o Aurora fica em relação ao EIXO DE GIRO do robô (30/09/2026).

Por quê: a volta à base de 29/09 parou 11 cm antes e 12 à direita na trena,
depois do giro final. Um giro no joystick em 30/09 mostrou o Aurora ~5 cm atrás
e 4–6 cm à esquerda do eixo, mas com o gravador a 1 amostra/s e o robô
escorregando 10–15 cm/min. A trena diz: 4 cm atrás do eixo das rodas, centrado.
Este script separa as hipóteses com um giro PURO (rodas em sentidos opostos,
como a missão) lendo o Aurora a ~10 Hz, uma volta para cada lado.

O ajuste, com o rumo que o próprio Aurora dá em cada amostra:
    x = cx + vx·t + f·cosθ − l·sinθ
    y = cy + vy·t + f·sinθ + l·cosθ
f = braço para a FRENTE, l = para a ESQUERDA (o rumo do Aurora cresce à
esquerda). vx, vy absorvem um escorregar lento do eixo. Se (f, l) mudar entre
os dois sentidos, o que muda é o CENTRO de giro (uma roda rende mais que a
outra); se ficar igual, é onde o Aurora está.

SEGURANÇA: só com os serviços parados (o rosto religa o frota-robo, e o
serviço é o único cliente do Aurora); força entre 8% e o teto da missão;
duração máxima por volta; sem avanço de 5° em 3 s → para; SIGINT/SIGTERM
param; stop() num finally. O robô gira no lugar: ~40 cm livres em volta.

ANTES:  sudo systemctl stop frota-rosto frota-robo   (e conferir os dois)
USO:    .venv/bin/python scripts/bancada_pivo.py                 # esquerda e direita, 1 volta
        .venv/bin/python scripts/bancada_pivo.py --lado direita --voltas 2
DEPOIS: sudo systemctl start frota-robo frota-rosto   + "Localizar na fita"
"""

import argparse
import csv
import math
import os
import signal
import sys
import time

_RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _RAIZ)

from config.settings import AURORA_IP, MISSAO_TETO_PCT, MISSAO_GIRO_PCT  # noqa: E402
from sensors.aurora_cliente_unico import exigir_servico_parado           # noqa: E402

DURACAO_MAXIMA_POR_VOLTA = 40.0
PASTA = os.path.join(_RAIZ, "data", "aurora", "pivo")
_motors = None


def _parar_tudo(*_):
    if _motors is not None:
        try:
            _motors.stop()
        except Exception:
            pass
    sys.exit(1)


def norm(a):
    while a > 180.0:
        a -= 360.0
    while a <= -180.0:
        a += 360.0
    return a


def _resolve(A, b):
    n = len(b)
    M = [A[i][:] + [b[i]] for i in range(n)]
    for c in range(n):
        piv = max(range(c, n), key=lambda i: abs(M[i][c]))
        M[c], M[piv] = M[piv], M[c]
        for i in range(n):
            if i != c:
                f = M[i][c] / M[c][c]
                M[i] = [a - f * bb for a, bb in zip(M[i], M[c])]
    return [M[i][n] / M[i][i] for i in range(n)]


def ajusta_braco(amostras):
    """amostras: [(t, x_m, y_m, rumo_graus)]. Devolve dict em cm."""
    t0 = amostras[0][0]
    linhas, alvo = [], []
    for t, x, y, r in amostras:
        th = math.radians(r)
        c, s = math.cos(th), math.sin(th)
        dt = t - t0
        linhas.append([1, 0, dt, 0, c, -s]); alvo.append(x * 100)
        linhas.append([0, 1, 0, dt, s, c]); alvo.append(y * 100)
    AtA = [[sum(r[i] * r[j] for r in linhas) for j in range(6)] for i in range(6)]
    Atb = [sum(r[i] * v for r, v in zip(linhas, alvo)) for i in range(6)]
    cx, cy, vx, vy, f, l = _resolve(AtA, Atb)
    res = [sum(a * b for a, b in zip(r, (cx, cy, vx, vy, f, l))) - v
           for r, v in zip(linhas, alvo)]
    return {"frente_cm": f, "esquerda_cm": l, "braco_cm": math.hypot(f, l),
            "arrasto_cm_min": math.hypot(vx, vy) * 60,
            "residuo_cm": math.sqrt(sum(e * e for e in res) / len(res))}


def ler_pose(sdk):
    pos, rpy, ts = sdk.data_provider.get_current_pose(use_se3=False)
    return ts, pos[0], pos[1], math.degrees(rpy[2])


def uma_volta(motors, h, sdk, lado, voltas, pct, espera):
    sinal = 1.0 if lado == "direita" else -1.0      # BNO: direita aumenta
    alvo = 360.0 * voltas
    amostras, ult_ts = [], None

    def coleta():
        nonlocal ult_ts
        try:
            ts, x, y, r = ler_pose(sdk)
        except Exception:
            return
        if ts != ult_ts:
            ult_ts = ts
            amostras.append((time.monotonic(), x, y, r))

    print(f"\nGiro de {voltas} volta(s) à {lado.upper()} a {pct}%. Saia de perto: {espera:.0f} s.")
    fim = time.monotonic() + espera
    while time.monotonic() < fim:
        coleta()
        time.sleep(0.05)
    n_antes = len(amostras)

    acum, ant = 0.0, h.yaw_deg
    t0 = time.monotonic()
    janela_t, janela_v = t0, 0.0
    motivo = "completou"
    while True:
        agora = time.monotonic()
        y = h.yaw_deg
        acum += abs(norm(y - ant))
        ant = y
        if acum >= alvo:
            break
        if agora - t0 > DURACAO_MAXIMA_POR_VOLTA * voltas:
            motivo = "tempo máximo"
            break
        if not h.healthy:
            motivo = "BNO sem leitura"
            break
        if agora - janela_t >= 3.0:
            if acum - janela_v < 5.0:
                motivo = "sem avanço (5° em 3 s)"
                break
            janela_t, janela_v = agora, acum
        motors.set_speed(sinal * pct, -sinal * pct)
        coleta()
        time.sleep(0.02)
    motors.stop()
    dur = time.monotonic() - t0
    fim = time.monotonic() + 2.0                   # a inércia também é giro puro
    while time.monotonic() < fim:
        coleta()
        time.sleep(0.05)
    print(f"  {motivo}: {acum:.0f}° pelo BNO em {dur:.1f} s "
          f"({acum / dur if dur else 0:.1f} °/s); {len(amostras) - n_antes} poses do Aurora")
    return motivo, amostras


def main() -> int:
    global _motors
    ap = argparse.ArgumentParser(description="Braço do Aurora em relação ao eixo de giro.")
    ap.add_argument("--lado", choices=["esquerda", "direita", "ambos"], default="ambos")
    ap.add_argument("--voltas", type=float, default=1.0)
    ap.add_argument("--pct", type=float, default=MISSAO_GIRO_PCT)
    ap.add_argument("--espera", type=float, default=5.0)
    a = ap.parse_args()

    if os.system("systemctl is-active --quiet frota-rosto") == 0:
        print("RECUSADO: pare os serviços antes (o rosto religa o frota-robo):\n"
              "  sudo systemctl stop frota-rosto frota-robo")
        return 2
    exigir_servico_parado()
    if not (8.0 <= a.pct <= MISSAO_TETO_PCT):
        print(f"RECUSADO: força {a.pct}% fora de 8–{MISSAO_TETO_PCT}%.")
        return 2
    if not (0.5 <= a.voltas <= 2.0):
        print("RECUSADO: --voltas entre 0,5 e 2.")
        return 2

    signal.signal(signal.SIGINT, _parar_tudo)
    signal.signal(signal.SIGTERM, _parar_tudo)

    from slamtec_aurora_sdk import AuroraSDK
    from core.motor_driver import MotorDriver
    from sensors.heading_lock import HeadingLock

    sdk = AuroraSDK()
    sdk.connect(connection_string=AURORA_IP)
    time.sleep(1.0)                                # o 1º segundo traz (0,0,0) e saltos
    _motors = motors = MotorDriver()
    h = HeadingLock()
    h.start()
    os.makedirs(PASTA, exist_ok=True)
    carimbo = time.strftime("%Y%m%d_%H%M%S")
    resultados = {}
    try:
        for _ in range(50):
            if h.healthy:
                break
            time.sleep(0.2)
        if not h.healthy:
            print("BNO085 sem leitura — abortado, nada foi comandado.")
            return 1
        lados = ["esquerda", "direita"] if a.lado == "ambos" else [a.lado]
        for lado in lados:
            motivo, amostras = uma_volta(motors, h, sdk, lado, a.voltas, a.pct, a.espera)
            arq = os.path.join(PASTA, f"pivo_{carimbo}_{lado}.csv")
            with open(arq, "w", newline="") as fh:
                w = csv.writer(fh)
                w.writerow(["t_s", "x_m", "y_m", "rumo_graus"])
                w.writerows(amostras)
            if motivo != "completou" or len(amostras) < 30:
                print(f"  sem ajuste ({motivo}, {len(amostras)} poses). Dados em {arq}")
                continue
            resultados[lado] = r = ajusta_braco(amostras)
            print(f"  braço: {r['frente_cm']:+.1f} cm FRENTE, {r['esquerda_cm']:+.1f} cm "
                  f"ESQUERDA (|braço| {r['braco_cm']:.1f} cm) · arrasto "
                  f"{r['arrasto_cm_min']:.1f} cm/min · resíduo {r['residuo_cm']:.1f} cm")
            print(f"  dados: {arq}")
        if len(resultados) == 2:
            e, d = resultados["esquerda"], resultados["direita"]
            print(f"\nDIFERENÇA entre os sentidos: frente {e['frente_cm'] - d['frente_cm']:+.1f} cm, "
                  f"esquerda {e['esquerda_cm'] - d['esquerda_cm']:+.1f} cm")
            print(f"MÉDIA: {(e['frente_cm'] + d['frente_cm']) / 2:+.1f} cm FRENTE, "
                  f"{(e['esquerda_cm'] + d['esquerda_cm']) / 2:+.1f} cm ESQUERDA")
        return 0
    finally:
        motors.stop()
        h.stop()
        try:
            motors.cleanup()
        except Exception:
            pass
        for fn in ("disconnect", "release"):
            try:
                getattr(sdk, fn)()
            except Exception:
                pass


if __name__ == "__main__":
    sys.exit(main())
