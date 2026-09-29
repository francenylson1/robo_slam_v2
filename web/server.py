"""
web/server.py
Servidor Flask — Dashboard responsivo + stream MJPEG + telemetria via SSE.
Sem dependência de PyQt5. Python puro + Flask, servido por waitress em produção.

Telemetria: Server-Sent Events (/events) em vez de WebSocket — funciona sob
qualquer servidor WSGI (incluindo waitress), com reconexão automática nativa
do EventSource no navegador.
"""

import os
import time
import json
import logging
import threading

from flask import Flask, Response, render_template, jsonify, request, session, send_file

from config.settings import (AUDIO_DIR, MJPEG_FPS, MOCK_MODE, TELEMETRY_INTERVAL_S,
                             VOZ_COOLDOWN_PADRAO, VOZ_COOLDOWN_S, VOZ_FRASES,
                             AURORA_FITA)
from web.auth import init_auth, login_required, registrar_rotas

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


def create_app(motors, state: dict, pose_source=None, parado_fn=None,
               nav=None) -> Flask:
    app = Flask(__name__, template_folder="templates", static_folder="static")
    # Relê o template se o arquivo mudar: atualizar uma página (ex.: o editor
    # do /mapa) não exige reiniciar o serviço — e reiniciar custa a
    # localização do Aurora (a fita de novo).
    app.config["TEMPLATES_AUTO_RELOAD"] = True
    app.jinja_env.auto_reload = True

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
    # TELEMETRIA (payload comum a /events e /api/status)
    # ─────────────────────────────────────────
    def _telemetry() -> dict:
        with _frame_lock:
            tem_camera = _last_frame is not None
        return {
            # Carimbo do SERVIDOR. O painel usa a distância entre dois carimbos
            # para saber que a telemetria congelou — sem isso, uma conexão morta
            # deixaria "✅ Livre" na tela indefinidamente, que é o pior estado
            # possível para um painel de segurança.
            "ts":       time.time(),
            "robot_id": state.get("robot_id", 1),
            "mode":     state.get("mode", "?"),
            "battery":  state.get("battery", {}),
            "blocked":  state.get("blocked", False),
            "lidar":    state.get("lidar", {}),
            "watchdog": state.get("watchdog", {}),
            "fleet_estop": state.get("fleet_estop", False),
            "camera":   tem_camera,
            "heading":  state.get("heading", {}),
            "pose":     state.get("pose", {"fonte": None, "valida": False,
                                           "motivo": "sem fonte de pose"}),
        }

    # ─────────────────────────────────────────
    # ROTAS
    # ─────────────────────────────────────────
    # AUTENTICACAO (Fase 2). A parada de emergencia fica DE FORA de proposito —
    # ver a justificativa no cabecalho de web/auth.py.
    app.config["FROTA_AUTH"] = init_auth(app)
    registrar_rotas(app, lambda: state.get("robot_id", 1))

    @app.route("/")
    @login_required
    def index():
        return render_template("dashboard.html",
                                robot_id=state.get("robot_id", 1))

    @app.route("/video")
    @login_required
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
    @login_required
    def api_status():
        return jsonify(_telemetry())

    @app.route("/events")
    @login_required
    def events():
        """Telemetria em tempo real via Server-Sent Events (EventSource)."""
        def stream():
            while True:
                yield f"data: {json.dumps(_telemetry())}\n\n"
                time.sleep(TELEMETRY_INTERVAL_S)
        return Response(stream(), mimetype="text/event-stream",
                        headers={"Cache-Control": "no-cache",
                                 "X-Accel-Buffering": "no"})

    @app.route("/api/mode", methods=["POST"])
    @login_required
    def api_set_mode():
        data = request.get_json(silent=True) or {}
        mode = data.get("mode", "JOYSTICK").upper()
        if mode in ("JOYSTICK", "AUTONOMO"):
            state["mode"] = mode
            if mode == "JOYSTICK":
                motors.stop()
            return jsonify({"ok": True, "mode": mode})
        return jsonify({"ok": False, "error": "Modo inválido"}), 400

    # PARTIDA DO AURORA (Fase 4, decisão 4 de 29/09/2026): "Localizar na fita".
    # COM login, e só aqui (não na tela do robô). Não move o robô: só fala com
    # o Aurora, e a própria sequência aborta se o robô andar.
    @app.route("/api/aurora/partida", methods=["POST"])
    @login_required
    def api_aurora_partida():
        if pose_source is None or getattr(pose_source, "fonte", None) != "aurora":
            return jsonify({"ok": False,
                            "error": "este robô não tem Aurora"}), 400
        ok, msg = pose_source.pedir_partida(parado_fn or (lambda: False))
        return jsonify({"ok": ok, "msg": msg}), (200 if ok else 409)

    # ─────────────────────────────────────────
    # MAPA: ÁREAS PROIBIDAS E POIs (Fase 4, 29/09/2026)
    # O operador desenha no /mapa. Tudo COM login. Nada disto move o robô.
    # ─────────────────────────────────────────
    def _quem():
        return session.get("usuario") or "operador"

    @app.route("/mapa")
    @login_required
    def mapa():
        return render_template("mapa.html", robot_id=state.get("robot_id", 1))

    @app.route("/api/nav")
    @login_required
    def api_nav():
        if nav is None:
            return jsonify({"ok": False, "error": "sem mapa de navegação"}), 404
        return jsonify({"ok": True, "doc": nav.carregar(), "planta": nav.planta(),
                        "margem_m": nav.margem_m, "editando": nav.editando(),
                        # Para a planta aparecer com a parede da FRENTE (para
                        # onde o robô olha na fita) no topo da tela.
                        "rumo_frente": AURORA_FITA[2]})

    @app.route("/nav/planta.png")
    @login_required
    def nav_planta():
        p = nav.planta_png() if nav is not None else None
        if p is None:
            return jsonify({"ok": False, "error": "planta ainda não gerada"}), 404
        return send_file(p, mimetype="image/png", max_age=0)

    @app.route("/api/nav/rota")
    @login_required
    def api_nav_rota():
        """Só MOSTRA a rota da pose atual até um POI. Não move nada."""
        if nav is None:
            return jsonify({"ok": False, "motivo": "sem mapa de navegação"}), 404
        poi = nav.poi(request.args.get("poi", ""))
        if poi is None:
            return jsonify({"ok": False, "motivo": "POI não encontrado no desenho salvo"}), 404
        p = pose_source.pose_valida() if pose_source is not None else None
        if p is None:
            motivo = pose_source.motivo() if pose_source is not None else "sem fonte de pose"
            return jsonify({"ok": False, "motivo": f"a pose do robô não vale: {motivo}"}), 409
        plan = nav.planejador()
        if plan is None:
            return jsonify({"ok": False, "motivo": "planta ainda não gerada"}), 409
        pts, motivo = plan.planejar((p.x_m, p.y_m), (poi["x"], poi["y"]))
        if pts is None:
            return jsonify({"ok": False, "motivo": motivo}), 409
        from slam.planejador import comprimento
        return jsonify({"ok": True, "pontos": [[round(x, 3), round(y, 3)] for x, y in pts],
                        "comprimento_m": round(comprimento(pts), 2)})

    @app.route("/api/nav/editar", methods=["POST"])
    @login_required
    def api_nav_editar():
        if nav is None:
            return jsonify({"ok": False, "error": "sem mapa de navegação"}), 404
        acao = (request.get_json(silent=True) or {}).get("acao", "")
        ok, msg = nav.editar(acao, _quem())
        return jsonify({"ok": ok, "msg": msg}), (200 if ok else 409)

    @app.route("/api/nav", methods=["POST"])
    @login_required
    def api_nav_salvar():
        if nav is None:
            return jsonify({"ok": False, "error": "sem mapa de navegação"}), 404
        corpo = request.get_json(silent=True) or {}
        doc = corpo.get("doc")
        base = corpo.get("versao_base")
        if not isinstance(doc, dict) or not isinstance(base, int):
            return jsonify({"ok": False, "erros": ["pedido inválido"]}), 400
        ok, res = nav.salvar(doc, _quem(), base)
        if not ok:
            return jsonify({"ok": False, "erros": res}), 422
        return jsonify({"ok": True, "doc": res})

    # SEM login_required — decisao deliberada: parar o robo nunca pode
    # depender de credencial. Ver web/auth.py.
    @app.route("/api/stop", methods=["POST"])
    def api_stop():
        motors.stop()
        return jsonify({"ok": True})

    # ─────────────────────────────────────────
    # ROSTO ANIMADO (Fase 2) — tela de 7" a bordo do robô
    #
    # PÚBLICO, de propósito. A tela do próprio robô precisa acender no boot,
    # em quiosque, sem ninguém digitar senha — um rosto que pede credencial
    # não serve ao propósito. Em troca, recebe um payload REDUZIDO: só o que
    # a expressão usa. Sem câmera, sem controles, sem estado interno. Nada
    # aqui é mais revelador do que olhar para o robô.
    # ─────────────────────────────────────────
    def _rosto_dados() -> dict:
        l = state.get("lidar", {}) or {}
        b = state.get("battery", {}) or {}
        return {
            "ts":          time.time(),
            "blocked":     state.get("blocked", False),
            "nearest_deg": l.get("nearest_deg"),
            "nearest_m":   l.get("nearest_m"),
            "lidar_ok":    l.get("healthy", False),
            "bateria":     b.get("percent", 0.0),
            "modo":        state.get("mode", "?"),
            "fleet_estop": state.get("fleet_estop", False),
        }

    def _voz_config() -> dict:
        """O que o rosto precisa para falar: os arquivos que REALMENTE existem
        em disco — não a lista teórica do settings — e o silêncio de cada
        estado. Se uma geração ficou pela metade, o rosto usa o que há em vez
        de pedir um .wav que daria 404 e falharia calado."""
        cfg = {}
        for chave in VOZ_FRASES:
            try:
                arquivos = sorted(n for n in os.listdir(AUDIO_DIR)
                                  if n.startswith(f"{chave}_") and n.endswith(".wav"))
            except OSError:
                arquivos = []          # sem pasta de áudio: rosto mudo, não quebrado
            espera = VOZ_COOLDOWN_S.get(chave, VOZ_COOLDOWN_PADRAO)
            cfg[chave] = {"arquivos": arquivos, "cooldown": int(espera * 1000)}
        return cfg

    @app.route("/rosto")
    def rosto():
        # As falas e o silêncio entre repetições vêm do settings.py — a mesma
        # fonte que gerou os .wav (scripts/gerar_vozes.py). Assim não existe
        # lista de frases duplicada entre quem gera e quem toca.
        return render_template("rosto.html",
                               robot_id=state.get("robot_id", 1),
                               voz=_voz_config())

    @app.route("/rosto/eventos")
    def rosto_eventos():
        def stream():
            while True:
                yield f"data: {json.dumps(_rosto_dados())}\n\n"
                time.sleep(0.2)          # 5Hz: expressão fluida sem pesar
        return Response(stream(), mimetype="text/event-stream",
                        headers={"Cache-Control": "no-cache",
                                 "X-Accel-Buffering": "no"})

    return app
