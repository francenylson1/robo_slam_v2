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
# 45 é o valor que o professor MEDIU no v1 ("VALOR CALIBRADO: Medido
# experimentalmente em 45 ticks por volta completa da roda",
# ~/robo_slam/src/core/config.py). A migração para o v2 trouxe 20 — fator de
# 2,25 de erro, corrigido em 22/09/2026. É a base da odometria da Fase 4 e de
# qualquer conversão TPS ↔ metros.
TICKS_PER_REVOLUTION      = 45      # Ticks por volta do encoder Hall (medido)
ROBOT_WHEEL_BASE_M        = 0.60    # Distância entre rodas (60cm)
ROBOT_WHEEL_CIRCUMFERENCE_M = 0.50  # Circunferência da roda (50cm)
ROBOT_WIDTH_M             = 0.60    # Largura total do robô

# ─────────────────────────────────────────────
# REGRA DE SEGURANÇA Nº 0 — INTOCÁVEL
# ─────────────────────────────────────────────
MOTOR_MAX_POWER_PCT       = 15.0    # Teto absoluto de potência (%)
MOTOR_EMERGENCY_STOP_PCT  = 20.0    # Qualquer valor ≥ este → Emergency Stop imediato

# ─── RETENÇÃO AO PARAR (Fase 3, 22/09/2026) ──────────────────────────
# O pino chamado "BREAK" no v1 e no v2 NÃO é um freio: é um ENABLE de lógica
# invertida. Provado fisicamente empurrando o robô, com PWM em zero e cada
# nível segurado por 90 s:
#     nível BAIXO → driver LIGADO    → roda TRAVADA (segura a posição)
#     nível ALTO  → driver DESLIGADO → roda LIVRE
# O código antigo punha ALTO ao parar. Resultado: o robô ficava solto toda vez
# que parava, e um processo morto o deixava em ponto morto — o oposto do que a
# Fase 1.5 documentava como provado. Ler o pino não provava o efeito.
BRAKE_LEVEL_HOLD = 0        # GPIO.LOW  — segura
BRAKE_LEVEL_FREE = 1        # GPIO.HIGH — solta

# Quanto tempo segurar depois de parar. Decisão do professor em 22/09/2026:
# segurar a parada curta e soltar na espera longa, porque driver ligado consome
# e aquece o motor — e este robô não opera em declive ("ainda não observei o
# robô sair descendo sozinho"). Se um dia operar em rampa, isto vira 0, que
# significa SEGURAR SEMPRE.
BRAKE_HOLD_S = 30.0

# ─── MALHA DE RUMO (Fase 3) ──────────────────────────────────────────
# O robô anda reto fechando a malha com o BNO085. Algoritmo e constantes vêm do
# v1 (~/robo_slam/src/core/config.py), que já roda neste robô:
#     BNO_STRAIGHT_KP                 = 0.35   TPS por grau de erro
#     BNO_STRAIGHT_MAX_CORRECTION_TPS = 8.0    saturação
#     BNO_STRAIGHT_INVERT_CORRECTION  = True   o sinal É invertido neste robô
#
# Aqui a correção é em POTÊNCIA (%), não em TPS, porque o caminho por TPS exige
# os dois encoders e o direito está com defeito físico (docs/ETAPA_B_ENCODERS.md).
# A conversão usa a tabela do próprio v1: 50 TPS ↔ 15% de potência, ou seja
# 0,3 %/TPS.
#     kp:   0,35 TPS/grau × 0,3 %/TPS = 0,105 %/grau
#     satura: 8 TPS      × 0,3 %/TPS = 2,4 %
# Proporcionalmente dá a mesma autoridade do v1: ~30% da potência base.
# Estes dois valores são os que se ajusta na bancada, medindo a reta de 2 m.
HEADING_KP_PCT          = 0.105   # % de correção por grau de erro
#
# O INTEGRAL é o que resolve este robô, e não veio do v1.
# Medido em 22/09/2026, percurso de 6 s a 8%:
#     sem correção  → desvio de 40,5° (6,75°/s)
#     com P puro    → desvio de 23,0°, e a correção SATUROU em 2,4%
# Conta: 2,4% de diferença entre as rodas compra 2,9°/s; para cancelar 6,75°/s
# seriam ~5,6%. Faltava mais que o dobro de autoridade.
#
# Mas só aumentar o limite não bastaria: a assimetria dos motores é uma
# perturbação CONSTANTE, e contra ela o proporcional puro SEMPRE deixa resíduo —
# ele só age enquanto o erro existe. O integral acumula o erro persistente e
# aprende a compensá-lo. O v1 não precisava disso porque tinha o PID de
# velocidade por roda embaixo; nós não temos (exige os dois encoders).
HEADING_KI_PCT          = 0.25    # % de correção por grau·segundo acumulado
HEADING_MAX_CORR_PCT    = 6.0     # saturação (era 2,4 e saturava o tempo todo)
# ATENÇÃO — NÃO copiar o True do v1. Os dois yaw têm SINAIS OPOSTOS:
#   v1: calcula o yaw do quaternion por I²C, atan2(siny_cosp, cosy_cosp) —
#       convenção matemática, girar para a ESQUERDA aumenta. Por isso ele
#       precisa de BNO_STRAIGHT_INVERT_CORRECTION = True.
#   v2: lê UART-RVC direto do sensor. Medido em 21/09/2026: girar para a
#       DIREITA aumenta o yaw. Convenção oposta → aqui o invert é False.
# Com True, a correção empurraria NA DIREÇÃO do erro (realimentação positiva) e
# o robô faria uma espiral em vez de endireitar. Há verificação no harness que
# fixa a física: desvio para a direita → a roda DIREITA acelera.
HEADING_INVERT          = False   # CONFIRMAR na bancada com o teste RUMO
HEADING_STRAIGHT_TOL_PCT = 1.0    # diferença máx. entre os lados p/ ser "reta"

# Nasce DESLIGADA: a malha só entra depois da medição comparativa (mesma reta
# com e sem correção). Ligar sem medir seria acreditar, não provar.
HEADING_ASSIST_ENABLED  = False
JOYSTICK_TIMEOUT_MS       = 200     # Sem pacote do joystick → força velocidade = 0

# ─────────────────────────────────────────────
# PID — GANHOS CALIBRADOS NO ROBÔ REAL
# Fonte: robo_slam v1 — resultado de calibração física
# ─────────────────────────────────────────────
PID_KP            = 0.26
PID_KI            = 0.23
PID_KD            = 0.0
# ATENÇÃO — estes limites estão AMARRADOS ao teto da Regra Nº 0, de propósito.
#
# Estavam em ∓90.0 e isso era um bloqueador: a saída do PID vai para
# _apply_safety_clip(), e ≥20% não é cortado — é EMERGENCY STOP. Com Ki=0,23 e
# um degrau de 35 TPS, a saída passa de 20% em poucos ciclos, e o robô travaria
# na primeira vez que alguém usasse set_target_speed_tps(). (Encontrado em
# 22/09/2026, auditando a Fase 3 antes de mover o robô.)
#
# No v1 o PID era limitado por perfil de velocidade — (-8,8), (-12,12),
# (-15,15) — e saturava no teto em vez de ultrapassá-lo. É o comportamento
# certo: a Regra Nº 0 é a rede de segurança para BUGS, não um obstáculo na
# operação normal.
PID_OUTPUT_MIN    = -MOTOR_MAX_POWER_PCT
PID_OUTPUT_MAX    =  MOTOR_MAX_POWER_PCT
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

# ⚠️ VALIDADO NO HARDWARE (21/09/2026) — RPLIDAR C1:
# O C1 usa 460800 baud, NÃO os 115200 dos A1/A2 (que é o padrão da biblioteca
# rplidar). Com o baud errado o handshake falha em "Descriptor length mismatch".
# Confirmado na Pi: model=65 (0x41=C1), firmware 1.2, health Good, ~13.8Hz e
# ~275 pontos por varredura.
LIDAR_BAUDRATE            = 460800

# ─────────────────────────────────────────────
# WATCHDOG (Fase 1.5 — Blindagem)
# O loop 50Hz alimenta o watchdog; se o processo travar, o serviço é
# reiniciado (systemd) ou a Pi reinicia (hardware) — freios voltam ao
# estado seguro (BREAK=HIGH é o estado inicial do motor_driver).
# ─────────────────────────────────────────────
WATCHDOG_DEVICE         = "/dev/watchdog"  # watchdog de hardware da Pi (BCM27xx)
WATCHDOG_TIMEOUT_S      = 15.0   # janela de disparo (HW da Pi: máx 15s); usada no MOCK
WATCHDOG_PET_INTERVAL_S = 1.0    # alimentação a cada 1s (15x de folga p/ o loop 50Hz)

# ─────────────────────────────────────────────
# SERVIDOR WEB (Flask)
# ─────────────────────────────────────────────
FLASK_HOST       = "0.0.0.0"
FLASK_PORT       = 5000
VIDEO_STREAM_URL = "/video"
MJPEG_FPS        = 15
WEB_SERVER_THREADS    = 16    # waitress: streams (MJPEG/SSE) seguram 1 thread cada

# ─────────────────────────────────────────────
# AUTENTICAÇÃO DO DASHBOARD (Fase 2 — Interface PRO)
# O dashboard comanda motores numa rede compartilhada, então a autenticação
# vem LIGADA. Sem senha configurada, o sistema sorteia uma e a publica no log
# em vez de ficar aberto — ver web/auth.py.
# Configurar de forma permanente: python3 scripts/set_web_password.py
# (grava FROTA_WEB_USER e FROTA_WEB_PASSWORD_HASH em /etc/frota.conf)
# ─────────────────────────────────────────────
WEB_AUTH_ENABLED   = os.environ.get("FROTA_WEB_AUTH", "1") == "1"
WEB_USER           = os.environ.get("FROTA_WEB_USER", "operador")
WEB_PASSWORD_HASH  = os.environ.get("FROTA_WEB_PASSWORD_HASH", "").strip()
WEB_SESSION_HORAS  = int(os.environ.get("FROTA_WEB_SESSION_HORAS", "12"))
TELEMETRY_INTERVAL_S  = 2.0   # período de emissão da telemetria SSE (/events)

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
# Barramento I2C nº 1: SDA = GPIO 2 (pino FÍSICO 3) | SCL = GPIO 3 (pino FÍSICO 5)
# ⚠️ Não confundir: "GPIO 5" (BCM) é o PIN_DIR_E do motor (pino físico 29).
I2C_BUS          = 1
I2C_ADDR_ADS1115 = 0x48     # ADC para telemetria de bateria (não faz clock stretching — OK)

# ─────────────────────────────────────────────
# BNO085 (GY-BNO08x) — UART-RVC, NÃO MAIS I2C
# O I2C de hardware da Pi tem bug de clock stretching e o BNO085 (SHTP) o usa
# intensamente → travamentos. Solução adotada: modo UART-RVC (PS0=3V3, PS1=GND):
# o sensor transmite Yaw/Pitch/Roll prontos a 100Hz, 115200 baud, pelo pino SDA
# (que vira TX) → GPIO15/RXD da Pi. Fiação e setup: docs/BNO085_UART_RVC.md
# ─────────────────────────────────────────────
BNO_UART_PORT = "/dev/serial0"   # symlink válido na Pi 4 e na Pi 5
BNO_UART_BAUD = 115200
# Referência histórica / plano B (i2c-gpio por software): endereço I2C era 0x4A

# Divisor resistivo para leitura da bateria 42V
# R1 = 100kΩ, R2 = 6.8kΩ → Vout_max = 42 * 6800/106800 = 2.67V
BATTERY_R1_OHM   = 100_000
BATTERY_R2_OHM   =   6_800
BATTERY_MAX_V    = 42.0
BATTERY_MIN_V    = 30.0
BATTERY_READ_INTERVAL_S = 5.0

# ─────────────────────────────────────────────
# TORRE DE CONTROLE — MQTT (Fase 2.5)
# Broker mosquitto roda NA TORRE (offline, rede local). Cada robô publica
# telemetria e escuta comandos; sem broker, o robô segue 100% funcional
# (fail-soft — a Torre é opcional por design).
# Tópicos:
#   frota/robos/<id>/telemetria  ← robô publica (JSON, a cada FLEET_TELEMETRY_S)
#   frota/robos/<id>/status      ← "online"/"offline" (retained + LWT)
#   frota/comandos/estop         ← Torre publica "on"/"off" (retained)
# ─────────────────────────────────────────────
MQTT_HOST         = os.environ.get("FROTA_MQTT_HOST", "127.0.0.1")  # IP da Torre
MQTT_PORT         = 1883
MQTT_KEEPALIVE_S  = 15
MQTT_BASE_TOPIC   = "frota"
FLEET_TELEMETRY_S = 2.0     # período de publicação da telemetria do robô
TOWER_WEB_PORT    = 5100    # dashboard da frota (na Torre)

# ─────────────────────────────────────────────
# POIs e MAPA
# ─────────────────────────────────────────────
POIS_FILE        = "data/pois.json"
MAP_FILE         = "data/map.json"
DATA_DIR         = os.path.join(os.path.dirname(__file__), '..', 'data')

# ─────────────────────────────────────────────
# ÁUDIO E EXPRESSÃO FACIAL
# ─────────────────────────────────────────────
AUDIO_DIR        = os.path.join(os.path.dirname(__file__), '..', 'web', 'static', 'audio')
FACE_WS_PORT     = 5001     # WebSocket da expressão facial (display 7")
SPEAKER_DEVICE   = "default"   # saída padrão do PipeWire (hoje: placa USB)

# ─── A VOZ (Fase 2) ───────────────────────────────────────────────────
# As frases são GERADAS ANTES, na bancada (scripts/gerar_vozes.py), e
# versionadas como .wav. O robô só TOCA.
#
# Por que não sintetizar na hora: medido na Pi 5 em 22/09/2026, o Piper leva
# ~4 s para produzir uma frase de 2 s (a maior parte é carregar o modelo).
# Um "Com licença!" que sai 4 segundos depois de alguém já estar na frente do
# robô não é um aviso, é um comentário. E o loop de 50 Hz não pode disputar
# CPU com uma rede neural.
#
# Consequência boa: o Piper NÃO entra no requirements.txt. É ferramenta de
# bancada; os 10 robôs da frota recebem só os .wav prontos pelo git.
VOZ_MODELO       = "pt_BR-faber-medium"   # escolhida de ouvido em 22/09/2026

# Quanto tempo de silêncio antes de repetir a fala do MESMO estado.
# Não é um número só de propósito: os estados têm naturezas diferentes.
#   licenca — situação passageira (alguém cruzou a frente). Precisa ser
#             rápido, senão o pedido chega depois de a pessoa já ter saído.
#   cego    — falha; o robô já está parado. Avisar de vez em quando basta.
#   bateria — condição PERMANENTE até alguém carregar. Com 8s aqui, o robô
#             passaria meia hora reclamando a cada 8 segundos. 3 minutos.
#   estop   — evento raro e sério; não precisa de insistência.
VOZ_COOLDOWN_S = {
    "licenca":  8.0,
    "cego":    30.0,
    "bateria": 180.0,
    "estop":   20.0,
}
VOZ_COOLDOWN_PADRAO = 15.0   # para uma chave nova que esqueçam de listar

# chave → LISTA de jeitos de dizer a mesma coisa.
#
# Por que uma lista: um robô garçom num evento de 4 horas passa por gente o
# tempo todo. Repetir "Com licença!" com a mesma entonação centenas de vezes
# cansa os convidados e desmancha a graça — foi o próprio professor quem
# notou, ouvindo. O rosto sorteia uma variação e NUNCA repete a última que
# usou, então o mesmo texto só volta depois de dar a volta nas outras.
#
# 'licenca' é a fala do dia a dia e ganha mais variações. 'estop' tem UMA só,
# de propósito: um aviso de emergência que muda de texto a cada vez fica mais
# difícil de reconhecer — aqui, previsibilidade é uma qualidade.
#
# Mudou esta lista? Rode scripts/gerar_vozes.py de novo. Cada frase vira um
# arquivo numerado (licenca_01.wav, licenca_02.wav, ...).
VOZ_FRASES = {
    "licenca": [
        "Com licença!",
        "Com licença, por favor.",
        "Dá licença!",
        "Opa! Com licença.",
        "Posso passar?",
        "Com licencinha!",
        "Oi! Preciso passar.",
        "Com licença, estou passando.",
        "Por favor, me dá passagem?",
        "Chegando! Com licença.",
    ],
    "cego": [
        "Não estou enxergando.",
        "Estou sem enxergar. Vou parar aqui.",
        "Perdi minha visão. Preciso de ajuda.",
    ],
    "bateria": [
        "Preciso carregar.",
        "Minha bateria está acabando.",
        "Estou ficando sem energia.",
        "Preciso de uma recarga.",
    ],
    "estop": [
        "Parada geral.",
    ],
}

# ─────────────────────────────────────────────
# DISPLAYS (dual HDMI)
# ─────────────────────────────────────────────
DISPLAY_7_HDMI   = "HDMI-A-1"   # Expressão facial / carinha
DISPLAY_156_HDMI = "HDMI-A-2"   # Sinalização digital / mídia
DISPLAY_156_MUTE = True          # Áudio do 15.6" sempre mudo (speaker = P2 da Pi)
