"""
web/server.py
Servidor Flask — Dashboard responsivo + stream MJPEG + WebSocket telemetria.
Sem dependência de PyQt5. Python puro + Flask + flask-sock.
"""

import time
import json
import logging
import threading

from flask import Flask, Response, render_template, jsonify, request
from flask_sock import Sock

from config.settings import MJPEG_FPS, MOCK_MODE

log = logging.getLogger(__name__)

try:
    import cv2
    CV2_OK = True
except ImportError:
    cv2 = None
    CV2_OK = False
    log.warning("[Camera] OpenCV (cv2) não disponível — stream de vídeo desativado.")

_frame_lock  = threading.Lock()
_last_frame  = None
_ws_clients  = set()
_ws_lock     = threading.Lock()


def create_app(motors, state: dict) -> Flask:
    app  = Flask(__name__, template_folder="templates", static_folder="static")
    sock = Sock(app)

    # ─────────────────────────────────────────
    # CAPTURA DE CÂMERA (thread)
    # ─────────────────────────────────────────
    def _camera_loop():
        global _last_frame
        if MOCK_MODE or not CV2_OK:
            log.info("[Camera] Modo MOCK ou sem OpenCV — sem câmera real.")
            return
        cap = cv2.VideoCapture(0)
        cap.set(cv2.CAP_PROP_FRAME_WIDTH,  640)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
        interval = 1.0 / MJPEG_FPS
        while True:
            ok, frame = cap.read()
            if ok:
                _, buf = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, 70])
                with _frame_lock:
                    _last_frame = buf.tobytes()
            time.sleep(interval)

    cam_thread = threading.Thread(target=_camera_loop, daemon=True, name="Camera")
    cam_thread.start()

    # ─────────────────────────────────────────
    # BROADCAST TELEMETRIA (thread)
    # ─────────────────────────────────────────
    def _telemetry_broadcast():
        while True:
            payload = json.dumps({
                "battery": state.get("battery", {}),
                "mode":    state.get("mode", "?"),
                "blocked": state.get("blocked", False),
                "lidar":   state.get("lidar", {}),
                "watchdog": state.get("watchdog", {}),
                "robot_id": state.get("robot_id", 1),
            })
            dead = set()
            with _ws_lock:
                clients = set(_ws_clients)
            for ws in clients:
                try:
                    ws.send(payload)
                except Exception:
                    dead.add(ws)
            if dead:
                with _ws_lock:
                    _ws_clients.difference_update(dead)
            time.sleep(5.0)

    tel_thread = threading.Thread(target=_telemetry_broadcast, daemon=True, name="Telemetry")
    tel_thread.start()

    # ─────────────────────────────────────────
    # ROTAS
    # ─────────────────────────────────────────
    @app.route("/")
    def index():
        return render_template("dashboard.html",
                                robot_id=state.get("robot_id", 1))

    @app.route("/video")
    def video():
        def generate():
            while True:
                with _frame_lock:
                    frame = _last_frame
                if frame:
                    yield (b"--frame\r\n"
                           b"Content-Type: image/jpeg\r\n\r\n"
                           + frame + b"\r\n")
                else:
                    time.sleep(0.05)
        return Response(generate(),
                        mimetype="multipart/x-mixed-replace; boundary=frame")

    @app.route("/api/status")
    def api_status():
        return jsonify({
            "robot_id": state.get("robot_id"),
            "mode":     state.get("mode"),
            "battery":  state.get("battery"),
            "blocked":  state.get("blocked"),
            "lidar":    state.get("lidar"),
            "watchdog": state.get("watchdog"),
        })

    @app.route("/api/mode", methods=["POST"])
    def api_set_mode():
        data = request.get_json(silent=True) or {}
        mode = data.get("mode", "JOYSTICK").upper()
        if mode in ("JOYSTICK", "AUTONOMO"):
            state["mode"] = mode
            if mode == "JOYSTICK":
                motors.stop()
            return jsonify({"ok": True, "mode": mode})
        return jsonify({"ok": False, "error": "Modo inválido"}), 400

    @app.route("/api/stop", methods=["POST"])
    def api_stop():
        motors.stop()
        return jsonify({"ok": True})

    # ─────────────────────────────────────────
    # WEBSOCKET — TELEMETRIA EM TEMPO REAL
    # ─────────────────────────────────────────
    @sock.route("/ws")
    def ws_telemetry(ws):
        with _ws_lock:
            _ws_clients.add(ws)
        try:
            while True:
                # Mantém conexão viva aguardando mensagem do cliente
                msg = ws.receive(timeout=30)
                if msg is None:
                    break
        except Exception:
            pass
        finally:
            with _ws_lock:
                _ws_clients.discard(ws)

    return app
