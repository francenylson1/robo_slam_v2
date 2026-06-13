"""
tower/main.py — Torre de Controle da Frota (Fase 2.5).
Dashboard único da frota (cartão por robô) + E-STOP GERAL via MQTT.

Execução:
  Na Torre (Pi 4 dedicada, com mosquitto local):  python3 -m tower.main
  No PC (demo MOCK com robôs simulados):          python3 scripts/demo_torre.py

A Torre só ESCUTA e COORDENA — cada robô continua independente e completo;
se a Torre cair, os robôs seguem funcionando (degradação graciosa).
"""

import json
import time
import logging
import threading

from flask import Flask, Response, render_template, jsonify, request

from config.settings import (
    MQTT_BASE_TOPIC, TOWER_WEB_PORT, FLEET_TELEMETRY_S, FLASK_HOST,
    WEB_SERVER_THREADS,
)
from fleet.link import FleetLink

log = logging.getLogger(__name__)

# Robô sem telemetria há mais que isto é exibido como OFFLINE
ROBOT_STALE_S = 3 * FLEET_TELEMETRY_S


def create_tower_app(link: FleetLink | None = None):
    """Retorna (app Flask, FleetLink). link injetável p/ demo e validação."""
    app   = Flask(__name__, template_folder="templates")
    link  = link or FleetLink(client_id="torre")
    lock  = threading.Lock()
    fleet = {}                      # robot_id → {"telemetry", "status", "last_seen"}
    estop = {"on": False}

    # ─────────────────────────────────────────
    # ASSINATURAS MQTT
    # ─────────────────────────────────────────
    def _robot_id(topic: str) -> str:
        return topic.split("/")[2]      # frota/robos/<id>/...

    def on_telemetry(topic, payload):
        try:
            data = json.loads(payload)
        except Exception:
            return
        with lock:
            entry = fleet.setdefault(_robot_id(topic), {})
            entry["telemetry"] = data
            entry["last_seen"] = time.time()

    def on_status(topic, payload):
        with lock:
            entry = fleet.setdefault(_robot_id(topic), {})
            entry["status"] = payload
            entry["last_seen"] = time.time()

    def on_estop_echo(topic, payload):
        # Mantém o estado do botão coerente mesmo se outro cliente acionar
        estop["on"] = str(payload).strip().lower() in ("on", "1", "true")

    link.subscribe(f"{MQTT_BASE_TOPIC}/robos/+/telemetria", on_telemetry)
    link.subscribe(f"{MQTT_BASE_TOPIC}/robos/+/status",     on_status)
    link.subscribe(f"{MQTT_BASE_TOPIC}/comandos/estop",     on_estop_echo)

    # ─────────────────────────────────────────
    # SNAPSHOT DA FROTA
    # ─────────────────────────────────────────
    def _snapshot() -> dict:
        now = time.time()
        robots = {}
        with lock:
            for rid, entry in fleet.items():
                age = (now - entry["last_seen"]) if "last_seen" in entry else None
                online = (entry.get("status") != "offline"
                          and age is not None and age <= ROBOT_STALE_S)
                robots[rid] = {
                    "telemetry": entry.get("telemetry", {}),
                    "online":    online,
                    "age_s":     None if age is None else round(age, 1),
                }
        return {"estop": estop["on"], "robots": robots}

    # ─────────────────────────────────────────
    # ROTAS
    # ─────────────────────────────────────────
    @app.route("/")
    def index():
        return render_template("torre.html")

    @app.route("/api/frota")
    def api_frota():
        return jsonify(_snapshot())

    @app.route("/events")
    def events():
        def stream():
            while True:
                yield f"data: {json.dumps(_snapshot())}\n\n"
                time.sleep(1.0)
        return Response(stream(), mimetype="text/event-stream",
                        headers={"Cache-Control": "no-cache"})

    @app.route("/api/estop", methods=["POST"])
    def api_estop():
        data = request.get_json(silent=True) or {}
        on   = bool(data.get("on", True))
        estop["on"] = on
        # retained: robô que conectar DEPOIS do acionamento também recebe
        link.publish(f"{MQTT_BASE_TOPIC}/comandos/estop",
                     "on" if on else "off", retain=True)
        log.critical(f"[Torre] E-STOP GERAL {'ACIONADO' if on else 'liberado'}.")
        return jsonify({"ok": True, "estop": on})

    return app, link


def main():
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s [%(name)s] %(levelname)s — %(message)s",
                        datefmt="%H:%M:%S")
    app, link = create_tower_app()
    link.start()
    log.info(f"[Torre] Dashboard da frota em http://0.0.0.0:{TOWER_WEB_PORT}")
    try:
        from waitress import serve
        serve(app, host=FLASK_HOST, port=TOWER_WEB_PORT,
              threads=WEB_SERVER_THREADS, ident="frota-torre")
    except ImportError:
        app.run(host=FLASK_HOST, port=TOWER_WEB_PORT,
                threaded=True, use_reloader=False)


if __name__ == "__main__":
    main()
