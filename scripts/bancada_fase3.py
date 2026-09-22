#!/usr/bin/env python3
"""
scripts/bancada_fase3.py
Etapa A da Fase 3 — o PRIMEIRO movimento deste robô sob o v2.

Até 22/09/2026 o v2 nunca moveu este robô: os motores giravam pelo código do v1.
Os pinos, a lógica direcional, a polaridade do freio e a frequência do PWM foram
auditados e batem (docs/FASE3_PLANO.md, §1) — isto aqui é a prova física.

PULSOS CURTOS, PARADOS POR TEMPO. O robô anda poucos centímetros por teste. A
parada não depende da mão de ninguém: é `time.sleep` seguido de stop() num
`finally`, e há handler de SIGINT/SIGTERM. Se a sessão SSH cair, o processo morre
e o systemd não o reinicia — os freios ficam acionados (provado na Fase 1.5).

ANTES DE RODAR:
    sudo systemctl stop frota-robo      # ele segura o GPIO e o LIDAR
DEPOIS:
    sudo systemctl start frota-robo

USO (na Pi, com o professor ao lado da chave geral):
    python3 scripts/bancada_fase3.py --teste A1
    python3 scripts/bancada_fase3.py --teste todos
    python3 scripts/bancada_fase3.py --teste A1 --potencia 10 --duracao 0.6

O que cada teste prova:
    A1  os dois lados à frente   → o robô anda para FRENTE
    A2  os dois lados em ré      → o robô anda para TRÁS
    A3  só o lado esquerdo       → gira para a DIREITA
    A4  só o lado direito        → gira para a ESQUERDA
    A5  sem comando              → freios ACIONADOS
"""

import argparse
import os
import signal
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config.settings import MOTOR_MAX_POWER_PCT, OBSTACLE_STOP_DISTANCE_M

POTENCIA_PADRAO = 8.0      # v1: 8% é o perfil "lenta / precisão máxima"
DURACAO_PADRAO  = 0.4      # s
DURACAO_MAXIMA  = 2.0      # s — trava do script, independente do que se peça

_motors = None


def _parar_tudo(*_):
    """Handler de sinal e rede de segurança do encerramento."""
    if _motors is not None:
        try:
            _motors.stop()
        except Exception:
            pass
    sys.exit(1)


def frota_robo_rodando() -> bool:
    return os.system("systemctl is-active --quiet frota-robo") == 0


def pulso(motors, esquerda: float, direita: float, duracao: float, rotulo: str):
    """Um pulso cronometrado. O stop() está no finally: qualquer exceção,
    Ctrl+C ou queda de conexão para os motores antes de sair."""
    print(f"  → {rotulo}: E={esquerda:+.1f}%  D={direita:+.1f}%  por {duracao:.1f}s")
    try:
        motors.set_speed(esquerda, direita)
        time.sleep(duracao)
    finally:
        motors.stop()
    time.sleep(0.6)          # deixa o robô assentar antes do próximo teste


def main() -> int:
    global _motors

    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--teste", required=True,
                   choices=["A1", "A2", "A3", "A4", "A5", "todos"])
    p.add_argument("--potencia", type=float, default=POTENCIA_PADRAO)
    p.add_argument("--duracao", type=float, default=DURACAO_PADRAO)
    p.add_argument("--sem-bumper", action="store_true",
                   help="não exigir o LIDAR (use só se o LIDAR estiver ocupado)")
    args = p.parse_args()

    if frota_robo_rodando():
        print("frota-robo está ATIVO — ele segura o GPIO e o LIDAR.")
        print("  sudo systemctl stop frota-robo")
        return 2

    pot = min(abs(args.potencia), MOTOR_MAX_POWER_PCT)   # a Regra 0 corta de novo
    dur = min(abs(args.duracao), DURACAO_MAXIMA)
    if pot != args.potencia or dur != args.duracao:
        print(f"Ajustado para os limites do script: {pot}% / {dur}s")

    signal.signal(signal.SIGINT,  _parar_tudo)
    signal.signal(signal.SIGTERM, _parar_tudo)

    from core.motor_driver import MotorDriver
    _motors = motors = MotorDriver()

    # O bumper vale também na bancada. Ele nasce fail-closed (bloqueado) e leva
    # ~2s para a primeira varredura completa — esperar é parte do protocolo.
    bumper = None
    if not args.sem_bumper:
        from sensors.safety_bumper import SafetyBumper
        bumper = SafetyBumper()
        bumper.start()
        print(f"Aguardando o LIDAR (bloqueio a {OBSTACLE_STOP_DISTANCE_M*100:.0f} cm)...")
        for _ in range(50):
            if bumper.health().get("healthy"):
                break
            time.sleep(0.2)
        estado = "LIVRE" if not bumper.blocked_front else "BLOQUEADO"
        print(f"LIDAR: {estado} (mais perto: {bumper.health().get('nearest_m')} m)")

    def frente_liberada() -> bool:
        if bumper is None:
            return True
        if bumper.blocked_front:
            print("  ✗ obstáculo à frente — avanço recusado")
            return False
        return True

    testes = ["A1", "A2", "A3", "A4", "A5"] if args.teste == "todos" else [args.teste]

    print(f"\nPotência {pot}% · pulsos de {dur}s · Regra Nº 0 ativa (teto "
          f"{MOTOR_MAX_POWER_PCT}%)\n")

    try:
        for t in testes:
            if t == "A1":
                if frente_liberada():
                    pulso(motors, pot, pot, dur, "A1 FRENTE (esperado: anda para frente)")
            elif t == "A2":
                pulso(motors, -pot, -pot, dur, "A2 RÉ (esperado: anda para trás)")
            elif t == "A3":
                pulso(motors, pot, 0.0, dur, "A3 SÓ ESQUERDO (esperado: gira à DIREITA)")
            elif t == "A4":
                pulso(motors, 0.0, pot, dur, "A4 SÓ DIREITO (esperado: gira à ESQUERDA)")
            elif t == "A5":
                motors.stop()
                time.sleep(0.3)
                print("  → A5 PARADO: confira com a mão — as rodas devem estar "
                      "TRAVADAS (freio acionado)")
    finally:
        motors.stop()
        if bumper is not None:
            bumper.stop()
        motors.cleanup()

    print("\nFim. Religue o serviço:  sudo systemctl start frota-robo")
    return 0


if __name__ == "__main__":
    sys.exit(main())
