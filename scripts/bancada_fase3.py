#!/usr/bin/env python3
"""
scripts/bancada_fase3.py
Etapa A da Fase 3 — as provas físicas do núcleo motor sob o v2.

Até 22/09/2026 o v2 nunca tinha movido este robô: os motores giravam pelo código
do v1. Os pinos, a lógica direcional, a polaridade do freio e a frequência do PWM
foram auditados e batem (docs/FASE3_PLANO.md, §1) — isto aqui é a prova física.

PULSOS CURTOS, PARADOS POR TEMPO. O robô anda poucos centímetros por teste. A
parada não depende da mão de ninguém: é `time.sleep` seguido de stop() num
`finally`, e há handler de SIGINT/SIGTERM.

Quem dispara este script NÃO vê a saída dele enquanto roda (ela chega toda no
fim). Por isso cada execução faz UMA coisa, com duração conhecida, e o aviso de
"olhe agora" vem de fora, antes.

ANTES DE RODAR:
    sudo systemctl stop frota-robo      # ele segura o GPIO e o LIDAR
DEPOIS:
    sudo systemctl start frota-robo

USO (na Pi, com o professor ao lado da chave geral):
    python3 scripts/bancada_fase3.py --teste A1
    python3 scripts/bancada_fase3.py --teste A1 --potencia 12 --duracao 1.0
    python3 scripts/bancada_fase3.py --teste FREIO --freio acionado --segurar 20
    python3 scripts/bancada_fase3.py --teste FREIO --freio solto    --segurar 20

O que cada teste prova:
    A1     os dois lados à frente   → o robô anda para FRENTE
    A2     os dois lados em ré      → o robô anda para TRÁS
    A3     só o lado esquerdo       → gira para a DIREITA
    A4     só o lado direito        → gira para a ESQUERDA
    FREIO  segura um estado do pino de freio para alguém tentar empurrar o robô
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
SEGURAR_MAXIMO  = 60.0     # s — teto do teste de freio

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
    print(f"  -> {rotulo}: E={esquerda:+.1f}%  D={direita:+.1f}%  por {duracao:.1f}s")
    try:
        motors.set_speed(esquerda, direita)
        time.sleep(duracao)
    finally:
        motors.stop()
    time.sleep(0.6)          # deixa o robô assentar antes do próximo teste


def prova_freio(motors, acionado: bool, segundos: float):
    """Segura UM dos dois estados do pino de freio, com PWM em zero o tempo
    todo, para alguém tentar empurrar o robô.

    Responde a pergunta aberta em 22/09/2026: o robô realmente FREIA quando
    parado, ou só fica desligado e livre? O projeto afirmava que freava — mas
    com base no NÍVEL DO PINO, nunca porque alguém empurrou. O professor
    empurrou e ele andou. Ler o pino não é provar o efeito.
    """
    rotulo = "ACIONADO (BREAK=HIGH)" if acionado else "SOLTO (BREAK=LOW)"
    print(f"  Freio {rotulo} — segurando por {segundos:.0f}s, PWM em zero.")
    try:
        motors.set_brake(acionado)
        time.sleep(segundos)
    finally:
        motors.stop()        # volta ao estado de parada, qualquer que seja o fim
    print("  Tempo esgotado. Freio devolvido ao estado de parada.")


def main() -> int:
    global _motors

    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--teste", required=True,
                   choices=["A1", "A2", "A3", "A4", "FREIO"])
    p.add_argument("--potencia", type=float, default=POTENCIA_PADRAO)
    p.add_argument("--duracao", type=float, default=DURACAO_PADRAO)
    p.add_argument("--freio", choices=["acionado", "solto"], default="acionado",
                   help="qual estado segurar no teste FREIO")
    p.add_argument("--segurar", type=float, default=20.0,
                   help="segundos segurando o estado no teste FREIO")
    p.add_argument("--sem-bumper", action="store_true",
                   help="não exigir o LIDAR (use só se o LIDAR estiver ocupado)")
    args = p.parse_args()

    if frota_robo_rodando():
        print("frota-robo está ATIVO — ele segura o GPIO e o LIDAR.")
        print("  sudo systemctl stop frota-robo")
        return 2

    pot = min(abs(args.potencia), MOTOR_MAX_POWER_PCT)   # a Regra 0 corta de novo
    dur = min(abs(args.duracao), DURACAO_MAXIMA)
    seg = min(abs(args.segurar), SEGURAR_MAXIMO)

    signal.signal(signal.SIGINT,  _parar_tudo)
    signal.signal(signal.SIGTERM, _parar_tudo)

    from core.motor_driver import MotorDriver
    _motors = motors = MotorDriver()

    # ── teste de freio: não envolve PWM, não precisa do LIDAR ────────────
    if args.teste == "FREIO":
        try:
            prova_freio(motors, args.freio == "acionado", seg)
        finally:
            motors.stop()
            motors.cleanup()
        print("Fim. Religue o serviço: sudo systemctl start frota-robo")
        return 0

    # ── testes de movimento ──────────────────────────────────────────────
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
        if bumper is None or not bumper.blocked_front:
            return True
        print("  x obstáculo à frente — avanço recusado")
        return False

    print(f"\nPotência {pot}% · pulso de {dur}s · Regra Nº 0 ativa "
          f"(teto {MOTOR_MAX_POWER_PCT}%)\n")

    try:
        if args.teste == "A1":
            if frente_liberada():
                pulso(motors, pot, pot, dur, "A1 FRENTE")
        elif args.teste == "A2":
            pulso(motors, -pot, -pot, dur, "A2 RÉ")
        elif args.teste == "A3":
            pulso(motors, pot, 0.0, dur, "A3 SÓ ESQUERDO (esperado: gira à DIREITA)")
        elif args.teste == "A4":
            pulso(motors, 0.0, pot, dur, "A4 SÓ DIREITO (esperado: gira à ESQUERDA)")
    finally:
        motors.stop()
        if bumper is not None:
            bumper.stop()
        motors.cleanup()

    print("\nFim. Religue o serviço: sudo systemctl start frota-robo")
    return 0


if __name__ == "__main__":
    sys.exit(main())
