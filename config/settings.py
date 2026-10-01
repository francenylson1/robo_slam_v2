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
#
# ⚠️ CORREÇÃO DE 23/09/2026 — "segura a posição" era largo demais. Com o nível
# BAIXO a ZS-X11H faz FRENAGEM ELÉTRICA: resiste quando a roda GIRA (robô
# empurrado, como no teste de 22/09), mas NÃO trava a roda parada — girada
# devagar à mão, no ar, as duas rodas ficaram leves. O sinal chega certo às
# duas placas (medido no terminal: 0 V segurando, 3,1 V livre). Trava de
# verdade seria o pino STOP da placa, que hoje NÃO está ligado. Suficiente
# para um robô que não opera em declive; rever se um dia operar em rampa.
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
# Subido de 0,105 para 0,45 em 22/09/2026. Com 0,105 o robô precisava desviar
# 53 GRAUS para o proporcional sozinho gerar a correção que o desvio natural
# pede (~5,6%) — então quem fazia o trabalho era o integral, que é lento por
# natureza: precisa ACUMULAR erro antes de agir. O resultado era um transiente
# inicial de 20 a 26 graus, e é ele que vira desvio lateral.
HEADING_KP_PCT          = 0.45    # % de correção por grau de erro
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

# Teto do que o integral acumula, em graus·segundo. FIXO de propósito: se
# dependesse do ki (como na primeira versão, que usava max_corr/ki), reduzir o
# ganho dobraria a memória do integral e agravaria o windup em vez de aliviá-lo.
# Foi o que aconteceu em 22/09/2026 ao testar ki=0,12: o desvio final piorou de
# +4,8° para −11,4°. Com limite fixo, o ki muda só a força da correção.
# 24 graus·s. Com ki=0,25 isso dá 6% de correção — que é o teto da malha, e
# cobre toda a faixa de assimetria MEDIDA neste robô (3,90% e 6,00% em regime).
#
# Com 12 o integral só conseguia 3%, e quando a necessidade passava disso ele
# chegava ao teto sem terminar o trabalho: o erro precisava ficar diferente de
# zero para o kp complementar, e esse viés residual fazia o desvio lateral
# crescer devagar ao longo do percurso — medido em 22/09/2026, de 20 para 30 cm
# em 4,70 m.
#
# O 24 já tinha sido testado ANTES, com kp fraco (0,105), e deu sobrepasso. Com
# kp=0,45 o transiente é atacado pelo proporcional e o integral fica só com o
# viés de regime, que é o trabalho dele.
HEADING_INTEGRAL_MAX    = 24.0    # graus·s

# TRIM — a diferença entre os lados que o robô já precisa TER ao arrancar.
#
# A assimetria dos motores é conhecida e constante: o esquerdo puxa mais. Sem
# trim, o robô sai com os dois lados no mesmo comando e só corrige depois que o
# erro aparece — e esse transiente de partida é o que vira desvio lateral. Em
# 22/09/2026, com kp=0,45, os 22 cm de desvio nasceram TODOS no início; daí em
# diante ele segurou o paralelo.
#
# MEDIDO E DESCARTADO em 22/09/2026. Três percursos funcionalmente IDÊNTICOS
# deram correções em regime de +6,00% (saturada), −3,04% e +3,90%. A assimetria
# oscila numa faixa de quase 7 pontos percentuais — MAIOR que a própria
# autoridade de correção (6%) — e troca de sinal entre rodadas.
#
# Qualquer valor fixo estaria errado, com o sinal trocado, em boa parte das
# rodadas: empurraria A FAVOR do erro. Por isso o trim fica em ZERO e a
# adaptação é feita inteiramente pelo integral, que reaprende a cada reta.
#
# Não é um parâmetro a ajustar: é um caminho fechado, com medida. Só faria
# sentido se a causa da variação fosse identificada e eliminada.
HEADING_TRIM_PCT        = 0.0     # fica em zero — ver acima
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

# LIGADA desde 22/09/2026, e ligada por MEDIDA, não por convicção. Duas rodadas
# reprodutíveis de ~4,85 m com esta configuração deram 10,0 cm e 10,5 cm de
# desvio — 2,1 cm por metro, contra 111 cm/m do mesmo robô sem correção no
# começo da tarde. Cinquenta e três vezes melhor.
#
# Continua fail-soft: sem BNO085 saudável ou fora de uma reta, o comando do
# operador passa intacto. O rumo nunca BLOQUEIA o robô — quem faz isso é o
# bumper, que é fail-closed.
HEADING_ASSIST_ENABLED  = True
JOYSTICK_TIMEOUT_MS       = 200     # Leitor parado ou sem controle → para e apaga o comando
                                    # (NÃO é silêncio do manche: ver joystick_reader.timed_out)

# O receptor 2.4 GHz do iPega PG-9076 (o controle de toda a frota) muda de
# identidade quando reenumera: em 30/09/2026, depois de uma sobrecorrente no
# USB, voltou como "Nintendo Co., Ltd. Pro Controller" (e tentou antes um
# "Sony Wireless Controller"). Os eixos só foram conferidos no modo abaixo.
# Controle com outro nome é RECUSADO: o robô não anda por um mapeamento que
# ninguém conferiu, e o painel diz o motivo.
JOYSTICK_NOMES_ACEITOS    = ("shanwan Android GamePad",)
JOYSTICK_PROCURA_S        = 1.0     # sem controle: procura de novo a cada 1 s

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
AURORA_MOUNT_HEIGHT_CM    = 145    # Altura do Aurora (cm) — só registro, nenhum código lê.
                                   # Era 30 (plano de jun/2026); montado a 1,45 m desde 25/09.

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

# Reset do BNO085 pelo pino RST (23/09/2026) — ver sensors/bno_reset.py.
# O sensor às vezes acorda MUDO ao ligar o robô; um pulso baixo no RST o
# reinicia. GPIO 4 = pino físico 7 (nasce com pull-up: no boot o RST fica solto).
BNO_RESET_PIN        = 4
BNO_RESET_PULSE_S    = 0.05          # pulso baixo (provado no hardware)
BNO_RESET_ON_START   = True          # reset limpo ao iniciar o serviço
BNO_MUTE_RESET_S     = 2.0           # sem quadro por 2 s → reset automático
BNO_RESET_BACKOFF_S  = (2.0, 5.0, 10.0, 30.0)   # espera entre resets seguidos

# Interruptor de energia do BNO085 (24/09/2026) — ver sensors/bno_reset.py.
# BC327 (PNP): emissor no 3V3 (pino 1), coletor no VCC+PS0 do BNO, base por
# 1 kΩ no GPIO 7 (pino físico 26), 10 kΩ entre base e emissor.
# GPIO 7 em BAIXO = BNO ligado; solto (pull-up) = BNO sem energia. O GPIO 7
# nasce com pull-up: no boot o BNO fica desligado até o serviço ligá-lo.
# ⚠️ GPIO 7 é o CE1 do SPI: o SPI precisa estar desligado (conferir na bancada).
BNO_POWER_PIN        = 7             # None = sem interruptor (só o RST)
BNO_POWER_OFF_S      = 2.0           # tempo sem energia no corte total
BNO_POWER_CYCLE_FROM = 2             # a partir da 2ª tentativa seguida, corte total
# Referência histórica / plano B (i2c-gpio por software): endereço I2C era 0x4A

# Divisor resistivo para leitura da bateria 42V
# R1 = 100kΩ, R2 = 6.8kΩ → Vout_max = 42 * 6800/106800 = 2.67V
BATTERY_R1_OHM   = 100_000
BATTERY_R2_OHM   =   6_800
BATTERY_MAX_V    = 42.0
BATTERY_MIN_V    = 30.0
BATTERY_READ_INTERVAL_S = 5.0

# Calibração e níveis (24/09/2026). Resistores de 5% erram a razão do divisor
# em até ~10%: o fator é acertado na bancada contra o multímetro
# (fator = tensão do multímetro ÷ tensão lida com fator 1,0).
BATTERY_CAL_FACTOR     = 1.018   # 25/09/2026, robô 1: multímetro 39,8 V ÷ ADS 39,09 V
# Níveis iniciais para o pack 10S (3,3 V e 3,2 V por célula) — confirmar com o
# professor. "baixa" só avisa; "critica" recusa e cancela missão autônoma.
BATTERY_LOW_V          = 33.0
BATTERY_CRITICAL_V     = 32.0
BATTERY_HYSTERESIS_V   = 0.5     # para voltar a um nível melhor, subir 0,5 V além do limite
BATTERY_CONFIRM_READS  = 3       # leituras seguidas para mudar de nível (15 s a 5 s/leitura)
BATTERY_STALE_S        = 30.0    # sem leitura boa por 30 s → nível "desconhecida"
# Fora desta faixa a leitura é descartada: A0 solto lê ~0 V, divisor invertido
# lê acima do fundo de escala. Nenhum dos dois é a bateria.
BATTERY_VALID_MIN_V    = 20.0
BATTERY_VALID_MAX_V    = 50.0

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

# ─── GRAVADOR DE VARREDURAS DO C1 (Fase 4) ─────────────────────────────
# Decidido com o professor em 23/09/2026: antes de escolher entre localizar a
# frota com o C1 (opção B) ou com marcador no teto (opção C), observar o salão
# por semanas. O gravador copia as varreduras que o bumper já lê — ver
# sensors/scan_recorder.py. Só roda em modo REAL.
SCAN_RECORD_ENABLED  = True
SCAN_RECORD_DIR      = os.path.join(DATA_DIR, 'varreduras')
SCAN_RECORD_PERIOD_S = 1.0      # 1 varredura por segundo (~5 KB cada, ~18 MB/h — medido)
SCAN_RECORD_MAX_MB   = 2000     # ~110 h ligado; apaga as horas mais antigas

# ─── POSE DO AURORA NO SERVIÇO (Fase 4, decidido em 29/09/2026) ─────────
# Desenho completo e as palavras do professor: fim de
# docs/FASE4_ARQUITETURA_FROTA.md. Módulos: sensors/pose_source.py (regras de
# validade, iguais para qualquer fonte) e sensors/aurora_pose.py (o Aurora).
#
# SÓ O ROBÔ 1 TEM AURORA. Os demais têm só o C1: neles o módulo nem sobe — sem
# alarme, sem tentativa de conexão — e a missão fica "indisponível".
AURORA_ROBOTS        = (1,)
AURORA_IP            = "192.168.11.1"     # cabo direto; a Pi é 192.168.11.2
# Mapa de navegação = arquivo FIXO (decisão de 23/09), conferido pelo sha256
# antes de cada envio. Mapa com outro sha é recusado: trocar de mapa exige
# refazer as áreas proibidas e os POIs, então tem que ser uma decisão, não um
# arquivo sobrescrito por engano.
AURORA_MAPA          = os.path.join(DATA_DIR, 'aurora', 'mapas',
                                    'lab_metade_20260925.stcm')
AURORA_MAPA_SHA256   = "bfc257994ee362c454441603039270d1c7ff7e024794408530090ded1a7a5d51"
# A FITA de partida, no referencial do mapa (x m, y m, rumo °; convenção do
# Aurora: o rumo cresce para a ESQUERDA).
#
# MUDADA em 29/09/2026 (decisão do professor, depois da prova P1): 50 cm PARA
# A FRENTE (na direção do rumo). A fita antiga — medida na relocalização a frio
# de 28/09, (-0.0463, -0.2529, 125.8), espalhamento de 2 mm parado — ficava a
# 58 cm da M4, com margem de 50: o robô parava na beira da margem. Na nova a
# folga é de ~1,07 m. 50 cm porque o piso da sala é marcado de 50 em 50 cm.
# A posição nova foi CALCULADA (antiga + 0,50 m no rumo 125,8° =
# (-0.3388, 0.1526)); a 1ª partida nela, às 16:15 de 29/09, deu VERDE e a pose
# medida parada ficou a 2,5 cm e 1,0° do cálculo. Vale a MEDIDA, como a antiga.
#
# CONVENÇÃO "robô na fita" (combinada com o professor em 29/09/2026): a FRENTE
# da base encostada na linha, centralizada, virada para a marca de frente.
#
# ESTA REFERÊNCIA É O PONTO DO AURORA, como foi medida — NÃO o centro. Em
# 30/09/2026 o giro puro (scripts/bancada_pivo.py) mostrou que o ponto que o
# Aurora reporta fica ~9 cm fora do eixo de giro (AURORA_BRACO_M, abaixo). O
# main.py converte esta referência para o CENTRO com o mesmo braço
# (fita_do_centro), e toda pose do Aurora também — a base passa a ser o centro
# verdadeiro, 30 cm atrás da linha.
AURORA_FITA          = (-0.3430, 0.1277, 126.8)

# Onde o ponto do Aurora fica em relação ao CENTRO DE GIRO (frente, esquerda),
# em metros. Medido em 30/09/2026 com giro puro a 8%, Aurora a ~10 Hz:
#   esquerda: −5,1 / +6,5 cm (178 poses, resíduo 1,0 cm)
#   direita:  −5,6 / +7,9 cm (362 poses, resíduo 1,4 cm)
# Os dois sentidos concordam (1 cm) → não é roda rendendo mais: é o ponto do
# Aurora. A trena dá a CAIXA 4 cm atrás do eixo e centrada — a origem da pose
# do SDK não é o centro da caixa (provável: uma das câmeras). Vale a medida.
# Trocou o suporte ou a posição do Aurora? MEDIR DE NOVO (bancada_pivo.py).
AURORA_BRACO_M       = (-0.053, 0.072)
AURORA_FITA_TOL_M    = 0.15    # depois de relocalizar, tem que cair aqui perto...
AURORA_FITA_TOL_DEG  = 5.0     # ...senão relocalizou no lugar errado
AURORA_POLL_S        = 0.1     # o Aurora entrega ~10 poses/s (medido em 25/09)
AURORA_RECONNECT_BACKOFF_S = (1.0, 2.0, 5.0, 10.0)
AURORA_PARTIDA_LIMITE_S    = 60.0   # a inicialização já levou >15 s (25/09)
# Gravar o LASER do Aurora (a 1,45 m) junto das varreduras do C1 (campo "a145"
# do gravador), 1 volta por segundo; 0 desliga. Decidido em 01/10/2026: medir
# com dados reais se um C1 a 1,45 m localizaria os robôs sem Aurora (a
# simulação no próprio mapa deu ~2 cm, otimista por construção).
# DESLIGADO em 01/10/2026 à tarde (decisão do professor): a leitura do laser
# roda na MESMA thread da pose e a envelhece — idade máxima foi de ≤0,20 s
# para 0,39 s com a Pi quente, e 3 missões cancelaram por "pose velha
# (0.30 s)". Religar só depois de tirar a leitura dessa thread (conversa de
# desenho). Já há 46 min gravados (16:12–16:58 de 01/10).
AURORA_LASER_GRAVAR_S      = 0

# Regras de validade da pose (valem para qualquer fonte de pose).
POSE_MAX_IDADE_S        = 0.5   # assistivo: a pose só informa
POSE_MAX_IDADE_MISSAO_S = 0.3   # missão: a 12%, 0,3 s = ~6,5 cm às cegas
# Salto impossível: a 15% o robô não passa de ~30 cm/s (~3 cm por leitura).
POSE_SALTO_M            = 0.25
POSE_SALTO_DEG          = 15.0
POSE_ESTAVEL_S          = 1.0   # depois de um salto, 1 s estável para voltar a valer
POSE_AQUECIMENTO_S      = 1.0   # o 1º segundo após conectar traz (0,0,0) e saltos

# ─── ÁREAS PROIBIDAS E POIs (Fase 4) — desenhados pelo OPERADOR ─────────
# Decidido em 29/09/2026: o operador desenha no dashboard (/mapa, com login)
# só o OBJETO REAL; a margem é do sistema. Ver slam/mapa_nav.py.
NAV_DIR              = os.path.join(DATA_DIR, 'navegacao')   # fora do git
# A planta é gerada na bancada por scripts/aurora_planta.py, ao lado do mapa.
AURORA_PLANTA_JSON   = os.path.splitext(AURORA_MAPA)[0] + '_planta.json'
# Margem em volta de cada área: o raio que o robô varre ao girar (36,6 cm,
# medido em 28/09) + folga de localização (o Aurora erra 5–8 cm na sala).
# Proposta de 28/09: 47–52 cm. PROVISÓRIO até medir os corredores reais.
NAV_MARGEM_M         = 0.50

# ─── MISSÃO "vá até o POI X" (Fase 4, decidida em 29/09/2026) ──────────
# Ver slam/missao.py e o fim de docs/FASE4_ARQUITETURA_FROTA.md.
MISSAO_TETO_PCT         = 12.0   # abaixo do teto de 15% da Regra Nº 0
MISSAO_RETO_PCT         = 12.0   # ~21,7 cm/s (medido em 22/09)
MISSAO_APROX_PCT        = 8.0    # ~8,8 cm/s; abaixo de 8% o robô não anda previsível
# A malha de rumo da missão nunca leva uma roda abaixo disto no reto (30/09/2026:
# a correção levava a roda lenta a 3%, ela parava e o robô "costurava" ±16°).
MISSAO_RODA_MIN_PCT     = 8.0
MISSAO_APROX_M          = 0.60   # últimos 60 cm a 8% (P3: com 40 cm ainda chegava a ~19 cm/s)
# P3 (29/09): parando NA linha do ponto, a inércia levou 7 cm (Aurora) / 9 cm
# (trena) além. Para 6 cm antes, como no giro (que para 25° antes).
MISSAO_PARADA_ANTECIPA_M = 0.06
MISSAO_CHEGADA_M        = 0.15   # o Aurora erra 5–8 cm na sala
MISSAO_CHEGADA_BASE_M   = 0.10   # na base, mais justo: fica pronto para a fita
# Giro no lugar — MEDIDO na prova P2 (29/09/2026, scripts/bancada_giro.py):
#   10% contínuo: 45–75 °/s e +39° de INÉRCIA depois de parar (erro 34°)
#    8% contínuo: 27–61 °/s e +15° de inércia (erro 10°)
#    8% parando 25° ANTES: a inércia leva até o alvo (erro 3,7° e 4,5°)
#   pulso de 0,12 s a 8%: 0–1° (não vence o atrito); de 0,25 s: ~3,3° cada
# Por isso: contínuo a 8% até faltarem 25°, espera 1 s a inércia acabar e
# termina com pulsos de 0,25 s. O robô é pesado e gira sobre o centro.
MISSAO_GIRO_PCT         = 8.0    # contínuo (10% passava do ponto em 34°)
MISSAO_GIRO_FINO_PCT    = 8.0    # pulsos
MISSAO_GIRO_FINO_DEG    = 20.0   # só o padrão do script de bancada
MISSAO_GIRO_ANTECIPA_DEG = 25.0  # para o contínuo quando faltar isto
# Volta do P-quina (29/09 18:31): no canto, o giro contínuo a 8% começou a
# ~12 °/s e caiu a ~2 °/s (no piso aberto da P2: ~30 °/s) — "sem avanço". O
# giro contínuo agora REGULA a velocidade medida pelo BNO: abaixo de 10 °/s
# sobe 1% (até 12%); acima de 35 °/s desce (piso de 8%; 10% a 45–75 °/s
# passava 39° do alvo).
MISSAO_GIRO_VEL_MIN_DPS = 10.0
MISSAO_GIRO_VEL_MAX_DPS = 35.0
MISSAO_GIRO_PCT_MAX     = 12.0
MISSAO_GIRO_AJUSTE_S    = 0.5    # a cada meio segundo mede e ajusta
MISSAO_GIRO_ESPERA_S    = 1.0    # a inércia do contínuo acaba em < 1 s
MISSAO_GIRO_PULSO_S     = 0.25   # duração do 1º pulso; os seguintes se ajustam
# Volta do P-quina (29/09 18:16): no canto, cada pulso de 0,25 s rendeu só ~1°
# (na P2 eram ~3,3°) e 15 pulsos acabaram a 9° do alvo. O ganho do pulso muda
# com piso, posição e bateria: depois de cada pulso a missão mede quantos
# graus ele rendeu e ajusta a duração do próximo ao que falta.
MISSAO_GIRO_PULSO_MIN_S = 0.15
MISSAO_GIRO_PULSO_MAX_S = 0.45
# Pulso de duração máxima que rende menos que isto → o próximo sobe 1% (até
# MISSAO_GIRO_PCT_MAX); passou do ponto → desce 1% (até 8%). 30/09/2026: num
# ponto da sala, 25 pulsos a 8% renderam < 1° cada e a missão desistiu.
MISSAO_GIRO_PULSO_POUCO_DEG = 1.0
MISSAO_GIRO_PULSO_GANHO = 13.0   # °/s de pulso esperado no começo (P2: 3,3° em 0,25 s)
MISSAO_GIRO_PAUSA_S     = 0.5
MISSAO_GIRO_MAX_PULSOS  = 25     # pulsos adaptativos: mais que isso algo está errado
MISSAO_GIRO_TOL_DEG     = 5.0    # aceitação
MISSAO_GIRO_ALVO_DEG    = 3.0    # os pulsos miram aqui, para sobrar folga até os 5°
MISSAO_GIRO_MAX_TENT    = 3      # correções de mira seguidas antes de desistir
MISSAO_ASSENTAR_S       = 0.5    # parado entre fases, antes de conferir
MISSAO_MIRA_S           = 0.5    # o Aurora corrige a mira a cada 0,5 s
MISSAO_REMIRAR_DEG      = 20.0   # erro de mira maior que isso no reto: para e gira
# 2ª P3 (29/09, 16:38): o rumo balançou de 118° a 142° no reto e, a 30 cm do
# ponto, "mira fora de 20°" o fez parar e tentar girar para um ponto que já
# estava a 8 cm — girou à toa até desistir. Perto do alvo a direção muda a
# cada centímetro: a mira congela nos últimos 50 cm, cada correção é pequena,
# e a menos de 25 cm o ponto conta como alcançado (não se gira para ele).
MISSAO_MIRA_MIN_M       = 0.50   # abaixo disso a mira não mexe (e não se remira)
MISSAO_MIRA_PASSO_DEG   = 3.0    # correção máxima da referência por atualização
MISSAO_MIRA_ZONA_DEG    = 1.5    # diferença menor que isso: não mexe
# P5 (29/09 17:44): com 25 cm aqui e 15 de tolerância, o robô a 23 cm do P5
# "alcançou" sem andar e a missão falhou. Esta distância TEM de ficar abaixo
# da tolerância de chegada (a missão ainda usa a menor das duas).
MISSAO_PERTO_M          = 0.12   # a menos disso do ponto: alcançado, sem girar
# BUMPER NO GIRO (decisão do professor em 29/09/2026, depois da P6): o C1 fica
# 30 cm à frente do centro e a margem das áreas é medida do CENTRO — perto de
# uma parede, o C1 pode estar a 20 cm dela. Girando PARADO o robô não avança
# para o que está na frente (varre um círculo de 37 cm em volta do centro), e
# o bumper de 50 cm cancelava a volta do P-quina (canto) no giro inicial.
# Girando/parado: só algo a menos de 20 cm do C1 cancela. Andando reto e no
# joystick continua OBSTACLE_STOP_DISTANCE_M (50 cm). Fail-closed mantido.
MISSAO_BUMPER_GIRO_M    = 0.20
# BUMPER NA APROXIMAÇÃO (decisão do professor em 29/09/2026, volta do
# P-quina): os pontos de curva ficam a 50 cm (do centro) das mesas; chegando
# de frente para uma, o C1 a via a 46 cm e o bumper de 50 cm cancelava antes
# do ponto. Nos últimos MISSAO_APROX_M, a 8% (~9 cm/s, para em poucos cm),
# só algo a menos de 30 cm do C1 cancela. Reto a 12% e joystick: 50 cm.
MISSAO_BUMPER_APROX_M   = 0.30
# REPLANEJAR NO PONTO DE CURVA (decisão do professor em 29/09/2026, 18:45):
# voltando do P1, a reta do ponto de curva até o próximo cruzava a margem de
# uma mesa e a missão cancelava. Agora ela replaneja de onde está (mesmas
# regras do planejador) e só para se não houver rota ou se passar deste
# número de replanejamentos na mesma missão.
MISSAO_MAX_REPLANOS     = 3

# CHEGADA À BASE (decisões do professor em 30/09/2026, depois de medir que um
# giro final de 174° escorregou o robô 11 cm — trena 3 cm antes e 11 à
# direita; o sistema viu 2,4 e 11,9):
#  B — se o último trecho chegaria mais torto que MISSAO_APROX_ALINHADO_DEG em
#      relação ao rumo da fita, a rota passa antes por um ponto a
#      MISSAO_APROX_BASE_M ATRÁS da base, na linha do rumo (como estacionar).
#      Sem espaço (área, parede), vai direto.
#  A — depois do giro final, confere a posição; fora da tolerância, corrige
#      MISSAO_CORRECOES_FINAIS vez(es); fora ainda, encerra dizendo a distância.
MISSAO_APROX_BASE_M       = 0.60
# 1ª prova (30/09 12:30): o ponto a 60 cm caiu na beira da margem da M4 e o
# robô, parando e girando ali, entrou na margem → cancelou. O ponto precisa
# de FOLGA; sem folga a 60 cm, tenta mais perto da base.
MISSAO_APROX_DISTANCIAS_M = (MISSAO_APROX_BASE_M, 0.45, 0.30)
MISSAO_APROX_FOLGA_M      = 0.15
MISSAO_APROX_ALINHADO_DEG = 30.0
MISSAO_CORRECOES_FINAIS   = 1
MISSAO_DIVERGENCIA_DEG  = 10.0   # BNO × Aurora
MISSAO_AVANCO_JANELA_S  = 3.0
MISSAO_AVANCO_MIN_M     = 0.05
MISSAO_AVANCO_MIN_DEG   = 5.0
MISSAO_ENCODER_JANELA_S = 2.0
MISSAO_ENCODER_MIN_M    = 0.10   # só compara com pelo menos 10 cm de um dos lados
MISSAO_ENCODER_RAZAO    = 0.3    # o outro lado viu menos de 30% disso → cancela
MISSAO_VEL_ESTIMADA_MS  = 0.217
MISSAO_GIRO_ESTIMADO_DPS = 15.0  # estimativa de tempo (P2: ~30 °/s contínuo + pulsos)
MISSAO_TEMPO_FOLGA_S    = 20.0   # limite = 2 × estimativa + 20 s
MISSAO_ROTA_TOL_M       = 0.15   # a rota vista no /mapa e a replanejada têm que bater
MISSAO_HISTORICO        = os.path.join(NAV_DIR, 'missoes.jsonl')
# Traço de diagnóstico dos retos, a 50 Hz, um CSV por missão (30/09/2026, para
# medir a "costura" de ±10°). Só observa. None desliga.
MISSAO_TRACO_DIR        = os.path.join(NAV_DIR, 'tracos')
BASE_NOME               = "base" # POI fixo: a fita (AURORA_FITA). Reservado no editor.

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
    # As falas da missão são por ACONTECIMENTO (uma por evento), não por
    # estado: o rosto as toca quando o número do evento muda, sem espera.
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
    # Missão (Fase 4, decisão 6 de 29/09/2026): uma fala por acontecimento.
    "missao_inicio": [
        "Estou indo!",
        "A caminho!",
        "Já vou.",
        "Vou até lá.",
    ],
    "missao_chegou": [
        "Cheguei!",
        "Pronto, cheguei.",
        "Aqui estou.",
    ],
    "missao_base": [
        "Voltando para a base.",
        "Indo para casa.",
        "Estou voltando.",
    ],
    "missao_chegou_base": [
        "Cheguei na base.",
        "De volta!",
    ],
    "missao_perdido": [
        "Perdi minha localização. Parei.",
        "Não sei onde estou. Vou parar aqui.",
        "Me perdi. Preciso de ajuda.",
    ],
    # Caminho apertado / sem rota (29/09/2026): antes saía a fala de
    # "perdido", que estava errada para esse caso.
    "missao_apertado": [
        "O caminho ficou apertado. Parei.",
        "Não consigo passar por aqui. Parei.",
    ],
    # Parou perto do destino, fora da tolerância (30/09/2026): antes saía
    # "Estou preso. Preciso de ajuda." — errado, o robô não está preso.
    "missao_perto": [
        "Parei perto do lugar. Pode me ajudar a acertar?",
        "Cheguei quase lá. Pode me ajustar, por favor?",
        "Fiquei um pouquinho fora do ponto. Pode me ajudar?",
    ],
    "missao_preso": [
        "Estou preso. Preciso de ajuda.",
        "Não consigo sair do lugar.",
    ],
}

# ─────────────────────────────────────────────
# DISPLAYS (dual HDMI)
# ─────────────────────────────────────────────
DISPLAY_7_HDMI   = "HDMI-A-1"   # Expressão facial / carinha
DISPLAY_156_HDMI = "HDMI-A-2"   # Sinalização digital / mídia
DISPLAY_156_MUTE = True          # Áudio do 15.6" sempre mudo (speaker = placa de som USB)
