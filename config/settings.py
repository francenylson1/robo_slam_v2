"""
config/settings.py
Configuração central do Projeto Frota Mista v2.
Todos os parâmetros físicos validados foram migrados do legado robo_slam v1.
NÃO alterar os valores da seção NÚCLEO MOTOR sem teste físico no robô.
"""

import os

# ─────────────────────────────────────────────
# DETECÇÃO DE AMBIENTE (migrado de environment.py)
# ─────────────────────────────────────────────
def _detect_board() -> tuple[bool, str]:
    """
    Lê /proc/device-tree/model e identifica a placa.
    Retorna (on_pi, modelo) onde modelo ∈ {"Pi 5", "Pi 4", "outro", "PC"}.
    A numeração BCM dos pinos é idêntica entre Pi 4 e Pi 5 — o modelo serve
    apenas para log/diagnóstico e para escolher avisos de compatibilidade.
    """
    try:
        with open('/proc/device-tree/model', 'r') as f:
            model = f.read().lower()
    except Exception:
        return False, "PC"

    if 'raspberry pi' not in model:
        return False, "PC"
    if 'raspberry pi 5' in model:
        return True, "Pi 5"
    if 'raspberry pi 4' in model:
        return True, "Pi 4"
    return True, "outro"

# Override manual via ambiente (usado por `main.py --mock` e validate_phase1.py)
_force_mock = os.environ.get("FROTA_MOCK", "0") == "1"

ON_PI, PI_MODEL = _detect_board()
GPIO_AVAILABLE   = ON_PI and not _force_mock      # forçar MOCK desliga o GPIO
MOCK_MODE        = _force_mock or not ON_PI        # True em PC ou MOCK forçado

if MOCK_MODE:
    _origem = "MOCK forçado" if _force_mock else f"ambiente {PI_MODEL}"
    print(f"[config] Ambiente: DESENVOLVIMENTO ({_origem}) — motor_driver em modo MOCK.")
else:
    print(f"[config] Ambiente: RASPBERRY PI ({PI_MODEL}) — modo real ativado.")
    if PI_MODEL == "Pi 5":
        print("[config] Pi 5 detectada — GPIO via rpi-lgpio (RPi.GPIO clássica é incompatível).")

# ─────────────────────────────────────────────
# NÚCLEO MOTOR — VALORES VALIDADOS NO HARDWARE
# ⚠️  NÃO ALTERAR SEM TESTE FÍSICO NO ROBÔ ⚠️
# Fonte: robo_slam v1 / robot_motor_controller.py
# ─────────────────────────────────────────────

# Pinos GPIO (BCM) — Motor Esquerdo
PIN_DIR_E   = 5    # Direção
PIN_BREAK_E = 6    # Freio
PIN_PWM_E   = 18   # Velocidade (PWM)
PIN_HALL_E  = 16   # Encoder Hall

# Pinos GPIO (BCM) — Motor Direito
PIN_DIR_D   = 23   # Direção
PIN_BREAK_D = 24   # Freio
PIN_PWM_D   = 12   # Velocidade (PWM)
PIN_HALL_D  = 17   # Encoder Hall

# Lógica direcional validada fisicamente
# Motor Esquerdo: HIGH = frente, LOW = trás
# Motor Direito:  LOW  = frente, HIGH = trás  ← OPOSTO por design de fiação
DIR_E_FORWARD = 1   # GPIO.HIGH
DIR_E_REVERSE = 0   # GPIO.LOW
DIR_D_FORWARD = 0   # GPIO.LOW  ← ATENÇÃO: oposto ao esquerdo
DIR_D_REVERSE = 1   # GPIO.HIGH

# PWM
PWM_FREQUENCY_HZ = 20          # Frequência validada — não alterar

# Encoder Hall (polling)
HALL_POLL_INTERVAL_S  = 0.001  # 1ms → ~1000Hz de polling
HALL_DEBOUNCE_S       = 0.010  # 10ms de debounce anti-ruído
SPEED_UPDATE_INTERVAL = 0.100  # Calcula TPS a cada 100ms

# Parâmetros físicos do robô
TICKS_PER_REVOLUTION      = 20      # Ticks por volta do encoder Hall
ROBOT_WHEEL_BASE_M        = 0.60    # Distância entre rodas (60cm)
ROBOT_WHEEL_CIRCUMFERENCE_M = 0.50  # Circunferência da roda (50cm)
ROBOT_WIDTH_M             = 0.60    # Largura total do robô

# ─────────────────────────────────────────────
# REGRA DE SEGURANÇA Nº 0 — INTOCÁVEL
# ─────────────────────────────────────────────
MOTOR_MAX_POWER_PCT       = 15.0    # Teto absoluto de potência (%)
MOTOR_EMERGENCY_STOP_PCT  = 20.0    # Qualquer valor ≥ este → Emergency Stop imediato
JOYSTICK_TIMEOUT_MS       = 200     # Sem pacote do joystick → força velocidade = 0

# ─────────────────────────────────────────────
# PID — GANHOS CALIBRADOS NO ROBÔ REAL
# Fonte: robo_slam v1 — resultado de calibração física
# ─────────────────────────────────────────────
PID_KP            = 0.26
PID_KI            = 0.23
PID_KD            = 0.0
PID_OUTPUT_MIN    = -90.0
PID_OUTPUT_MAX    =  90.0
PID_LOOP_HZ       = 20            # Frequência do loop PID (20Hz = 50ms)

# ─────────────────────────────────────────────
# NAVEGAÇÃO E SLAM
# ─────────────────────────────────────────────
ROBOT_SPEED_MS            = 0.25   # Velocidade de avanço (m/s)
ROBOT_TURN_SPEED_DPS      = 27.0   # Velocidade de giro (graus/s)
ROBOT_INITIAL_POSITION    = (5.7, 11.5)   # (x, y) em metros
ROBOT_INITIAL_ANGLE_DEG   = 270           # graus — apontando para cima

GOAL_TOLERANCE_M          = 0.20   # Distância para considerar chegada (20cm)
ANGLE_TOLERANCE_DEG       = 5.0    # Tolerância angular (graus)
OBSTACLE_STOP_DISTANCE_M  = 0.50   # Para se obstáculo a esta distância
AURORA_MOUNT_HEIGHT_CM    = 30     # Altura de instalação do Aurora (cm)

# Fail-closed do bumper (Fase 1.5 — Blindagem):
# sem varredura VÁLIDA do LIDAR há mais que LIDAR_FRESH_TIMEOUT_S,
# o robô é considerado BLOQUEADO (segurança falha "fechada").
LIDAR_FRESH_TIMEOUT_S     = 0.5            # idade máxima do dado (s)
LIDAR_RECONNECT_BACKOFF_S = (1.0, 2.0, 5.0)  # esperas progressivas de reconexão

# ─────────────────────────────────────────────
# SERVIDOR WEB (Flask)
# ─────────────────────────────────────────────
FLASK_HOST       = "0.0.0.0"
FLASK_PORT       = 5000
VIDEO_STREAM_URL = "/video"
MJPEG_FPS        = 15

# Tamanhos de tela suportados (para CSS responsivo)
DISPLAY_SIZES = {
    "ultrawide_34": (3440, 1440),
    "display_156":  (1920, 1080),
    "display_7":    (1024, 600),
    "smartphone":   (390, 844),
}

# ─────────────────────────────────────────────
# I2C — BARRAMENTOS E ENDEREÇOS
# ─────────────────────────────────────────────
I2C_BUS          = 1        # Barramento I2C nativo da Pi (pinos 3 e 5)
I2C_ADDR_ADS1115 = 0x48     # ADC para telemetria de bateria
I2C_ADDR_BNO085  = 0x4A     # IMU para correção de Yaw

# Divisor resistivo para leitura da bateria 42V
# R1 = 100kΩ, R2 = 6.8kΩ → Vout_max = 42 * 6800/106800 = 2.67V
BATTERY_R1_OHM   = 100_000
BATTERY_R2_OHM   =   6_800
BATTERY_MAX_V    = 42.0
BATTERY_MIN_V    = 30.0
BATTERY_READ_INTERVAL_S = 5.0

# ─────────────────────────────────────────────
# POIs e MAPA
# ─────────────────────────────────────────────
POIS_FILE        = "data/pois.json"
MAP_FILE         = "data/map.json"
DATA_DIR         = os.path.join(os.path.dirname(__file__), '..', 'data')

# ─────────────────────────────────────────────
# ÁUDIO E EXPRESSÃO FACIAL
# ─────────────────────────────────────────────
AUDIO_DIR        = "audio"
FACE_WS_PORT     = 5001     # WebSocket da expressão facial (display 7")
SPEAKER_DEVICE   = "default"

# ─────────────────────────────────────────────
# DISPLAYS (dual HDMI)
# ─────────────────────────────────────────────
DISPLAY_7_HDMI   = "HDMI-A-1"   # Expressão facial / carinha
DISPLAY_156_HDMI = "HDMI-A-2"   # Sinalização digital / mídia
DISPLAY_156_MUTE = True          # Áudio do 15.6" sempre mudo (speaker = P2 da Pi)
