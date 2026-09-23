"""
sensors/bno_reset.py
O pino de reset do BNO085 — a ÚNICA escrita em GPIO fora do core/motor_driver.py.

POR QUE EXISTE (23/09/2026): o BNO085 às vezes acorda MUDO quando o robô é
ligado — zero bytes na UART, com a fiação certa e a UART da Pi certa. Aconteceu
em 22/09 e 23/09; nas duas vezes só voltou desligando e religando o robô. O
teste de mexer fio a fio não reproduziu nada: é a partida, não mau contato.
O RST do GY-BNO08x foi ligado ao GPIO 4 (pino físico 7), e um pulso baixo
reinicia o sensor sem ninguém abrir o robô. Provado no hardware em 23/09: yaw
de -118,44° virou -0,02° (o sensor zera o yaw ao reiniciar) e os quadros
voltaram na hora.

A REGRA DESTE MÓDULO: o pino só é puxado para BAIXO e depois SOLTO (entrada com
pull-up). Nunca é posto em nível alto. Quem segura o RST alto é o pull-up — o da
placa e o interno da Pi (o GPIO 4 nasce com pull-up, por isso foi escolhido no
lugar do GPIO 22, que nasce com pull-down e seguraria o sensor em reset no boot).
Assim, mesmo com o RST em curto, a Pi nunca entra em curto contra ele.

A varredura da Regra Nº 0 (scripts/validate_phase1.py) confere este arquivo
linha a linha: só o BNO_RESET_PIN, só com initial=GPIO.LOW, sem output nem PWM.
"""

import logging
import time

from config.settings import GPIO_AVAILABLE, BNO_RESET_PIN, BNO_RESET_PULSE_S

log = logging.getLogger(__name__)

GPIO = None
if GPIO_AVAILABLE:
    try:
        import RPi.GPIO as GPIO     # rpi-lgpio na Pi 5
    except ImportError:
        GPIO = None


def reset_disponivel() -> bool:
    return GPIO is not None and BNO_RESET_PIN is not None


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
