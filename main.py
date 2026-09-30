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
    MOTOR_MAX_POWER_PCT,
    HEADING_KP_PCT, HEADING_KI_PCT, HEADING_INTEGRAL_MAX, HEADING_TRIM_PCT,
    HEADING_MAX_CORR_PCT, HEADING_INVERT,
    HEADING_STRAIGHT_TOL_PCT, HEADING_ASSIST_ENABLED,
    SCAN_RECORD_ENABLED, SCAN_RECORD_DIR, SCAN_RECORD_PERIOD_S, SCAN_RECORD_MAX_MB,
    AURORA_ROBOTS, AURORA_IP, AURORA_MAPA, AURORA_MAPA_SHA256, AURORA_FITA,
    AURORA_FITA_TOL_M, AURORA_FITA_TOL_DEG, AURORA_POLL_S,
    AURORA_RECONNECT_BACKOFF_S, AURORA_PARTIDA_LIMITE_S, AURORA_BRACO_M,
    POSE_MAX_IDADE_S, POSE_SALTO_M, POSE_SALTO_DEG, POSE_ESTAVEL_S,
    POSE_AQUECIMENTO_S,
    NAV_DIR, NAV_MARGEM_M, AURORA_PLANTA_JSON,
    MISSAO_HISTORICO, BASE_NOME,
)
import config.settings as settings
from core.motor_driver   import MotorDriver
from core.joystick_reader import JoystickReader
from core.control_loop    import run_control_loop
from core.heading_assist import HeadingAssist
from core.watchdog        import HardwareWatchdog
from fleet.link            import FleetLink
from sensors.battery_monitor import BatteryMonitor
from sensors.safety_bumper   import SafetyBumper
from sensors.heading_lock    import HeadingLock
from sensors.scan_recorder   import ScanRecorder
from sensors.pose_source     import PoseValidator, NullPoseSource, fita_do_centro
from sensors.aurora_pose     import AuroraPose
from slam.mapa_nav           import NavStore
from slam.missao             import Missao
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

# Fonte de pose (Fase 4, decidido em 29/09/2026). Só o robô 1 tem Aurora; nos
# demais o módulo nem sobe — sem alarme, sem tentativa de conexão. Em MOCK
# também não: não há Aurora no PC.
#
# A pose é do CENTRO de giro (30/09/2026): o ponto do Aurora fica ~9 cm fora do
# eixo. A fonte converte cada pose e a fita é convertida aqui com o mesmo braço.
FITA_CENTRO = fita_do_centro(AURORA_FITA, AURORA_BRACO_M)
if args.robot_id in AURORA_ROBOTS and not MOCK_MODE:
    pose_source = AuroraPose(
        ip=AURORA_IP, mapa=AURORA_MAPA, mapa_sha256=AURORA_MAPA_SHA256,
        braco_m=AURORA_BRACO_M,
        validator=PoseValidator(
            fita=FITA_CENTRO, fita_tol_m=AURORA_FITA_TOL_M,
            fita_tol_deg=AURORA_FITA_TOL_DEG, max_idade_s=POSE_MAX_IDADE_S,
            salto_m=POSE_SALTO_M, salto_deg=POSE_SALTO_DEG,
            estavel_s=POSE_ESTAVEL_S, aquecimento_s=POSE_AQUECIMENTO_S),
        poll_s=AURORA_POLL_S, backoff_s=AURORA_RECONNECT_BACKOFF_S,
        partida_limite_s=AURORA_PARTIDA_LIMITE_S,
    )
else:
    pose_source = NullPoseSource()


# Áreas proibidas e POIs, desenhados pelo operador no /mapa (Fase 4).
nav = NavStore(NAV_DIR, AURORA_MAPA_SHA256, NAV_MARGEM_M,
               planta_json=AURORA_PLANTA_JSON)


class _RodasParadas:
    """Rodas paradas = nenhum pulso dos encoders há pelo menos 0,5 s.

    Lê os CONTADORES (left/right_ticks_odo), que a thread dos Hall sempre
    incrementa — inclusive com alguém empurrando o robô. O current_*_tps do
    motor_driver só é atualizado com o PID de velocidade ligado e ficava em
    zero (achado em 29/09, na P3)."""
    def __init__(self):
        self._ult = None
        self._mudou_em = 0.0

    def __call__(self) -> bool:
        import time as _t
        agora = _t.monotonic()
        cont = (motors.left_ticks_odo, motors.right_ticks_odo)
        if cont != self._ult:
            self._ult, self._mudou_em = cont, agora
        return agora - self._mudou_em >= 0.5


_rodas_paradas = _RodasParadas()


def robo_parado() -> bool:
    """Para a partida do Aurora: sem comando nos motores e rodas paradas."""
    return state.get("cmd_motores") is None and _rodas_paradas()


# A MISSÃO (Fase 4, decidida em 29/09/2026): o único caminho em que um pedido
# de rede move o robô — e só por set_speed, dentro do loop de 50 Hz. Malha de
# rumo própria (mesmos ganhos da Fase 3), separada da do joystick.
assist_missao = HeadingAssist(
    kp_pct=HEADING_KP_PCT, ki_pct=HEADING_KI_PCT,
    limite_integral=HEADING_INTEGRAL_MAX, trim_pct=HEADING_TRIM_PCT,
    max_corr_pct=HEADING_MAX_CORR_PCT, teto_pct=MOTOR_MAX_POWER_PCT,
    invert=HEADING_INVERT, tol_pct=HEADING_STRAIGHT_TOL_PCT, enabled=True,
)
missao = Missao(
    motors=motors, pose_source=pose_source, heading=heading, bumper=bumper,
    nav=nav, assist=assist_missao, state=state, cfg=settings,
    base_poi={"nome": BASE_NOME, "x": FITA_CENTRO[0], "y": FITA_CENTRO[1],
              "rumo": FITA_CENTRO[2]},
    historico=MISSAO_HISTORICO,
)


# Gravador de varreduras do C1 (Fase 4) — só em modo REAL. "mov" registra se o
# operador comandava os motores, para a comparação usar só o robô parado.
recorder = None
if SCAN_RECORD_ENABLED and not MOCK_MODE:
    recorder = ScanRecorder(
        SCAN_RECORD_DIR, period_s=SCAN_RECORD_PERIOD_S,
        max_total_mb=SCAN_RECORD_MAX_MB,
        yaw_fn=lambda: heading.yaw_deg if heading.healthy else None,
        moving_fn=lambda: state.get("cmd_motores") is not None,
        pose_fn=pose_source.pose_valida,
    )
    bumper.recorder = recorder

# ─────────────────────────────────────────────
# CALLBACKS DO JOYSTICK
# ─────────────────────────────────────────────
def on_joystick_move(left_pct: float, right_pct: float):
    """Recebe comandos do joystick e envia ao motor_driver."""
    # Mexer no joystick CANCELA a missão e devolve o controle a quem pegou
    # (decisão 3 de 29/09): é o jeito mais rápido de o supervisor assumir.
    if (left_pct or right_pct) and missao.ativa:
        missao.cancelar("o operador pegou o joystick", operador=True)
        state["mode"] = "JOYSTICK"
    if state["mode"] != "JOYSTICK":
        return
    if state["blocked"] and left_pct > 0 and right_pct > 0:
        # Bloqueia avanço se obstáculo frontal detectado
        log.debug("[main] Avanço bloqueado — obstáculo frontal.")
        state["cmd_motores"] = None
        motors.stop()
        return
    # O loop de 50 Hz precisa saber o que o operador está pedindo para poder
    # corrigir o rumo em cima disso (passo 3 do control_loop, Fase 3).
    state["cmd_motores"] = (left_pct, right_pct) if (left_pct or right_pct) else None
    motors.set_speed(left_pct, right_pct)

def on_joystick_button(button_id: int):
    """Mapeia botões do joystick para ações do sistema."""
    log.info(f"[main] Botão joystick: {button_id}")
    # Botão 0: herdado do v1, alternava JOYSTICK ↔ AUTONOMO. Em 29/09/2026
    # (P1) ele deixava o robô em "Autônomo" sem missão e o joystick mudo.
    # Agora o Autônomo só existe durante uma missão: o botão 0 só VOLTA para
    # Joystick (e, se houver missão, a cancela).
    if button_id == 0:
        if missao.ativa:
            missao.cancelar("botão do joystick", operador=True)
        if state["mode"] != "JOYSTICK":
            state["mode"] = "JOYSTICK"
            motors.stop()
            log.info("[main] Modo: JOYSTICK (botão 0).")
        else:
            log.info("[main] Botão 0: o modo Autônomo só existe durante uma missão.")

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
        missao.cancelar("E-Stop geral da frota", operador=True)
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
            "pose":        state.get("pose"),
        })
        _t.sleep(FLEET_TELEMETRY_S)

# ─────────────────────────────────────────────
# SERVIDOR WEB
# ─────────────────────────────────────────────
app = create_app(motors=motors, state=state,
                 pose_source=pose_source, parado_fn=robo_parado, nav=nav,
                 missao=missao)

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
    if recorder is not None:
        recorder.stop()
    battery.stop()
    heading.stop()
    pose_source.stop()
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
    if recorder is not None:
        recorder.start()
    bumper.start()
    heading.start()
    pose_source.start()
    joystick.start()
    web_thread.start()
    fleet.start()
    fleet_thread.start()
    watchdog.arm()
    log.info(f"[main] Dashboard disponível em http://0.0.0.0:5000")
    log.info(f"[main] Modo MOCK: {MOCK_MODE}")
    log.info("[main] Loop de controle 50Hz iniciado. Ctrl+C para sair.")
    # Malha de rumo (Fase 3). Nasce desligada em config/settings.py: só entra
    # depois da medição comparativa da reta de 2 m, com e sem correção.
    assist = HeadingAssist(
        kp_pct=HEADING_KP_PCT,
        ki_pct=HEADING_KI_PCT,
        limite_integral=HEADING_INTEGRAL_MAX,
        trim_pct=HEADING_TRIM_PCT,
        max_corr_pct=HEADING_MAX_CORR_PCT,
        teto_pct=MOTOR_MAX_POWER_PCT,
        invert=HEADING_INVERT,
        tol_pct=HEADING_STRAIGHT_TOL_PCT,
        enabled=HEADING_ASSIST_ENABLED,
    )
    log.info(f"[main] Malha de rumo: "
             f"{'LIGADA' if HEADING_ASSIST_ENABLED else 'desligada'}")

    run_control_loop(
        state,
        motors=motors, bumper=bumper, heading=heading,
        battery=battery, joystick=joystick, watchdog=watchdog,
        assist=assist, pose=pose_source, missao=missao,
    )
