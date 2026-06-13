#!/usr/bin/env python3
"""
scripts/demo_torre.py
Demo interativo da Torre de Controle em MOCK — sem broker, sem hardware.

Sobe NO MESMO PROCESSO (compartilhando o barramento mock):
  • 3 robôs simulados (1, 2 e 3) publicando telemetria viva (bateria caindo,
    obstáculo intermitente no robô 2, LIDAR saudável alternando no robô 3)
  • A Torre de Controle em http://localhost:5100

Teste no navegador:
  1. Abra http://localhost:5100 — veja os 3 cartões atualizando
  2. Clique em ⛔ E-STOP GERAL — os 3 robôs param (cartões mostram PARADO)
  3. Clique em ✅ LIBERAR FROTA — todos voltam

Ctrl+C para sair.
"""

import os
import sys
import time
import random
import logging
import threading

os.environ["FROTA_MOCK"] = "1"

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s [%(name)s] %(levelname)s — %(message)s",
                    datefmt="%H:%M:%S")
log = logging.getLogger("demo_torre")

from fleet.link import FleetLink
from tower.main import create_tower_app
from config.settings import MQTT_BASE_TOPIC, TOWER_WEB_PORT, FLEET_TELEMETRY_S


def fake_robot(robot_id: int):
    """Thread: um robô simulado publicando telemetria e ouvindo o E-Stop."""
    state = {"fleet_estop": False}
    link = FleetLink(f"robo-{robot_id}",
                     status_topic=f"{MQTT_BASE_TOPIC}/robos/{robot_id}/status",
                     backend="mock")
    link.subscribe(
        f"{MQTT_BASE_TOPIC}/comandos/estop",
        lambda t, p: state.update(
            fleet_estop=p.strip().lower() in ("on", "1", "true")))
    link.start()

    voltage = 42.0 - robot_id            # baterias em níveis diferentes
    while True:
        voltage = max(30.0, voltage - random.uniform(0.0, 0.05))
        pct = (voltage - 30.0) / 12.0 * 100.0
        blocked = (robot_id == 2 and int(time.time()) % 10 < 3)   # robô 2 oscila
        lidar_ok = not (robot_id == 3 and int(time.time()) % 14 < 4)
        link.publish(f"{MQTT_BASE_TOPIC}/robos/{robot_id}/telemetria", {
            "robot_id": robot_id,
            "mode":     "AUTONOMO" if robot_id == 1 else "JOYSTICK",
            "battery":  {"voltage_v": round(voltage, 2), "percent": round(pct, 1)},
            "blocked":  blocked,
            "lidar":    {"healthy": lidar_ok, "fail_closed": True,
                         "last_scan_age_s": 0.1},
            "watchdog": {"mode": "mock", "armed": True, "last_pet_age_s": 0.5},
            "fleet_estop": state["fleet_estop"],
            "loop_hz":  50.0,
        })
        time.sleep(FLEET_TELEMETRY_S)


def main():
    for rid in (1, 2, 3):
        threading.Thread(target=fake_robot, args=(rid,),
                         daemon=True, name=f"FakeRobot{rid}").start()
    log.info("3 robôs simulados publicando no barramento mock.")

    app, link = create_tower_app()      # FleetLink("torre") auto → mock
    link.start()
    log.info(f"Torre de Controle: http://localhost:{TOWER_WEB_PORT}  (Ctrl+C sai)")
    try:
        from waitress import serve
        serve(app, host="0.0.0.0", port=TOWER_WEB_PORT, threads=16,
              ident="frota-torre-demo")
    except ImportError:
        app.run(host="0.0.0.0", port=TOWER_WEB_PORT,
                threaded=True, use_reloader=False)


if __name__ == "__main__":
    main()
