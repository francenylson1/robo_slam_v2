"""
main.py — Frota Mista v2
Ponto de entrada do sistema. Inicializa todos os subsistemas
e executa o loop de controle a 50Hz (20ms por ciclo).

Ordem de inicialização:
  1. Logger
  2. Sensores (battery, bumper, heading)
  3. Motor driver
  4. Joystick reader
  5. Servidor web Flask (thread)
  6. Loop de controle principal

Para executar:
  python3 main.py
  python3 main.py --mock        (força modo MOCK mesmo na Pi)
  python3 main.py --robot-id 3  (seleciona config do robô 3)
"""

import argparse
import logging
import os
import signal
import sys

# ─────────────────────────────────────────────
# ARGS
# ─────────────────────────────────────────────
parser = argparse.ArgumentParser(description="Frota Mista v2 — Robô Garçom")
parser.add_argument("--mock",     action="store_true", help="Força modo MOCK")
parser.add_argument("--robot-id", type=int, default=1,  help="ID do robô (1–10)")
parser.add_argument("--log",      default="INFO",       help="Nível de log")
args = parser.parse_args()

# Aplica --mock ANTES de qualquer import de config.settings (MOCK_MODE é decidido
# no import). Sem isto, a flag seria ignorada na Raspberry Pi.
if args.mock:
    os.environ["FROTA_MOCK"] = "1"

# ─────────────────────────────────────────────
# LOGGER
# ─────────────────────────────────────────────
logging.basicConfig(
    level=getattr(logging, args.log.upper(), logging.INFO),
    format="%(asctime)s [%(name)s] %(levelname)s — %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("main")
log.info(f"Iniciando Frota Mista v2 — Robô ID={args.robot_id}")

# ─────────────────────────────────────────────
# IMPORTS DOS MÓDULOS
# ─────────────────────────────────────────────
from config.settings import MOCK_MODE
from core.motor_driver   import MotorDriver
from core.joystick_reader import JoystickReader
from core.control_loop    import run_control_loop
from sensors.battery_monitor import BatteryMonitor
from sensors.safety_bumper   import SafetyBumper
from sensors.heading_lock    import HeadingLock
from web.server              import create_app

# ─────────────────────────────────────────────
# ESTADO GLOBAL COMPARTILHADO
# ─────────────────────────────────────────────
state = {
    "robot_id":    args.robot_id,
    "mode":        "JOYSTICK",   # JOYSTICK | AUTONOMO
    "blocked":     False,
    "lidar":       {"healthy": False, "fail_closed": False, "last_scan_age_s": None},
    "yaw_error":   0.0,
    "battery":     {"voltage_v": 0.0, "percent": 0.0},
    "running":     True,
    "emergency":   False,
    "loop":        {"hz": 0.0, "jitter_ms_max": 0.0, "jitter_ms_avg": 0.0, "cycles": 0},
}

# ─────────────────────────────────────────────
# INSTÂNCIAS
# ─────────────────────────────────────────────
motors  = MotorDriver()
battery = BatteryMonitor()
bumper  = SafetyBumper()
heading = HeadingLock()

# ─────────────────────────────────────────────
# CALLBACKS DO JOYSTICK
# ─────────────────────────────────────────────
def on_joystick_move(left_pct: float, right_pct: float):
    """Recebe comandos do joystick e envia ao motor_driver."""
    if state["mode"] != "JOYSTICK":
        return
    if state["blocked"] and left_pct > 0 and right_pct > 0:
        # Bloqueia avanço se obstáculo frontal detectado
        log.debug("[main] Avanço bloqueado — obstáculo frontal.")
        motors.stop()
        return
    motors.set_speed(left_pct, right_pct)

def on_joystick_button(button_id: int):
    """Mapeia botões do joystick para ações do sistema."""
    log.info(f"[main] Botão joystick: {button_id}")
    # Botão 0: alterna modo JOYSTICK ↔ AUTONOMO
    if button_id == 0:
        state["mode"] = "AUTONOMO" if state["mode"] == "JOYSTICK" else "JOYSTICK"
        log.info(f"[main] Modo alterado para: {state['mode']}")
        if state["mode"] == "JOYSTICK":
            motors.stop()

joystick = JoystickReader(
    move_callback=on_joystick_move,
    button_callback=on_joystick_button,
)

# ─────────────────────────────────────────────
# SERVIDOR WEB
# ─────────────────────────────────────────────
app = create_app(motors=motors, state=state)

import threading
web_thread = threading.Thread(
    target=lambda: app.run(host="0.0.0.0", port=5000, threaded=True, use_reloader=False),
    daemon=True,
    name="FlaskServer",
)

# ─────────────────────────────────────────────
# SHUTDOWN GRACIOSO
# ─────────────────────────────────────────────
def shutdown(sig=None, frame=None):
    log.info("[main] Desligando sistema...")
    state["running"] = False
    motors.stop()
    joystick.stop()
    bumper.stop()
    battery.stop()
    heading.stop()
    motors.cleanup()
    log.info("[main] Sistema encerrado.")
    sys.exit(0)

signal.signal(signal.SIGINT,  shutdown)
signal.signal(signal.SIGTERM, shutdown)

# ─────────────────────────────────────────────
# STARTUP
# ─────────────────────────────────────────────
if __name__ == "__main__":
    log.info("[main] Iniciando subsistemas...")
    battery.start()
    bumper.start()
    heading.start()
    joystick.start()
    web_thread.start()
    log.info(f"[main] Dashboard disponível em http://0.0.0.0:5000")
    log.info(f"[main] Modo MOCK: {MOCK_MODE}")
    log.info("[main] Loop de controle 50Hz iniciado. Ctrl+C para sair.")
    run_control_loop(
        state,
        motors=motors, bumper=bumper, heading=heading,
        battery=battery, joystick=joystick,
    )
