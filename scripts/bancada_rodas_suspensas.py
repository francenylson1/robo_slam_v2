#!/usr/bin/env python3
"""
scripts/bancada_rodas_suspensas.py
Cada roda de tração no ar, com força constante — a velocidade varia por volta? (10/11/2026)

Por quê: em 09/11, com força constante de 10%, o robô no chão caía de ~20 para
4–7 cm/s uma vez a cada ~50 cm (uma volta da roda). Se for algo raspando, roda
torta ou eixo frouxo, aparece também no ar: a velocidade de UMA roda cai num
ponto fixo da volta. Se no ar as duas giram lisas, a causa é no contato com o
chão (rodízio, pneu amassado, peso).

COMO: para cada força, esquerda sozinha, direita sozinha e as duas juntas, por
--tempo s, sempre PARA A FRENTE. Velocidade pelos Hall em janelas de --janela s.
Mostra média, mínima, máxima, desvio e a série (uma linha por janela).

SEGURANÇA: SÓ COM O ROBÔ SUSPENSO (rodas sem tocar em nada). Serviços parados.
Força de 3% ao teto da missão; SIGINT/SIGTERM param; stop() num finally.

ANTES:  sudo systemctl stop frota-rosto frota-robo
USO:    set -a; . /etc/frota.conf; set +a
        .venv/bin/python scripts/bancada_rodas_suspensas.py --forcas 10 12
DEPOIS: sudo systemctl start frota-robo frota-rosto   + "Localizar na fita"
"""

import argparse
import csv
import os
import signal
import statistics
import sys
import time

_RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _RAIZ)
PASTA = os.path.join(_RAIZ, "data", "velocidade")
_motors = None


def _parar_tudo(*_):
    if _motors is not None:
        try:
            _motors.stop()
        except Exception:
            pass
    sys.exit(1)


def serie(amostras, janela, k):
    """amostras (t, esq, dir) → lista de (t_rel, v_esq, v_dir) em m/s por janela."""
    out, i0 = [], 0
    t_ini = amostras[0][0]
    for i in range(1, len(amostras)):
        if amostras[i][0] - amostras[i0][0] >= janela:
            dt = amostras[i][0] - amostras[i0][0]
            out.append((amostras[i][0] - t_ini,
                        (amostras[i][1] - amostras[i0][1]) * k / dt,
                        (amostras[i][2] - amostras[i0][2]) * k / dt))
            i0 = i
    return out


def main() -> int:
    global _motors
    from config.settings import MISSAO_TETO_PCT, ROBOT_WHEEL_CIRCUMFERENCE_M, TICKS_PER_REVOLUTION

    ap = argparse.ArgumentParser(description="Rodas suspensas, força constante, uma por vez.")
    ap.add_argument("--forcas", type=float, nargs="+", default=[10, 12])
    ap.add_argument("--tempo", type=float, default=8.0)
    ap.add_argument("--janela", type=float, default=0.2)
    ap.add_argument("--embalo", type=float, default=1.5, help="s iniciais fora da estatística")
    a = ap.parse_args()

    if os.system("systemctl is-active --quiet frota-robo") == 0 or \
       os.system("systemctl is-active --quiet frota-rosto") == 0:
        print("RECUSADO: sudo systemctl stop frota-rosto frota-robo")
        return 2
    if not all(3 <= f <= MISSAO_TETO_PCT for f in a.forcas) or not (2 <= a.tempo <= 15):
        print(f"RECUSADO: forças 3..{MISSAO_TETO_PCT}%, tempo 2..15 s.")
        return 2

    signal.signal(signal.SIGINT, _parar_tudo)
    signal.signal(signal.SIGTERM, _parar_tudo)
    from core.motor_driver import MotorDriver
    _motors = m = MotorDriver()
    k = ROBOT_WHEEL_CIRCUMFERENCE_M / TICKS_PER_REVOLUTION
    linhas = []
    try:
        print("ROBÔ SUSPENSO? Começa em 3 s.")
        time.sleep(3)
        for pct in a.forcas:
            for nome, l, r in (("esquerda", pct, 0), ("direita", 0, pct), ("as duas", pct, pct)):
                am = []
                t0 = time.monotonic()
                while time.monotonic() - t0 < a.tempo:
                    m.set_speed(l, r)
                    am.append((time.monotonic(), m.left_ticks_odo, m.right_ticks_odo))
                    time.sleep(0.01)
                m.stop()
                time.sleep(1.5)
                s = [q for q in serie(am, a.janela, k) if q[0] >= a.embalo]
                for lado, idx, ativo in (("esq", 1, l > 0), ("dir", 2, r > 0)):
                    if not ativo:
                        continue
                    v = [q[idx] * 100 for q in s]
                    if len(v) < 3:
                        print(f"  {pct:4.1f}% {nome:8s} {lado}: poucas amostras")
                        continue
                    print(f"  {pct:4.1f}% {nome:8s} {lado}: média {statistics.mean(v):5.1f} "
                          f"mín {min(v):5.1f} máx {max(v):5.1f} dp {statistics.pstdev(v):4.1f} cm/s")
                    print("        " + " ".join(f"{x:.0f}" for x in v))
                    for q in s:
                        linhas.append([pct, nome, lado, round(q[0], 2), round(q[idx], 4)])
        os.makedirs(PASTA, exist_ok=True)
        arq = os.path.join(PASTA, f"suspensas_{time.strftime('%Y%m%d_%H%M%S')}.csv")
        with open(arq, "w", newline="") as fh:
            w = csv.writer(fh)
            w.writerow(["pct", "teste", "lado", "t_s", "v_ms"])
            w.writerows(linhas)
        print(f"\ndados: {arq}")
        return 0
    finally:
        m.stop()
        try:
            m.cleanup()
        except Exception:
            pass


if __name__ == "__main__":
    sys.exit(main())
