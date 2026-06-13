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
from config.settings import (
    MOCK_MODE, FLASK_HOST, FLASK_PORT, WEB_SERVER_THREADS,
    MQTT_BASE_TOPIC, FLEET_TELEMETRY_S,
)
from core.motor_driver   import MotorDriver
from core.joystick_reader import JoystickReader
from core.control_loop    import run_control_loop
from core.watchdog        import HardwareWatchdog
from fleet.link            import FleetLink
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
    "watchdog":    {"mode": None, "armed": False, "last_pet_age_s": None},
    "fleet_estop": False,   # E-STOP GERAL da frota (Torre de Controle)
    "yaw_error":   0.0,
    "battery":     {"voltage_v": 0.0, "percent": 0.0},
    "running":     True,
    "emergency":   False,
    "loop":        {"hz": 0.0, "jitter_ms_max": 0.0, "jitter_ms_avg": 0.0, "cycles": 0},
}

# ─────────────────────────────────────────────
# INSTÂNCIAS
# ─────────────────────────────────────────────
motors   = MotorDriver()
battery  = BatteryMonitor()
bumper   = SafetyBumper()
heading  = HeadingLock()
watchdog = HardwareWatchdog()

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
# TORRE DE CONTROLE (MQTT) — telemetria + E-Stop geral
# ─────────────────────────────────────────────
fleet = FleetLink(
    client_id=f"robo-{args.robot_id}",
    status_topic=f"{MQTT_BASE_TOPIC}/robos/{args.robot_id}/status",
)

def on_fleet_estop(topic: str, payload: str):
    on = str(payload).strip().lower() in ("on", "1", "true")
    state["fleet_estop"] = on
    if on:
        motors.stop()
        log.critical("[fleet] E-STOP GERAL recebido da Torre — robô parado.")
    else:
        log.info("[fleet] E-Stop geral liberado pela Torre.")

fleet.subscribe(f"{MQTT_BASE_TOPIC}/comandos/estop", on_fleet_estop)

def _fleet_telemetry_loop():
    import time as _t
    topic = f"{MQTT_BASE_TOPIC}/robos/{args.robot_id}/telemetria"
    while state.get("running", True):
        fleet.publish(topic, {
            "robot_id":    state.get("robot_id"),
            "mode":        state.get("mode"),
            "battery":     state.get("battery"),
            "blocked":     state.get("blocked"),
            "lidar":       state.get("lidar"),
            "watchdog":    state.get("watchdog"),
            "fleet_estop": state.get("fleet_estop"),
            "loop_hz":     state.get("loop", {}).get("hz"),
        })
        _t.sleep(FLEET_TELEMETRY_S)

# ─────────────────────────────────────────────
# SERVIDOR WEB
# ─────────────────────────────────────────────
app = create_app(motors=motors, state=state)

def _run_web():
    """Serve o dashboard com waitress (WSGI de produção). Fallback: dev server."""
    try:
        from waitress import serve
        log.info(f"[main] Servidor web: waitress ({WEB_SERVER_THREADS} threads).")
        serve(app, host=FLASK_HOST, port=FLASK_PORT,
              threads=WEB_SERVER_THREADS, ident="frota-mista")
    except ImportError:
        log.warning("[main] waitress ausente — usando dev server do Flask "
                    "(instale com: pip install waitress).")
        app.run(host=FLASK_HOST, port=FLASK_PORT,
                threaded=True, use_reloader=False)

import threading
web_thread   = threading.Thread(target=_run_web, daemon=True, name="WebServer")
fleet_thread = threading.Thread(target=_fleet_telemetry_loop, daemon=True,
                                name="FleetTelemetry")

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
    fleet.stop()        # publica "offline" na Torre
    watchdog.disarm()   # parada intencional não deve causar reboot
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
    fleet.start()
    fleet_thread.start()
    watchdog.arm()
    log.info(f"[main] Dashboard disponível em http://0.0.0.0:5000")
    log.info(f"[main] Modo MOCK: {MOCK_MODE}")
    log.info("[main] Loop de controle 50Hz iniciado. Ctrl+C para sair.")
    run_control_loop(
        state,
        motors=motors, bumper=bumper, heading=heading,
        battery=battery, joystick=joystick, watchdog=watchdog,
    )
