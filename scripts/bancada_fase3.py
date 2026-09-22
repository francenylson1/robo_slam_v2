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
    python3 scripts/bancada_fase3.py --teste FREIO --freio segura --segurar 20
    python3 scripts/bancada_fase3.py --teste FREIO --freio livre  --segurar 20

O que cada teste prova:
    A1     os dois lados à frente   → o robô anda para FRENTE
    A2     os dois lados em ré      → o robô anda para TRÁS
    A3     só o lado esquerdo       → gira para a DIREITA
    A4     só o lado direito        → gira para a ESQUERDA
    FREIO    mantém o robô SEGURO ou LIVRE, para alguém tentar empurrá-lo
    ENCODER  conta os ticks dos dois Hall enquanto ALGUÉM EMPURRA o robô —
             nenhum motor é comandado
    RUMO     confirma o SINAL do yaw girando o robô na mão — nenhum motor é
             comandado. Diz se a malha de rumo vai endireitar ou espiralar
    RETA     o gate da Fase 3: anda para a frente medindo o desvio de rumo,
             com a correção LIGADA ou DESLIGADA (--assist on|off)
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
SEGURAR_MAXIMO  = 180.0    # s — teto dos testes sem PWM (freio, encoder, hall)

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


def prova_freio(motors, segurar: bool, segundos: float):
    """Mantém o robô SEGURO ou LIVRE pelo tempo pedido, com PWM em zero, para
    alguém tentar empurrá-lo.

    Foi este teste que mostrou, em 22/09/2026, que o projeto tinha os dois
    estados invertidos: o pino chamado "freio" é um enable de lógica invertida.
    O professor empurrou o robô e ele andou. Ler o pino não prova o efeito.
    """
    rotulo = "SEGURANDO (driver ligado)" if segurar else "LIVRE (driver desligado)"
    print(f"  {rotulo} — por {segundos:.0f}s, PWM em zero.")
    try:
        motors.set_brake(segurar)
        time.sleep(segundos)
    finally:
        motors.stop()        # volta ao estado de parada, qualquer que seja o fim
    print("  Tempo esgotado. Robô devolvido ao estado de parada.")


def prova_encoder(motors, segundos: float):
    """Conta os ticks dos dois encoders Hall enquanto alguém empurra o robô.

    NENHUM motor é comandado: a retenção é solta para as rodas girarem leves, os
    contadores são zerados, e no fim se lê quanto cada lado contou. É a Etapa B
    da Fase 3 — os encoders nunca tinham sido lidos pelo v2, e são pré-requisito
    do controle por TPS e da odometria da Fase 4.

    Referência: TICKS_PER_REVOLUTION = 45 (medido pelo professor no v1). Uma
    roda de hoverboard de 6,5" tem ~0,52 m de circunferência, então ~1 m
    empurrado deve dar ~86 ticks por lado.
    """
    from config.settings import TICKS_PER_REVOLUTION

    motors.set_brake(False)           # solta, para a roda girar leve na mão
    motors.get_and_reset_ticks()      # zera os contadores
    print(f"  Contando por {segundos:.0f}s. Empurre o robô — nenhum motor "
          f"será acionado.")
    time.sleep(segundos)
    t = motors.get_and_reset_ticks()
    esq  = abs(t["left"])
    dir_ = abs(t["right"])
    print("")
    print(f"  ESQUERDO: {esq} ticks  ->  {esq / TICKS_PER_REVOLUTION:.2f} voltas")
    print(f"  DIREITO : {dir_} ticks  ->  {dir_ / TICKS_PER_REVOLUTION:.2f} voltas")
    if esq == 0 or dir_ == 0:
        print("  !! um dos lados NAO contou — fiacao do Hall ou pino errado")
    elif max(esq, dir_) > 3 * max(1, min(esq, dir_)):
        print("  !! diferenca grande entre os lados — verificar")
    else:
        print("  Os dois lados contaram na mesma ordem de grandeza.")


def prova_hall(motors, segundos: float):
    """Observa o nível BRUTO dos dois pinos de encoder, sem contar nada.

    Separa os dois diagnósticos que a contagem zerada não distingue:
      - pino preso em 0 ou em 1  -> o sinal não chega (fiação, alimentação do
        sensor, pino errado, ou pull-up/pull-down trocado);
      - pino alternando          -> o sinal chega e o problema é a contagem.
    """
    motors.set_brake(False)           # roda leve na mão
    amostras = {"left": [], "right": []}
    fim = time.time() + segundos
    print(f"  Observando os pinos por {segundos:.0f}s. Gire as rodas na mão.")
    while time.time() < fim:
        bruto = motors.hall_raw()
        amostras["left"].append(bruto["left"])
        amostras["right"].append(bruto["right"])
        time.sleep(0.002)
    for lado, nome in (("left", "ESQUERDO"), ("right", "DIREITO ")):
        v = amostras[lado]
        if not v or v[0] is None:
            print(f"  {nome}: sem leitura (GPIO indisponível)")
            continue
        trocas = sum(1 for i in range(1, len(v)) if v[i] != v[i - 1])
        niveis = sorted(set(v))
        print(f"  {nome}: {len(v)} amostras · níveis vistos {niveis} · "
              f"{trocas} transições")
        if trocas == 0:
            print(f"           -> PRESO em {niveis[0]} — o sinal NAO chega ao pino")


def prova_reta(motors, bumper, potencia: float, segundos: float,
               assist_on: bool, espera: float):
    """O gate da Fase 3: anda para a frente e mede o quanto o rumo desviou.

    Roda-se DUAS vezes — com a correção desligada e ligada — e comparam-se os
    desvios. Sem o par de medidas não há prova de que a malha serve para algo.

    O desvio é medido de duas formas independentes:
      - pelo BNO085, acumulando o giro durante o percurso (esta função);
      - pela trena, no chão, medindo o afastamento da linha (o professor).
    """
    from sensors.heading_lock import HeadingLock
    from core.heading_assist import HeadingAssist, normaliza_graus
    from config.settings import (HEADING_KP_PCT, HEADING_KI_PCT,
                                 HEADING_INTEGRAL_MAX, HEADING_TRIM_PCT,
                                 HEADING_MAX_CORR_PCT,
                                 HEADING_INVERT, HEADING_STRAIGHT_TOL_PCT)

    h = HeadingLock()
    h.start()
    for _ in range(50):
        if h.healthy:
            break
        time.sleep(0.2)
    if not h.healthy:
        print("  BNO085 sem leitura — abortado.")
        h.stop()
        return

    assist = HeadingAssist(kp_pct=HEADING_KP_PCT, ki_pct=HEADING_KI_PCT,
                           limite_integral=HEADING_INTEGRAL_MAX,
                           trim_pct=HEADING_TRIM_PCT,
                           max_corr_pct=HEADING_MAX_CORR_PCT,
                           invert=HEADING_INVERT,
                           tol_pct=HEADING_STRAIGHT_TOL_PCT,
                           teto_pct=MOTOR_MAX_POWER_PCT,
                           enabled=assist_on)

    print(f"  Correção: {'LIGADA' if assist_on else 'DESLIGADA'} · "
          f"{potencia}% por até {segundos:.1f}s")

    # Carência para quem posicionou o robô sair da frente. Sem isto o teste
    # começa a medir no instante em que sobe, e a pessoa ainda no arco de ±30°
    # faz o bumper bloquear no primeiro ciclo — aconteceu em 22/09/2026.
    if espera > 0:
        print(f"  Saia da frente: {espera:.0f}s de carência antes de andar.")
        time.sleep(espera)
    if bumper is not None and bumper.blocked_front:
        print("  x ainda há obstáculo no arco frontal — nada foi comandado.")
        print(f"    mais perto: {bumper.health().get('nearest_m')} m a "
              f"{bumper.health().get('nearest_deg')}°")
        h.stop()
        return

    acumulado = 0.0
    anterior  = h.yaw_deg
    maior_corr = 0.0
    motivo = "tempo"
    # Medir só o desvio FINAL não distingue "estabilizou torto" de "está no meio
    # de uma oscilação" — os dois podem dar o mesmo número. Daí o perfil.
    pico_dir  = 0.0        # maior excursão para um lado
    pico_esq  = 0.0        # e para o outro
    cruzou    = 0          # quantas vezes passou pela linha (= oscilações)
    soma_quad = 0.0        # para o desvio médio quadrático
    amostras  = 0
    sinal_ant = 0
    # Correções ao longo do tempo: a MÉDIA na segunda metade do percurso é o
    # valor do trim — a diferença que o robô precisa ter em regime para andar
    # reto. Alimentando isso direto na partida, o transiente inicial some.
    correcoes = []
    inicio = time.time()
    try:
        while time.time() - inicio < segundos:
            if bumper is not None and bumper.blocked_front:
                motivo = "LIDAR bloqueou"
                break
            atual = h.yaw_deg
            acumulado += normaliza_graus(atual - anterior)
            anterior = atual

            pico_dir = max(pico_dir, acumulado)
            pico_esq = min(pico_esq, acumulado)
            soma_quad += acumulado * acumulado
            amostras += 1
            sinal = 1 if acumulado > 1.0 else (-1 if acumulado < -1.0 else 0)
            if sinal != 0:
                if sinal_ant != 0 and sinal != sinal_ant:
                    cruzou += 1
                sinal_ant = sinal

            novo = assist.corrigir(potencia, potencia, atual, h.healthy)
            if novo is None:
                motors.set_speed(potencia, potencia)
            else:
                motors.set_speed(novo[0], novo[1])
                corr = (novo[1] - novo[0]) / 2.0
                correcoes.append(corr)
                if abs(corr) > abs(maior_corr):
                    maior_corr = corr
            time.sleep(0.02)                      # 50 Hz, igual ao loop real
    finally:
        motors.stop()
        h.stop()

    andou = time.time() - inicio
    rms = (soma_quad / amostras) ** 0.5 if amostras else 0.0
    print("")
    print(f"  Percurso: {andou:.1f}s — parou por {motivo}")
    print(f"  Desvio FINAL:  {acumulado:+.1f}°")
    print(f"  Excursão:      {pico_esq:+.1f}° a {pico_dir:+.1f}°  "
          f"(amplitude {pico_dir - pico_esq:.1f}°)")
    # ATENÇÃO ao que este número é: cruzamentos do RUMO de referência, não da
    # linha no chão. A malha controla rumo, não posição — o robô pode oscilar em
    # torno do rumo certo e mesmo assim seguir todo de um lado da linha, em
    # paralelo a ela. Foi o que o professor observou em 22/09/2026: 4
    # cruzamentos de rumo, 1 cruzamento de linha.
    print(f"  Cruzou o RUMO de referência {cruzou}x  ->  "
          f"{'rumo OSCILANDO' if cruzou >= 2 else 'rumo sem oscilação franca'}")
    print("     (rumo, não a linha do chão — a malha não controla posição)")
    print(f"  Desvio médio quadrático: {rms:.1f}°   "
          f"(o quanto ficou fora da linha no conjunto)")
    if assist_on:
        print(f"  Maior correção aplicada: {maior_corr:+.2f}%"
              f"{'  <- SATUROU' if abs(maior_corr) >= 5.99 else ''}")
        if len(correcoes) >= 4:
            metade = correcoes[len(correcoes) // 2:]
            regime = sum(metade) / len(metade)
            print(f"  Correção média EM REGIME: {regime:+.2f}%")
            print(f"     -> é este o valor de HEADING_TRIM_PCT. Alimentado na "
                  f"partida, mata o transiente inicial.")
    print("  Agora meça com a trena o afastamento lateral da linha.")


def prova_rumo(segundos: float):
    """Confirma no hardware o SINAL do yaw, sem comandar motor nenhum.

    A malha de rumo depende disto: no v2 o yaw vem do UART-RVC e, pela medida
    de 21/09/2026, girar para a DIREITA AUMENTA o yaw. O v1 usa a convenção
    oposta (calcula do quaternion), e por isso precisa de invert=True. Copiar a
    constante dele faria a correção empurrar NA DIREÇÃO do erro — o robô faria
    uma espiral em vez de endireitar.

    Aqui só se LÊ o sensor. Quem gira o robô é a pessoa.
    """
    from sensors.heading_lock import HeadingLock

    h = HeadingLock()
    h.start()
    for _ in range(50):                       # espera o sensor ficar saudável
        if h.healthy:
            break
        time.sleep(0.2)
    if not h.healthy:
        print("  BNO085 sem leitura — verifique se o frota-robo está parado.")
        h.stop()
        return

    from core.heading_assist import normaliza_graus

    inicio = h.yaw_deg
    print(f"  Yaw inicial: {inicio:.1f}°. Gire o robô para a DIREITA nos "
          f"próximos {segundos:.0f}s.")

    # ACUMULA passo a passo. Comparar só início e fim não distingue "girou 110°
    # num sentido" de "girou 249° no outro" quando o yaw cruza o ±180° — foi o
    # que arruinou a primeira tentativa deste teste, em 22/09/2026. O v1 já
    # tratava isso: "soma dos passos (evita wrap)".
    acumulado = 0.0
    anterior  = h.yaw_deg
    maior_passo = 0.0
    fim = time.time() + segundos
    while time.time() < fim:
        atual = h.yaw_deg
        passo = normaliza_graus(atual - anterior)
        if abs(passo) > maior_passo:
            maior_passo = abs(passo)
        acumulado += passo
        anterior = atual
        time.sleep(0.02)
    h.stop()

    print("")
    print(f"  Yaw inicial {inicio:7.1f}°   final {anterior:7.1f}°")
    print(f"  Giro ACUMULADO: {acumulado:+.1f}°  (maior passo entre amostras: "
          f"{maior_passo:.1f}°)")
    if maior_passo > 90:
        print("  !! passo grande demais entre amostras — leitura perdeu pulso; "
              "gire mais devagar e repita")
    if abs(acumulado) < 20:
        print("  ?? giro pequeno — o robô foi mesmo girado?")
    elif acumulado > 0:
        print("  -> Girar à DIREITA AUMENTA o yaw. Confirma HEADING_INVERT=False.")
    else:
        print("  -> Girar à DIREITA DIMINUI o yaw. HEADING_INVERT deve virar True!")


def main() -> int:
    global _motors

    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--teste", required=True,
                   choices=["A1", "A2", "A3", "A4", "RETA", "FREIO", "ENCODER", "HALL", "RUMO"])
    p.add_argument("--potencia", type=float, default=POTENCIA_PADRAO)
    p.add_argument("--duracao", type=float, default=DURACAO_PADRAO)
    p.add_argument("--freio", choices=["segura", "livre"], default="segura",
                   help="qual estado segurar no teste FREIO")
    p.add_argument("--segurar", type=float, default=20.0,
                   help="segundos segurando o estado no teste FREIO")
    p.add_argument("--espera", type=float, default=6.0,
                   help="segundos de carência antes de andar, no teste RETA")
    p.add_argument("--assist", choices=["on", "off"], default="off",
                   help="malha de rumo ligada ou desligada no teste RETA")
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

    # ── testes sem PWM: não comandam motor, não precisam do LIDAR ────────
    if args.teste in ("FREIO", "ENCODER", "HALL", "RUMO"):
        try:
            if args.teste == "FREIO":
                prova_freio(motors, args.freio == "segura", seg)
            elif args.teste == "HALL":
                prova_hall(motors, seg)
            elif args.teste == "RUMO":
                prova_rumo(seg)
            else:
                prova_encoder(motors, seg)
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

    janela = "" if args.teste == "RETA" else f" · pulso de {dur}s"
    print("")
    print(f"Potência {pot}%{janela} · Regra Nº 0 ativa "
          f"(teto {MOTOR_MAX_POWER_PCT}%)")
    print("")

    try:
        if args.teste == "RETA":
            if frente_liberada():
                prova_reta(motors, bumper, pot, min(abs(args.duracao), 30.0),
                           args.assist == "on", args.espera)
        elif args.teste == "A1":
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
