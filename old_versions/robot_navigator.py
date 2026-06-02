import sys
import os

# Adiciona o diretório raiz ao PYTHONPATH
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

import time
import math
from typing import List, Tuple, Optional
from PyQt5.QtCore import QObject, pyqtSignal
from .slamtec_manager import SlamtecManager
from .robot_motor_controller import RobotMotorController
from .config import *
from src.core.environment import GPIO_AVAILABLE, is_raspberry_pi
from .path_finder import PathFinder

class RobotNavigator(QObject):

    # Sinal para notificar a UI sobre a atualização da posição e ângulo do robô
    position_updated = pyqtSignal(float, float, float)
    # Sinal para notificar a UI sobre a atualização do estado da navegação
    navigation_status_updated = pyqtSignal(dict)
    # Sinal para notificar a UI quando a navegação for finalizada ou interrompida
    navigation_completed = pyqtSignal(str)


    def __init__(self):
        """Inicializa o navegador do robô."""
        super().__init__()  # Essencial para inicializar o QObject
        self.slamtec = SlamtecManager()
        self.motors = RobotMotorController()
        
        print("DEBUG: Inicializando RobotNavigator...")
        print(f"DEBUG: ROBOT_INITIAL_POSITION configurado como: {ROBOT_INITIAL_POSITION}")
        print(f"DEBUG: ROBOT_INITIAL_ANGLE configurado como: {ROBOT_INITIAL_ANGLE}°")
        
        self.current_position = ROBOT_INITIAL_POSITION
        self.current_angle = ROBOT_INITIAL_ANGLE
        self.current_target = None
        self.navigation_active = False
        self.is_returning_to_base = False
        self.base_position = ROBOT_INITIAL_POSITION
        self.is_adjusting_final_angle = False
        self.navigation_state = "IDLE"  # IDLE, ORIENTING_TO_TARGET, NAVIGATING, RETURNING, COMPLETED
        self.speed_multiplier = 1.0  # Fator de velocidade inicial (100%)
        
        # Inicializa o PathFinder com as dimensões do mapa do config e grid size consistente
        self.path_finder = PathFinder(
            width=int(MAP_WIDTH / MAP_GRID_SIZE),
            height=int(MAP_HEIGHT / MAP_GRID_SIZE),
            grid_size=MAP_GRID_SIZE
        )
        
        self.forbidden_areas = []
        self.is_autonomous = False
        self.current_path = []
        self.current_path_index = 0
        
        # Novos atributos para navegação melhorada
        self.path_smoothing_enabled = True
        self.obstacle_avoidance_enabled = True
        self.emergency_stop_active = False
        self.last_position_update = time.time()
        self.navigation_start_time = None
        self.estimated_completion_time = None
        
        # Atributos para precisão na chegada
        self.arrival_pause_time = 2.0  # segundos de pausa ao chegar no destino
        self.arrival_time = None
        self.is_paused_at_destination = False
        
        self.is_returning_to_initial_angle = False  # Nova flag para controle do retorno ao ângulo inicial
        
        # NOVO: Atributo para controlar o tipo de navegação
        self.should_return_to_base = True  # True = ida e volta, False = apenas ao destino
        
        # Sistema de timeout para evitar travamento na aproximação final
        self.final_approach_start_time = None
        self.final_approach_timeout = 25.0  # Aumentado de 15s para 25s para dar mais tempo ao PID
        
        print(f"DEBUG: Posição inicial definida: {self.current_position}")
        print(f"DEBUG: Ângulo inicial definido: {self.current_angle}°")
        print(f"DEBUG: Base position definida: {self.base_position}")
        print(f"DEBUG: ROBOT_INITIAL_ANGLE importado: {ROBOT_INITIAL_ANGLE}°")
        print(f"DEBUG: ROBOT_INITIAL_POSITION importado: {ROBOT_INITIAL_POSITION}")
        
        print(f"DEBUG: Área proibida configurada no navegador")
        
    def reset_to_initial_state(self):
        """Reseta o robô para o estado inicial"""
        print("🔄 ===== RESETANDO ROBÔ PARA ESTADO INICIAL =====")
        print(f"🔄 Posição alvo: {ROBOT_INITIAL_POSITION}, ângulo alvo: {ROBOT_INITIAL_ANGLE}°")
        print(f"🔄 Estado anterior - navigation_active: {self.navigation_active}")
        print(f"🔄 Estado anterior - is_returning_to_base: {self.is_returning_to_base}")
        print(f"🔄 Estado anterior - navigation_state: {self.navigation_state}")
        
        # Preserva as áreas proibidas durante o reset
        preserved_forbidden_areas = self.forbidden_areas.copy()
        
        # ETAPA 2: Correção do "Pulo" - NÃO reseta a posição/ângulo.
        # A nova navegação deve começar da posição final real da navegação anterior.
        # self.current_position = ROBOT_INITIAL_POSITION
        # self.current_angle = ROBOT_INITIAL_ANGLE
        
        # Reseta variáveis de navegação
        self.navigation_active = False
        self.current_target = None
        self.path = []
        self.path_index = 0
        self.is_adjusting_final_angle = False
        self.is_returning_to_base = False  # RESETA ESTE VALOR
        self.navigation_state = "IDLE"
        self.progress = 0.0
        self.start_time = None
        self.estimated_time_remaining = 0.0
        self.is_paused_at_destination = False
        
        # Reset de variáveis específicas
        if hasattr(self, 'original_destination'):
            delattr(self, 'original_destination')
        self.final_approach_start_time = None
        
        # Restaura as áreas proibidas
        self.forbidden_areas = preserved_forbidden_areas
        self.path_finder.set_forbidden_areas(preserved_forbidden_areas)
        
        # Para os motores
        self.motors.stop()
        
        print("✅ ===== RESET CONCLUÍDO =====")
        print(f"✅ Posição resetada: {self.current_position}, Ângulo: {self.current_angle}°")
        print(f"✅ navigation_active: {self.navigation_active}")
        print(f"✅ is_returning_to_base: {self.is_returning_to_base}")
        print(f"✅ navigation_state: {self.navigation_state}")
        print(f"✅ Áreas proibidas preservadas: {len(self.forbidden_areas)}")
        print("=" * 60)
        
    def set_speed_multiplier(self, multiplier: float):
        """
        Define o multiplicador de velocidade para a navegação.
        
        Args:
            multiplier: Fator a ser multiplicado pela velocidade base (ex: 1.0, 1.5, 2.0).
        """
        if 1.0 <= multiplier <= 2.0:
            self.speed_multiplier = multiplier
            print(f"Velocidade ajustada para {self.speed_multiplier * 100:.0f}%")
        else:
            print(f"AVISO: Tentativa de definir multiplicador de velocidade inválido: {multiplier}. Deve ser entre 1.0 e 2.0.")

    def set_path(self, path: List[Tuple[float, float]]):
        """
        Define um novo caminho para o robô seguir.
        
        Args:
            path: Lista de pontos (x, y) que formam o caminho
        """
        self.current_path = self._smooth_path(path) if self.path_smoothing_enabled else path
        self.current_path_index = 0
        print(f"DEBUG: Caminho definido com {len(self.current_path)} pontos")
        
    def _smooth_path(self, path: List[Tuple[float, float]]) -> List[Tuple[float, float]]:
        """Suaviza o caminho para movimentos mais naturais"""
        if len(path) < 3:
            return path
            
        smoothed_path = [path[0]]  # Mantém o ponto inicial
        
        for i in range(1, len(path) - 1):
            prev_point = path[i - 1]
            current_point = path[i]
            next_point = path[i + 1]
            
            # Calcula o ponto médio ponderado
            smoothed_x = (prev_point[0] + 2 * current_point[0] + next_point[0]) / 4
            smoothed_y = (prev_point[1] + 2 * current_point[1] + next_point[1]) / 4
            
            smoothed_path.append((smoothed_x, smoothed_y))
            
        smoothed_path.append(path[-1])  # Mantém o ponto final
        return smoothed_path
        
    def update(self):
        """Atualiza o estado do robô usando uma máquina de estados clara."""
        self._update_pose_with_odometry()

        if not self.navigation_active:
            return

        if self.navigation_state == "IDLE":
            return

        elif self.navigation_state == "ORIENTING_TO_TARGET":
            self._orient_towards_target()

        elif self.navigation_state == "NAVIGATING_TO_DESTINATION":
            self._handle_navigation_to_destination()

        elif self.navigation_state == "FINAL_APPROACH_DESTINATION":
            if self._stable_final_approach(self.original_destination):
                self._transition_to_paused_at_destination()
        
        elif self.navigation_state == "PAUSED_AT_DESTINATION":
            self._handle_pause_at_destination()

        elif self.navigation_state == "RETURNING_TO_BASE":
            self._handle_return_to_base()

        elif self.navigation_state == "FINAL_APPROACH_BASE":
            if self._stable_final_approach(self.path[-1]):
                self._start_final_angle_adjustment()

        elif self.navigation_state == "ADJUSTING_FINAL_ANGLE":
            self._adjust_final_angle()

        if len(self.path) > 1:
            self.progress = self.path_index / (len(self.path) - 1)
        else:
            self.progress = 0.0

    def _finalize_navigation(self):
        """Finaliza completamente a navegação"""
        print("DEBUG: === FINALIZANDO NAVEGAÇÃO ===")
        self.motors.stop()
        self.navigation_active = False
        self.is_adjusting_final_angle = False
        self.navigation_state = "COMPLETED"
        self.current_target = None
        self.path = []
        self.path_index = 0
        print("DEBUG: === NAVEGAÇÃO FINALIZADA ===")
        
    def _calculate_and_execute_return_angle(self):
        """Calcula o ângulo necessário para retornar à base e inicia o giro"""
        print("DEBUG: === CALCULANDO ÂNGULO DE RETORNO ===")
        
        # Calcula o caminho de volta para a base
        path_to_base = self.path_finder.find_path(self.current_position, self.base_position)
        if not path_to_base or len(path_to_base) < 2:
            print("ERRO: Não foi possível calcular o caminho de volta para a base.")
            self._finalize_navigation()
            return
            
        self.path = path_to_base
        self.path_index = 0
        self.current_target = self.path[0]
        self.is_returning_to_base = True
        
        print("🔄 MUDANÇA DE FASE: PAUSED_AT_DESTINATION → ORIENTING_TO_TARGET (para retorno)")
        self.navigation_state = "ORIENTING_TO_TARGET"

    def _start_return_navigation(self):
        """Inicia a navegação de retorno à base"""
        print("DEBUG: === INICIANDO NAVEGAÇÃO DE RETORNO DIRETO ===")
        
        # NOVA LÓGICA: Retorno direto à base sem waypoints intermediários
        # Isso força o robô a ir direto para a base, fazendo o giro de 180° necessário
        
        # Cria um caminho direto: posição atual -> base
        direct_path = [self.current_position, self.base_position]
        
        # Substitui o caminho atual pelo caminho direto
        self.path = direct_path
        self.path_index = 0
        self.current_target = self.path[1]  # O alvo é a base
        
        print(f"DEBUG: Caminho direto criado: {self.current_position} -> {self.base_position}")
        print("🔄 MUDANÇA DE FASE: TURNING_TO_RETURN → RETURNING_TO_BASE")
        self.navigation_state = "RETURNING_TO_BASE"
        self.is_returning_to_base = True
        
    def _start_final_angle_adjustment(self):
        """Inicia o ajuste do ângulo final"""
        print("DEBUG: === INICIANDO AJUSTE DE ÂNGULO FINAL ===")
        print(f"DEBUG: Destino original preservado: {getattr(self, 'original_destination', 'NÃO DEFINIDO')}")
        self.motors.stop()
        self.navigation_state = "ADJUSTING_FINAL_ANGLE"
        self.is_adjusting_final_angle = True
        self.current_target = None
        # NÃO limpa o path para preservar informações de debug
        # self.path = []  # <- REMOVIDO para preservar o destino original
        self.path_index = len(self.path)  # Marca como final do caminho
        
        # Inicia o ajuste de ângulo
        self._adjust_final_angle()
        
    def get_current_path(self) -> List[Tuple[float, float]]:
        """Retorna o caminho de navegação atual."""
        return self.path

    def set_autonomous_mode(self, autonomous):
        """Alterna entre modo autônomo e manual"""
        self.is_autonomous = autonomous
        if not autonomous:
            self.motors.stop()  # Para o robô ao sair do modo autônomo

    def set_forbidden_areas(self, areas: List[List[Tuple[float, float]]]):
        """Define as áreas proibidas para o navegador"""
        self.forbidden_areas = areas
        self.path_finder.set_forbidden_areas(areas)
        print(f"DEBUG: {len(areas)} áreas proibidas configuradas no navegador")

    def navigate_to_destination_only(self, destination: Tuple[float, float]) -> None:
        """Navega apenas até o destino e para lá (sem retorno automático)"""
        print(f"DEBUG: ===== NAVEGAÇÃO APENAS AO DESTINO =====")
        print(f"DEBUG: Destino: {destination}")
        print(f"DEBUG: Posição atual: {self.current_position}, Ângulo atual: {self.current_angle}°")
        
        self.reset_to_initial_state()
        
        self.navigation_active = True
        self.start_time = time.time()
        self.is_returning_to_base = False
        self.should_return_to_base = False
        self.final_approach_start_time = None
        
        path_to_destination = self.path_finder.find_path(self.current_position, destination)
        if not path_to_destination or len(path_to_destination) < 2:
            print("DEBUG: ERRO - Não foi possível encontrar caminho para o destino")
            self.navigation_active = False
            return

        self.path = path_to_destination
        self.path_index = 0
        
        self.original_destination = destination
        self.destination_index = len(path_to_destination) - 1
        
        self.current_target = self.path[0]
        
        print(f"DEBUG: Caminho calculado com {len(self.path)} pontos.")
        print("🔄 MUDANÇA DE FASE: IDLE → ORIENTING_TO_TARGET")
        self.navigation_state = "ORIENTING_TO_TARGET"

    def get_navigation_status(self) -> dict:
        """Retorna o status atual da navegação"""
        if not self.navigation_active:
            return {
                "state": "IDLE", "progress": 0.0, "estimated_time_remaining": 0.0,
                "current_target": None, "position": self.current_position, "angle": self.current_angle
            }
            
        if len(self.path) > 1:
            progress = (self.path_index - 1) / (len(self.path) - 1)
        else:
            progress = 0.0
            
        time_remaining = 0.0
        if self.estimated_completion_time:
            time_remaining = max(0.0, self.estimated_completion_time - time.time())
            
        current_state = self.navigation_state
        if self.is_paused_at_destination:
            current_state = "PAUSED_AT_DESTINATION"
        elif self.is_adjusting_final_angle:
            current_state = "ADJUSTING_FINAL_ANGLE"
            
        return {
            "state": current_state, "progress": progress, "estimated_time_remaining": time_remaining,
            "current_target": self.current_target, "position": self.current_position,
            "angle": self.current_angle, "is_returning_to_base": self.is_returning_to_base,
            "is_paused_at_destination": self.is_paused_at_destination
        }

    def _calculate_distance(self, p1: Tuple[float, float], p2: Tuple[float, float]) -> float:
        """Calcula a distância entre dois pontos"""
        return math.sqrt((p2[0] - p1[0])**2 + (p2[1] - p1[1])**2) 

    def _orient_towards_target(self):
        if self.current_target is None:
            return

        dx = self.current_target[0] - self.current_position[0]
        dy = self.current_target[1] - self.current_position[1]
        target_angle = math.degrees(math.atan2(dy, dx))
        angle_error = (target_angle - self.current_angle + 180) % 360 - 180

        if abs(angle_error) < 5.0:  # Tolerância de 5 graus
            self.motors.stop()
            state_key = "RETURNING_TO_BASE" if self.is_returning_to_base else "NAVIGATING_TO_DESTINATION"
            print(f"🔄 MUDANÇA DE FASE: ORIENTING_TO_TARGET → {state_key}")
            self.navigation_state = state_key
            return

        # Volta para PID tradicional com força mínima garantida
        angular_speed_rads = math.radians(angle_error) * 5.0 
        angular_speed_rads = max(-MAX_ANGULAR_SPEED_RADS, min(MAX_ANGULAR_SPEED_RADS, angular_speed_rads))

        v = 0.0  # Velocidade linear é zero durante a orientação
        w = angular_speed_rads
        L = ROBOT_WHEEL_BASE_M
        
        left_wheel_speed_ms = v + (w * L) / 2.0
        right_wheel_speed_ms = v - (w * L) / 2.0
        
        left_tps = (left_wheel_speed_ms / ROBOT_WHEEL_CIRCUMFERENCE_M) * TICKS_PER_REVOLUTION
        right_tps = (right_wheel_speed_ms / ROBOT_WHEEL_CIRCUMFERENCE_M) * TICKS_PER_REVOLUTION
        
        # Aplica força mínima se a velocidade calculada for muito baixa
        MIN_TURN_TPS = 20.0
        if 0 < abs(left_tps) < MIN_TURN_TPS:
            left_tps = MIN_TURN_TPS * (1 if left_tps > 0 else -1)
        if 0 < abs(right_tps) < MIN_TURN_TPS:
            right_tps = MIN_TURN_TPS * (1 if right_tps > 0 else -1)
        
        self.motors.set_target_speed(left_tps, right_tps)

    def _move_towards_target(self):
        if self.current_target is None:
            self.motors.set_target_speed(0, 0)
            return

        dx = self.current_target[0] - self.current_position[0]
        dy = self.current_target[1] - self.current_position[1]
        target_angle = math.degrees(math.atan2(dy, dx))
        angle_error = (target_angle - self.current_angle + 180) % 360 - 180

        angle_factor = max(0.0, math.cos(math.radians(angle_error)))
        linear_speed_ms = MAX_LINEAR_SPEED_MS * self.speed_multiplier * angle_factor
        
        angular_speed_rads = math.radians(angle_error) * 1.8
        angular_speed_rads = max(-MAX_ANGULAR_SPEED_RADS, min(MAX_ANGULAR_SPEED_RADS, angular_speed_rads))

        v = linear_speed_ms
        w = angular_speed_rads
        L = ROBOT_WHEEL_BASE_M
        
        left_wheel_speed_ms = v + (w * L) / 2.0
        right_wheel_speed_ms = v - (w * L) / 2.0
        
        left_tps = (left_wheel_speed_ms / ROBOT_WHEEL_CIRCUMFERENCE_M) * TICKS_PER_REVOLUTION
        right_tps = (right_wheel_speed_ms / ROBOT_WHEEL_CIRCUMFERENCE_M) * TICKS_PER_REVOLUTION
        
        self.motors.set_target_speed(left_tps, right_tps)

    def _stable_final_approach(self, final_target: Tuple[float, float]):
        if final_target is None:
            self.motors.stop()
            return True

        current_time = time.time()
        if self.final_approach_start_time is None:
            self.final_approach_start_time = current_time

        if current_time - self.final_approach_start_time > self.final_approach_timeout:
            self.motors.stop()
            self.final_approach_start_time = None
            return True 
            
        dx = final_target[0] - self.current_position[0]
        dy = final_target[1] - self.current_position[1]
        total_distance = math.sqrt(dx**2 + dy**2)
        target_angle = math.degrees(math.atan2(dy, dx))
        angle_diff = (target_angle - self.current_angle + 180) % 360 - 180

        if total_distance <= 0.25:  # Aumentado de 0.15 para 0.25 metros (25cm)
            self.motors.stop()
            self.final_approach_start_time = None
            return True

        linear_speed_ms = 0.0 if abs(angle_diff) > 5.0 else min(MAX_LINEAR_SPEED_MS * 0.85, total_distance / 1.5)  # Aumentado de 0.7 para 0.85
        
        angular_speed_rads = math.radians(angle_diff) * 2.5
        angular_speed_rads = max(-MAX_ANGULAR_SPEED_RADS, min(MAX_ANGULAR_SPEED_RADS, angular_speed_rads))

        v = linear_speed_ms
        w = angular_speed_rads
        L = ROBOT_WHEEL_BASE_M
        left_wheel_speed_ms = v + (w * L) / 2.0
        right_wheel_speed_ms = v - (w * L) / 2.0

        left_tps = (left_wheel_speed_ms / ROBOT_WHEEL_CIRCUMFERENCE_M) * TICKS_PER_REVOLUTION
        right_tps = (right_wheel_speed_ms / ROBOT_WHEEL_CIRCUMFERENCE_M) * TICKS_PER_REVOLUTION

        self.motors.set_target_speed(left_tps, right_tps)
        return False

    def _adjust_final_angle(self):
        angle_diff = (ROBOT_INITIAL_ANGLE - self.current_angle + 180) % 360 - 180
        
        if abs(angle_diff) > 1.0:
            if abs(angle_diff) > 30: turn_value = min(0.8, abs(angle_diff) / 25.0)
            elif abs(angle_diff) > 10: turn_value = min(0.6, abs(angle_diff) / 30.0)
            else: turn_value = min(0.4, abs(angle_diff) / 35.0)
                
            if angle_diff > 0:
                left_speed = turn_value * 100
                right_speed = -turn_value * 100
            else:
                left_speed = -turn_value * 100
                right_speed = turn_value * 100
            self.motors.set_speed(left_speed, right_speed)
        else:
            self._finalize_navigation()

    def _get_next_waypoint_info(self):
        if not self.path or self.path_index >= len(self.path):
            return None
        return self.path_index, self.current_target, len(self.path)

    def _update_pose_with_odometry(self):
        ticks_data = self.motors.get_and_reset_ticks()
        if not ticks_data:
            return

        left_ticks, right_ticks = ticks_data.get('left', 0), ticks_data.get('right', 0)
        dist_left = (left_ticks / TICKS_PER_REVOLUTION) * ROBOT_WHEEL_CIRCUMFERENCE_M
        dist_right = (right_ticks / TICKS_PER_REVOLUTION) * ROBOT_WHEEL_CIRCUMFERENCE_M
        delta_distance = (dist_left + dist_right) / 2.0
        delta_angle_rad = (dist_left - dist_right) / ROBOT_WHEEL_BASE_M
        delta_angle_deg = math.degrees(delta_angle_rad)

        self.current_angle += delta_angle_deg
        if self.current_angle > 180: self.current_angle -= 360
        elif self.current_angle < -180: self.current_angle += 360

        angle_rad = math.radians(self.current_angle)
        delta_x = delta_distance * math.cos(angle_rad)
        delta_y = delta_distance * math.sin(angle_rad)

        self.current_position = (self.current_position[0] + delta_x, self.current_position[1] + delta_y)
        self.last_position_update = time.time()
        self.position_updated.emit(self.current_position[0], self.current_position[1], self.current_angle)

    def get_motor_controller(self):
        return self.motors

    def stop(self):
        print("INFO: Comando de parada recebido pelo navegador.")
        self._finalize_navigation()
        
    def _handle_navigation_to_destination(self):
        if self.current_target is None or self.current_position is None:
            self._finalize_navigation()
            return

        distance_to_target = self._calculate_distance(self.current_position, self.current_target)

        is_near_final_destination = (self.path_index >= len(self.path) - 1)

        if is_near_final_destination and distance_to_target < 0.15:
            self.navigation_state = "FINAL_APPROACH_DESTINATION"
            self.current_target = self.original_destination
            return

        if distance_to_target < 0.12:
            self.path_index += 1
            if self.path_index < len(self.path):
                self.current_target = self.path[self.path_index]
            else:
                self.navigation_state = "FINAL_APPROACH_DESTINATION"
                self.current_target = self.original_destination
            return
        
        self._move_towards_target()

    def _handle_return_to_base(self):
        if self.current_target is None or self.current_position is None or not self.path:
            self._finalize_navigation()
            return

        distance_to_target = self._calculate_distance(self.current_position, self.current_target)
        is_near_base = (self.path_index >= len(self.path) - 1)

        if is_near_base and distance_to_target < 0.15:
            self.navigation_state = "FINAL_APPROACH_BASE"
            self.current_target = self.path[-1]
            self.final_approach_start_time = None 
            return

        if distance_to_target < NAVIGATION_GOAL_TOLERANCE:
            self.path_index += 1
            if self.path_index < len(self.path):
                self.current_target = self.path[self.path_index]
            else:
                self._start_final_angle_adjustment()
            return
        
        self._move_towards_target()

    def _transition_to_paused_at_destination(self):
        self.motors.stop()
        self.navigation_state = "PAUSED_AT_DESTINATION"
        self.arrival_time = time.time()
        self.is_paused_at_destination = True

    def _handle_pause_at_destination(self):
        if self.arrival_time is not None and (time.time() - self.arrival_time > self.arrival_pause_time):
            self.is_paused_at_destination = False
            if self.should_return_to_base:
                self._calculate_and_execute_return_angle()
            else:
                self._finalize_navigation()
