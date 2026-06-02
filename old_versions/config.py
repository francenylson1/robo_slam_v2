"""
Arquivo de configuração do projeto Robô Garçom Autônomo.
"""

import platform
import os

def is_raspberry_pi():
    """Verifica se está rodando em um Raspberry Pi."""
    try:
        with open('/proc/device-tree/model', 'r') as f:
            model = f.read().lower()
            return 'raspberry pi' in model
    except:
        return False

def is_development():
    """Verifica se está em ambiente de desenvolvimento."""
    return not is_raspberry_pi()

# Configurações específicas do ambiente
GPIO_AVAILABLE = is_raspberry_pi()
LIDAR_AVAILABLE = False  # Mude para True quando os sensores chegarem

# Configurações do ambiente
ENVIRONMENT_WIDTH = 6  # metros
ENVIRONMENT_HEIGHT = 12  # metros
MAP_WIDTH = int(ENVIRONMENT_WIDTH)
MAP_HEIGHT = int(ENVIRONMENT_HEIGHT)
MAP_GRID_SIZE = 0.1 # Tamanho da célula da grade em metros (10cm)
MAP_SCALE = 56.66  # pixels por metro (ajustado para mostrar grids de 0.5m com 70% de aumento)

# Configurações de segurança
EMERGENCY_STOP_DISTANCE = 0.2  # 20cm
# A margem de segurança deve ser o RAIO do robô + uma folga.
# Raio (30cm para um robô de 60cm de diâmetro) + Folga (5cm) = 35cm
FORBIDDEN_AREA_INFLATION_RADIUS = 0.35 # 35cm de margem de segurança

# Configurações do robô
ROBOT_WIDTH = 0.6                # Largura/Diâmetro do robô em metros (60cm)
ROBOT_SPEED = 0.25               # AUMENTADO para compensar atrito (era 0.15).
ROBOT_MAX_SPEED = 0.25           # Alinhado com ROBOT_SPEED.
SIMULATION_SPEED_FACTOR = 8.0    # Fator de multiplicação para a velocidade na simulação
ROBOT_TURN_SPEED = 27.0          # REDUZIDO para 30% do valor anterior (era 90.0). Velocidade de giro (graus/s).
ROBOT_ADJUSTMENT_TURN_SPEED = 0.25 # Velocidade de giro para ajustes finos (lenta e segura).

# Constante legada - Manter por compatibilidade, mas com valor seguro
ROBOT_FORWARD_SPEED = 0.25         # (LEGADO) Alinhado com ROBOT_SPEED.

ROBOT_INITIAL_POSITION = (5.7, 11.5) # (x, y) em metros - posição central na parte inferior
ROBOT_INITIAL_ANGLE = 270            # graus - apontando para cima

# Configurações de simulação
SIMULATION_TIMESTEP = 0.1  # segundos
SIMULATION_UPDATE_RATE = 10  # Hz

# Configurações de navegação
NAVIGATION_GOAL_TOLERANCE = 0.20  # 5cm - Distância para considerar que chegou (REDUZIDO DE 0.15)
NAVIGATION_ANGLE_TOLERANCE = 5.0   # REDUZIDO para 5 graus. Força um alinhamento melhor antes de avançar.
NAVIGATION_OBSTACLE_DISTANCE = 0.5  # metros

# Configurações de precisão avançada
NAVIGATION_ULTRA_PRECISION_TOLERANCE = 0.02  # (2cm) Retornando ao valor original para máxima precisão
NAVIGATION_FINE_APPROACH_DISTANCE = 0.5  # 15cm
NAVIGATION_PRECISION_APPROACH_DISTANCE = 0.10  # 8cm
NAVIGATION_ULTRA_PRECISION_ANGLE_TOLERANCE = 1.5  # graus (tolerância de ângulo ultra-precisa)

# Configurações de interface
INTERFACE_UPDATE_RATE = 10  # Hz
INTERFACE_GRID_SIZE = 1  # metros
INTERFACE_POINT_SIZE = 15  # pixels (mesmo tamanho do robô para facilitar navegação)
INTERFACE_ROBOT_SIZE = 15  # pixels
INTERFACE_DIRECTION_LENGTH = 30  # pixels

# Configurações de banco de dados
DATABASE_PATH = "data/robot.db"
DATABASE_VERSION = "1.0"

# Configurações de logging
LOG_LEVEL = "INFO"
LOG_FILE = "logs/robot.log"
LOG_FORMAT = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
LOG_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"

# Configurações de desenvolvimento
DEBUG = True
SIMULATION_MODE = True

# Configurações da interface
WINDOW_WIDTH = 1200
WINDOW_HEIGHT = 800
WINDOW_TITLE = "Robô Garçom Autônomo"

# Mensagem de ambiente (executada apenas quando o módulo é importado diretamente)
if __name__ == '__main__':
    if is_development():
        print("Executando em modo de desenvolvimento (simulação)")
    else:
        print("Executando em Raspberry Pi")
        if not LIDAR_AVAILABLE:
            print("Aviso: Sensores LIDAR não disponíveis (modo simulado)")

# Configurações do RPLIDAR
RPLIDAR_PORT = "/dev/ttyUSB0"  # Porta padrão do RPLIDAR
RPLIDAR_BAUDRATE = 115200
RPLIDAR_TIMEOUT = 1.0  # segundos

# Configurações de simulação
SIMULATION_FREQUENCY = 10.0  # Hz
SIMULATION_OBSTACLE_COUNT = 3
SIMULATION_DEFAULT_DISTANCE = 5.0  # metros

# Configurações de segurança
MIN_SAFE_DISTANCE = 0.5  # metros

# Configurações da interface
WINDOW_WIDTH = 800
WINDOW_HEIGHT = 600
WINDOW_TITLE = "Robô Garçom Autônomo"

# Configuracoes do PID e caracteristicas fisicas do robo
ROBOT_WHEEL_BASE_M = 0.075  # Distancia entre as rodas em metros (ex: 15cm)
ROBOT_WHEEL_CIRCUMFERENCE_M = 0.53 # Circunferencia da roda em metros (medida em 53cm)
ROBOT_WHEEL_RADIUS_M = ROBOT_WHEEL_CIRCUMFERENCE_M / (2 * 3.1415926535) # Raio calculado a partir da circunferencia
TICKS_PER_REVOLUTION = 90 # CORREÇÃO FUNDAMENTAL: Ajustado com base na documentação dos sensores Hall (90 pulsos por revolução).

# Limites de velocidade para o PID
# A linha abaixo foi MODIFICADA para usar ROBOT_SPEED como fonte única de verdade.
# Isso garante que a velocidade máxima seja a mesma que a velocidade de navegação.
MAX_LINEAR_SPEED_MS = ROBOT_SPEED  # Velocidade maxima para frente em metros/segundo.
MAX_ANGULAR_SPEED_RADS = 0.5