#!/usr/bin/env python3
"""
scripts/bancada_velocidade.py
Quanto o robô ANDA com cada força — a curva força × velocidade (09/11/2026).

Por quê: o piso de 8% e o "chute" do piloto de velocidade vêm do robô de
22/09 (8% = 8,8 cm/s, 12% = 21,7 cm/s). Com os rodízios de 75 mm, as missões
de 09/11 chegaram a 20–27 cm/s a 8–10%: o robô ficou mais solto, e a
aproximação (9 cm/s) esbarra no piso de 8%. Sem a curva medida, qualquer piso
novo é chute. Cada robô tem a sua: isto vira um passo do teste de aceitação.

COMO: para cada força de --forcas, anda --tempo s PARA A FRENTE, para,
espera, e volta --tempo s DE RÉ com a mesma força (o robô fica no mesmo ~1 m;
a ré passa pelo caminho que ele acabou de fazer). A velocidade é a do Aurora
(posição) e a dos Hall, só no fim de cada reta (--regime s), quando já
embalou. Sem correção de rumo: 2 s de reta não precisam dela.

SEGURANÇA: só com os serviços parados (o serviço é o único cliente do Aurora);
força de 3% ao teto da missão; reta ≤ 2 s; bumper do C1 fail-closed na ida
(frente bloqueada → não sai ou para na hora); SIGINT/SIGTERM param; stop()
num finally.

ANTES:  sudo systemctl stop frota-rosto frota-robo   (e conferir os dois)
USO:    .venv/bin/python scripts/bancada_velocidade.py
        .venv/bin/python scripts/bancada_velocidade.py --forcas 5 6 7 8 --tempo 2
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

PASTA = os.path.join(_RAIZ, "data", "velocidade")
TEMPO_MAXIMO_RETA_S = 2.0
FORCA_MINIMA_PCT = 3.0
_motors = None


def _parar_tudo(*_):
    if _motors is not None:
        try:
            _motors.stop()
        except Exception:
            pass
    sys.exit(1)


# ─────────────────────────────────────────
# ANÁLISE (pura — sem hardware)
# ─────────────────────────────────────────
def velocidade_aurora(poses, t0, t1):
    """m/s entre a 1ª e a última pose em [t0, t1]; None com menos de 2."""
    p = [q for q in poses if t0 <= q[0] <= t1]
    if len(p) < 2 or p[-1][0] - p[0][0] < 0.2:
        return None
    return math.hypot(p[-1][1] - p[0][1], p[-1][2] - p[0][2]) / (p[-1][0] - p[0][0])


def velocidade_hall(ticks, t0, t1, circ_m, ticks_volta):
    """(esq, dir) em m/s pelos contadores em [t0, t1]; None sem amostras."""
    s = [q for q in ticks if t0 <= q[0] <= t1]
    if len(s) < 2 or s[-1][0] - s[0][0] < 0.2:
        return None
    dt = s[-1][0] - s[0][0]
    k = circ_m / ticks_volta / dt
    return (s[-1][1] - s[0][1]) * k, (s[-1][2] - s[0][2]) * k


# ─────────────────────────────────────────
# BANCADA
# ─────────────────────────────────────────
class Coleta:
    def __init__(self, sdk, motors):
        self.sdk, self.motors = sdk, motors
        self.poses = []          # (t, x, y)
        self.ticks = []          # (t, esq, dir)
        self._ult_ts = None

    def amostra(self):
        agora = time.monotonic()
        try:
            pos, _, ts = self.sdk.data_provider.get_current_pose(use_se3=False)
            if ts != self._ult_ts:
                self._ult_ts = ts
                self.poses.append((agora, pos[0], pos[1]))
        except Exception:
            pass
        self.ticks.append((agora, self.motors.left_ticks_odo, self.motors.right_ticks_odo))

    def esperar(self, s):
        fim = time.monotonic() + s
        while time.monotonic() < fim:
            self.amostra()
            time.sleep(0.02)


def reta(col, motors, bumper, pct, tempo, de_re):
    """Anda uma reta; devolve (t_partida, t_parada, motivo)."""
    sinal = -1.0 if de_re else 1.0
    t0 = time.monotonic()
    motivo = "tempo"
    while time.monotonic() - t0 < tempo:
        if not de_re and bumper.blocked_front:
            motivo = "bumper"
            break
        motors.set_speed(sinal * pct, sinal * pct)
        col.amostra()
        time.sleep(0.02)
    motors.stop()
    return t0, time.monotonic(), motivo


def main() -> int:
    global _motors
    from config.settings import (AURORA_IP, MISSAO_TETO_PCT, ROBOT_WHEEL_CIRCUMFERENCE_M,
                                 TICKS_PER_REVOLUTION)
    from sensors.aurora_cliente_unico import exigir_servico_parado

    ap = argparse.ArgumentParser(description="Curva força × velocidade do robô.")
    ap.add_argument("--forcas", type=float, nargs="+", default=[4, 5, 6, 7, 8, 10])
    ap.add_argument("--tempo", type=float, default=2.0, help="s de cada reta")
    ap.add_argument("--regime", type=float, default=0.8, help="s finais de cada reta que contam")
    ap.add_argument("--espera", type=float, default=5.0, help="s antes da 1ª reta (saia da frente)")
    a = ap.parse_args()

    if os.system("systemctl is-active --quiet frota-rosto") == 0:
        print("RECUSADO: pare os serviços antes (o rosto religa o frota-robo):\n"
              "  sudo systemctl stop frota-rosto frota-robo")
        return 2
    exigir_servico_parado()
    if not all(FORCA_MINIMA_PCT <= f <= MISSAO_TETO_PCT for f in a.forcas):
        print(f"RECUSADO: forças entre {FORCA_MINIMA_PCT} e {MISSAO_TETO_PCT}%.")
        return 2
    if not (0.5 <= a.tempo <= TEMPO_MAXIMO_RETA_S) or not (0.3 <= a.regime < a.tempo):
        print(f"RECUSADO: --tempo entre 0,5 e {TEMPO_MAXIMO_RETA_S} s; --regime menor que --tempo.")
        return 2

    signal.signal(signal.SIGINT, _parar_tudo)
    signal.signal(signal.SIGTERM, _parar_tudo)

    from slamtec_aurora_sdk import AuroraSDK
    from core.motor_driver import MotorDriver
    from sensors.safety_bumper import SafetyBumper
    sdk = AuroraSDK()
    sdk.connect(connection_string=AURORA_IP)
    time.sleep(1.0)                                # o 1º segundo traz (0,0,0) e saltos
    bumper = SafetyBumper()
    bumper.start()
    _motors = motors = MotorDriver()
    col = Coleta(sdk, motors)
    linhas = []
    try:
        print(f"Saia da frente: {a.espera:.0f} s. Ida e volta em cada força: {a.forcas}.")
        col.esperar(a.espera)
        for pct in a.forcas:
            for de_re in (False, True):
                if not de_re and bumper.blocked_front:
                    print("  frente BLOQUEADA (ou C1 sem dado) — parei a bancada.")
                    raise SystemExit(1)
                t0, t1, motivo = reta(col, motors, bumper, pct, a.tempo, de_re)
                col.esperar(1.5)
                va = velocidade_aurora(col.poses, t1 - a.regime, t1)
                vh = velocidade_hall(col.ticks, t1 - a.regime, t1,
                                     ROBOT_WHEEL_CIRCUMFERENCE_M, TICKS_PER_REVOLUTION)
                sentido = "ré" if de_re else "frente"
                linhas.append([pct, sentido, motivo, va, *(vh or (None, None))])
                txt_a = "—" if va is None else f"{va * 100:5.1f}"
                txt_h = "—" if vh is None else f"{vh[0] * 100:5.1f} / {vh[1] * 100:5.1f}"
                print(f"  {pct:4.1f}% {sentido:6s}: Aurora {txt_a} cm/s · Hall esq/dir {txt_h} cm/s"
                      + ("" if motivo == "tempo" else f" · parou por {motivo}"))
        os.makedirs(PASTA, exist_ok=True)
        arq = os.path.join(PASTA, f"velocidade_{time.strftime('%Y%m%d_%H%M%S')}.csv")
        with open(arq, "w", newline="") as fh:
            w = csv.writer(fh)
            w.writerow(["pct", "sentido", "motivo", "aurora_ms", "hall_esq_ms", "hall_dir_ms"])
            w.writerows(linhas)
        print(f"\ndados: {arq}")
        return 0
    finally:
        motors.stop()
        try:
            motors.cleanup()
        except Exception:
            pass
        bumper.stop()
        for fn in ("disconnect", "release"):
            try:
                getattr(sdk, fn)()
            except Exception:
                pass


if __name__ == "__main__":
    sys.exit(main())
