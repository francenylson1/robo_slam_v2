#!/usr/bin/env python3
"""
scripts/bancada_giro.py
Prova P2 da missão (29/09/2026): GIRAR PARADO no chão, medindo pelo BNO085.

O giro no lugar NUNCA foi medido com os motores — só empurrado. A missão vai
girar com as rodas em sentidos opostos, forte (--forte, 10%) até faltarem
--fino-graus (20°) e fraco (--fino, 8%) no fim, parando com erro < --tol (5°).
Este script faz exatamente isso, UMA vez, e mede:
  - a velocidade de giro em cada fase (°/s);
  - quanto o robô ainda gira DEPOIS de parar (a inércia, em 2 s);
  - o erro final.
Os números entram no settings.py (MISSAO_GIRO_*) antes das provas P3–P5.

SINAL (o mesmo da missão): o BNO cresce para a DIREITA. Girar à direita =
roda esquerda para a frente, direita para trás: set_speed(+p, −p).

SEGURANÇA: duração máxima de 15 s; sem avanço de 5° em 3 s → para; SIGINT e
SIGTERM param; stop() num finally. O teto de 12% da missão vale aqui também.

ANTES:  sudo systemctl stop frota-rosto frota-robo   (e conferir os dois)
USO:    .venv/bin/python scripts/bancada_giro.py --lado esquerda
        .venv/bin/python scripts/bancada_giro.py --lado direita --forte 10 --fino 8
DEPOIS: sudo systemctl start frota-robo frota-rosto
"""

import argparse
import os
import signal
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config.settings import (MISSAO_TETO_PCT, MISSAO_GIRO_PCT, MISSAO_GIRO_FINO_PCT,
                             MISSAO_GIRO_FINO_DEG, MISSAO_GIRO_TOL_DEG)

DURACAO_MAXIMA = 15.0
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


def main() -> int:
    global _motors
    ap = argparse.ArgumentParser(description="P2: giro no lugar, medido pelo BNO085.")
    ap.add_argument("--lado", choices=["esquerda", "direita"], required=True)
    ap.add_argument("--graus", type=float, default=90.0)
    ap.add_argument("--forte", type=float, default=MISSAO_GIRO_PCT)
    ap.add_argument("--fino", type=float, default=MISSAO_GIRO_FINO_PCT)
    ap.add_argument("--fino-graus", type=float, default=MISSAO_GIRO_FINO_DEG)
    ap.add_argument("--tol", type=float, default=MISSAO_GIRO_TOL_DEG)
    ap.add_argument("--espera", type=float, default=5.0,
                    help="segundos para a pessoa se afastar antes de girar")
    # MODO PULSOS (29/09, depois das duas primeiras medidas: a 10% o robô
    # ainda girou 39° DEPOIS de parar; a 8%, 15°). Gira contínuo só até
    # faltarem --antecipa graus e termina com pulsos curtos, medindo cada um.
    ap.add_argument("--antecipa", type=float, default=0.0,
                    help="para o giro contínuo quando faltar isto (0 = sem pulsos)")
    ap.add_argument("--pulso", type=float, default=0.12, help="duração do pulso (s)")
    ap.add_argument("--pausa", type=float, default=0.5, help="espera entre pulsos (s)")
    a = ap.parse_args()

    if os.system("systemctl is-active --quiet frota-robo") == 0 or \
       os.system("systemctl is-active --quiet frota-rosto") == 0:
        print("RECUSADO: pare os serviços antes (o rosto religa o frota-robo):\n"
              "  sudo systemctl stop frota-rosto frota-robo")
        return 2
    for pct in (a.forte, a.fino):
        if not (8.0 <= pct <= MISSAO_TETO_PCT):
            print(f"RECUSADO: potência {pct}% fora de 8–{MISSAO_TETO_PCT}%.")
            return 2

    signal.signal(signal.SIGINT, _parar_tudo)
    signal.signal(signal.SIGTERM, _parar_tudo)

    from core.motor_driver import MotorDriver
    from sensors.heading_lock import HeadingLock
    _motors = motors = MotorDriver()
    h = HeadingLock()
    h.start()
    try:
        for _ in range(50):
            if h.healthy:
                break
            time.sleep(0.2)
        if not h.healthy:
            print("BNO085 sem leitura — abortado, nada foi comandado.")
            return 1

        print(f"Giro de {a.graus:.0f}° à {a.lado.upper()}: {a.forte}% e {a.fino}% "
              f"nos últimos {a.fino_graus:.0f}°. Saia de perto: {a.espera:.0f} s.")
        time.sleep(a.espera)

        # alvo em "giro acumulado" (soma de passos: imune ao ±180°)
        sinal = 1.0 if a.lado == "direita" else -1.0
        alvo = sinal * a.graus
        acum, ant = 0.0, h.yaw_deg
        t0 = time.monotonic()
        janela_t, janela_v = t0, 0.0
        fases = {"forte": [None, None, 0.0], "fino": [None, None, 0.0]}  # t0, t1, graus
        motivo = "chegou"
        while True:
            agora = time.monotonic()
            y = h.yaw_deg
            passo = norm(y - ant)
            ant = y
            acum += passo
            falta = alvo - acum
            if abs(falta) <= a.tol:
                break
            if agora - t0 > DURACAO_MAXIMA:
                motivo = "tempo máximo"
                break
            if not h.healthy:
                motivo = "BNO sem leitura"
                break
            if agora - janela_t >= 3.0:
                if abs(acum) - janela_v < 5.0:
                    motivo = "sem avanço (5° em 3 s)"
                    break
                janela_t, janela_v = agora, abs(acum)
            if a.antecipa > 0 and abs(falta) <= a.antecipa:
                motivo = "antecipou"
                break
            fase = "forte" if abs(falta) > a.fino_graus else "fino"
            f = fases[fase]
            if f[0] is None:
                f[0] = agora
            f[1] = agora
            f[2] += abs(passo)
            pct = a.forte if fase == "forte" else a.fino
            d = 1.0 if falta > 0 else -1.0     # + = girar à direita
            motors.set_speed(d * pct, -d * pct)
            time.sleep(0.01)
        motors.stop()
        pulsos = []
        if motivo == "antecipou":
            # deixa a inércia do giro contínuo acabar antes de medir
            fim_ = time.monotonic() + a.pausa + 0.5
            while time.monotonic() < fim_:
                y = h.yaw_deg
                acum += norm(y - ant)
                ant = y
                time.sleep(0.01)
            motivo = "chegou"
            while abs(alvo - acum) > a.tol:
                if len(pulsos) >= 30 or time.monotonic() - t0 > DURACAO_MAXIMA + 15:
                    motivo = "pulsos demais"
                    break
                antes = acum
                d = 1.0 if alvo - acum > 0 else -1.0
                motors.set_speed(d * a.fino, -d * a.fino)
                time.sleep(a.pulso)
                motors.stop()
                fim_ = time.monotonic() + a.pausa
                while time.monotonic() < fim_:
                    y = h.yaw_deg
                    acum += norm(y - ant)
                    ant = y
                    time.sleep(0.01)
                pulsos.append(acum - antes)
        parou_em = acum
        t_fim = time.monotonic()
        # inércia: quanto ainda gira depois de parar
        while time.monotonic() - t_fim < 2.0:
            y = h.yaw_deg
            acum += norm(y - ant)
            ant = y
            time.sleep(0.01)

        print(f"\nRESULTADO: {motivo}")
        for nome, (ta, tb, g) in fases.items():
            if ta is not None and tb and tb > ta:
                print(f"  fase {nome:5s}: {g:5.1f}° em {tb - ta:4.1f} s → {g / (tb - ta):5.1f} °/s")
            else:
                print(f"  fase {nome:5s}: não usada")
        if pulsos:
            print(f"  pulsos  : {len(pulsos)} de {a.pulso:.2f} s a {a.fino}% → "
                  + ", ".join(f"{g:+.1f}°" for g in pulsos))
        print(f"  parou com {parou_em:+.1f}° (alvo {alvo:+.0f}°)")
        print(f"  inércia : {acum - parou_em:+.1f}° nos 2 s depois de parar")
        print(f"  FINAL   : {acum:+.1f}° → erro {acum - alvo:+.1f}° "
              f"({'dentro' if abs(acum - alvo) <= a.tol else 'FORA'} de ±{a.tol:.0f}°)")
        return 0 if motivo == "chegou" else 1
    finally:
        motors.stop()
        h.stop()
        try:
            motors.cleanup()
        except Exception:
            pass


if __name__ == "__main__":
    sys.exit(main())
