#!/usr/bin/env python3
"""
scripts/bancada_freio.py
Como a roda PARA quando o comando dela cai a zero (29/10/2026).

Por quê: na bancada da curva (sala-lab-teste, 14h) a roda de dentro, mandada a
0%, seguiu girando 55–76% do que girou a de fora; o arco pedia 24%. No código,
um lado a |pct| < 1 em set_speed() fica LIVRE (driver desligado), não freado.
Antes de desenhar a roda de dentro por encoder, medir o que cada jeito de
"parar uma roda" rende na ZS-X11H, com o robô SUSPENSO (rodas no ar):

    livre  — PWM 0 e driver desligado (o que a curva fez)
    freio  — PWM 0 e driver ligado (frenagem elétrica)
    re10   — ré a 8% por 0,10 s, depois freio
    re20   — ré a 8% por 0,20 s, depois freio

Cada ensaio: as duas rodas a 9% por 2 s (mede a velocidade no último 1 s),
corta pelo modo e conta os pulsos por 1,5 s. Depois 9% de novo por 1 s, para
provar que o driver segue respondendo após a ré. O hall não dá o sentido:
quem diz se a roda INVERTEU é o olho de quem está do lado.

SEGURANÇA: só com o robô SUSPENSO e os serviços parados; força ≤ 9%;
SIGINT/SIGTERM param; stop() + cleanup() num finally.

ANTES:  sudo systemctl stop frota-rosto frota-robo
USO:    .venv/bin/python scripts/bancada_freio.py [--repeticoes 2]
DEPOIS: sudo systemctl start frota-robo frota-rosto   + "Localizar na fita"
"""

import argparse
import csv
import os
import signal
import sys
import time

_RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _RAIZ)

from sensors.aurora_cliente_unico import exigir_servico_parado  # noqa: E402

GIRA_PCT = 9.0
RE_PCT = 8.0
GIRA_S = 2.0
OBSERVA_S = 1.5
MODOS = ("livre", "freio", "re10", "re20")
PASTA = os.path.join(_RAIZ, "data", "bancada_freio")
_motors = None


def _parar_tudo(*_):
    if _motors is not None:
        try:
            _motors.stop()
        except Exception:
            pass
    sys.exit(1)


def _pulsos(m):
    with m._lock:
        return m.left_ticks_odo, m.right_ticks_odo


def _amostrar(m, dur, linhas, fase, modo, rep, t0):
    fim = time.monotonic() + dur
    while time.monotonic() < fim:
        e, d = _pulsos(m)
        linhas.append((modo, rep, fase, round(time.monotonic() - t0, 3), e, d))
        time.sleep(0.01)


def _ensaio(m, modo, rep, linhas):
    t0 = time.monotonic()
    m.set_speed(GIRA_PCT, GIRA_PCT)
    _amostrar(m, GIRA_S - 1.0, linhas, "gira", modo, rep, t0)
    e0, d0 = _pulsos(m)
    _amostrar(m, 1.0, linhas, "gira", modo, rep, t0)
    e1, d1 = _pulsos(m)
    if modo == "livre":
        m.set_brake(False)
    elif modo == "freio":
        m.set_brake(True)
    else:
        m.set_speed(-RE_PCT, -RE_PCT)
        _amostrar(m, 0.10 if modo == "re10" else 0.20, linhas, "re", modo, rep, t0)
        m.set_brake(True)
    t_corte = time.monotonic() - t0
    _amostrar(m, OBSERVA_S, linhas, "corte", modo, rep, t0)
    e2, d2 = _pulsos(m)
    ultimo = {"e": t_corte, "d": t_corte}
    ant = None
    for l in linhas:
        if l[0] != modo or l[1] != rep or l[3] < t_corte - 0.25:
            continue
        if ant is not None:
            if l[4] != ant[4]:
                ultimo["e"] = l[3]
            if l[5] != ant[5]:
                ultimo["d"] = l[3]
        ant = l
    # o driver ainda responde depois do corte?
    m.set_speed(GIRA_PCT, GIRA_PCT)
    _amostrar(m, 1.0, linhas, "volta", modo, rep, t0)
    e3, d3 = _pulsos(m)
    m.set_brake(True)
    time.sleep(1.0)
    return {"modo": modo, "rep": rep,
            "vel_e": e1 - e0, "vel_d": d1 - d0,
            "apos_e": e2 - e1, "apos_d": d2 - d1,
            "para_e_s": round(ultimo["e"] - t_corte, 2), "para_d_s": round(ultimo["d"] - t_corte, 2),
            "volta_e": e3 - e2, "volta_d": d3 - d2}


def main():
    global _motors
    ap = argparse.ArgumentParser()
    ap.add_argument("--repeticoes", type=int, default=2)
    args = ap.parse_args()
    exigir_servico_parado()
    signal.signal(signal.SIGINT, _parar_tudo)
    signal.signal(signal.SIGTERM, _parar_tudo)
    from core.motor_driver import MotorDriver
    _motors = m = MotorDriver()
    linhas, res = [], []
    try:
        time.sleep(0.5)
        for rep in range(1, args.repeticoes + 1):
            for modo in MODOS:
                r = _ensaio(m, modo, rep, linhas)
                res.append(r)
                print(f"{modo:<6} #{rep}  a 9%: E {r['vel_e']:>3} D {r['vel_d']:>3} pulsos/s · "
                      f"depois do corte: E {r['apos_e']:>3} D {r['apos_d']:>3} pulsos "
                      f"(último em {r['para_e_s']:.2f}/{r['para_d_s']:.2f} s) · "
                      f"9% de novo: E {r['volta_e']:>3} D {r['volta_d']:>3}", flush=True)
    finally:
        m.stop()
        m.cleanup()
        os.makedirs(PASTA, exist_ok=True)
        nome = os.path.join(PASTA, time.strftime("freio_%Y%m%d_%H%M%S.csv"))
        with open(nome, "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(("modo", "rep", "fase", "t_s", "pulsos_e", "pulsos_d"))
            w.writerows(linhas)
        print("traço:", nome)


if __name__ == "__main__":
    main()
