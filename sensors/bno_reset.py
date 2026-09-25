"""
sensors/bno_reset.py
Os pinos do BNO085 — RST e interruptor de energia — as ÚNICAS escritas em GPIO
fora do core/motor_driver.py.

POR QUE EXISTE (23/09/2026): o BNO085 às vezes acorda MUDO quando o robô é
ligado — zero bytes na UART, com a fiação certa e a UART da Pi certa. Aconteceu
em 22/09 e 23/09; nas duas vezes só voltou desligando e religando o robô. O
teste de mexer fio a fio não reproduziu nada: é a partida, não mau contato.
O RST do GY-BNO08x foi ligado ao GPIO 4 (pino físico 7), e um pulso baixo
reinicia o sensor sem ninguém abrir o robô. Provado no hardware em 23/09: yaw
de -118,44° virou -0,02° (o sensor zera o yaw ao reiniciar) e os quadros
voltaram na hora.

O INTERRUPTOR DE ENERGIA (24/09/2026): na noite de 23/09 o reset não bastou —
cinco pulsos, RST solto e VCC religado, e o sensor só voltou com o corte total
do robô. Hipótese: o chip trava e religar só o VCC não o desliga de verdade,
porque o PS0 seguia no 3,3 V da Pi. Um BC327 (PNP) entre o 3V3 (pino 1) e o
VCC+PS0 do BNO, com a base no BNO_POWER_PIN por 1 kΩ e 10 kΩ entre base e
emissor, deixa o software fazer esse corte total:
  - pino em BAIXO → corrente sai da base, o transistor conduz, BNO ligado;
  - pino SOLTO (entrada com pull-up) → o 10 kΩ desliga o transistor, BNO sem
    energia, inclusive no PS0.
Durante o corte o RST fica preso em BAIXO: o pull-up interno da Pi no GPIO 4
alimentaria o chip por fora e o corte deixaria de ser total. O RX da UART
(GPIO 15) fica como está: o pull-up dele passa uns 50 µA, pouco para segurar
um chip travado, e mexer na função do pino desligaria a UART.

A REGRA DESTE MÓDULO: os pinos só são puxados para BAIXO e depois SOLTOS
(entrada com pull-up). Nunca são postos em nível alto. Quem segura o RST alto é
o pull-up — o da placa e o interno da Pi (o GPIO 4 nasce com pull-up, por isso
foi escolhido no lugar do GPIO 22, que nasce com pull-down e seguraria o sensor
em reset no boot). O GPIO 7 também nasce com pull-up: no boot o transistor fica
desligado até o serviço ligar o BNO. Assim, mesmo com um pino em curto, a Pi
nunca entra em curto contra ele.

A varredura da Regra Nº 0 (scripts/validate_phase1.py) confere este arquivo
linha a linha: só o BNO_RESET_PIN e o BNO_POWER_PIN, toda saída com
initial=GPIO.LOW, sem output nem PWM.
"""

import logging
import time

from config.settings import (
    GPIO_AVAILABLE, BNO_RESET_PIN, BNO_RESET_PULSE_S,
    BNO_POWER_PIN, BNO_POWER_OFF_S,
)

log = logging.getLogger(__name__)

GPIO = None
if GPIO_AVAILABLE:
    try:
        import RPi.GPIO as GPIO     # rpi-lgpio na Pi 5
    except ImportError:
        GPIO = None


def reset_disponivel() -> bool:
    return GPIO is not None and BNO_RESET_PIN is not None


def energia_disponivel() -> bool:
    return GPIO is not None and BNO_POWER_PIN is not None and BNO_RESET_PIN is not None


def pulsar_reset() -> bool:
    """Puxa o RST para baixo por BNO_RESET_PULSE_S e o solta. True se pulsou."""
    if not reset_disponivel():
        return False
    try:
        GPIO.setmode(GPIO.BCM)
        GPIO.setwarnings(False)
        try:
            GPIO.setup(BNO_RESET_PIN, GPIO.OUT, initial=GPIO.LOW)
            time.sleep(BNO_RESET_PULSE_S)
        finally:
            GPIO.setup(BNO_RESET_PIN, GPIO.IN, pull_up_down=GPIO.PUD_UP)
        return True
    except Exception as e:
        log.error(f"[BNO reset] Falha ao pulsar o GPIO {BNO_RESET_PIN}: {e}")
        return False


def ligar_energia() -> bool:
    """Liga o BNO: base do BC327 em BAIXO, o transistor conduz. True se ligou."""
    if not energia_disponivel():
        return False
    try:
        GPIO.setmode(GPIO.BCM)
        GPIO.setwarnings(False)
        GPIO.setup(BNO_POWER_PIN, GPIO.OUT, initial=GPIO.LOW)
        return True
    except Exception as e:
        log.error(f"[BNO energia] Falha ao ligar pelo GPIO {BNO_POWER_PIN}: {e}")
        return False


def ciclar_energia() -> bool:
    """
    Corte total: RST preso em baixo, energia cortada por BNO_POWER_OFF_S,
    energia de volta e, por fim, o RST solto — o sensor parte limpo.
    True se o ciclo completou. Bloqueia ~BNO_POWER_OFF_S (roda na thread do
    HeadingLock, nunca no loop de 50 Hz).
    """
    if not energia_disponivel():
        return False
    religado = False
    try:
        GPIO.setmode(GPIO.BCM)
        GPIO.setwarnings(False)
        GPIO.setup(BNO_RESET_PIN, GPIO.OUT, initial=GPIO.LOW)
        try:
            GPIO.setup(BNO_POWER_PIN, GPIO.IN, pull_up_down=GPIO.PUD_UP)
            time.sleep(BNO_POWER_OFF_S)
            GPIO.setup(BNO_POWER_PIN, GPIO.OUT, initial=GPIO.LOW)
            religado = True
            time.sleep(BNO_RESET_PULSE_S)
        finally:
            if not religado:
                # Falhou no meio: o BNO não pode ficar sem energia por isso.
                try:
                    GPIO.setup(BNO_POWER_PIN, GPIO.OUT, initial=GPIO.LOW)
                except Exception:
                    pass
            GPIO.setup(BNO_RESET_PIN, GPIO.IN, pull_up_down=GPIO.PUD_UP)
        return religado
    except Exception as e:
        log.error(f"[BNO energia] Falha no corte de energia (GPIO {BNO_POWER_PIN}): {e}")
        return False
