# modules/robot_motor_controller.py
import time
import sys
import os
import threading
from PyQt5.QtCore import QObject, pyqtSignal

# Adiciona o diretório raiz ao PYTHONPATH
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

from src.core.environment import GPIO_AVAILABLE
from src.core.pid_controller import PIDController
from src.core.config import TICKS_PER_REVOLUTION # Importa a constante necessária

if GPIO_AVAILABLE:
    try:
        import RPi.GPIO as GPIO
    except (ImportError, RuntimeError):
        print("AVISO: A biblioteca RPi.GPIO não pôde ser importada. Motores não funcionarão.")
        GPIO_AVAILABLE = False
else:
    GPIO = None

class RobotMotorController(QObject):
    """
    Controla os motores do robô, abstraindo a complexidade do hardware.
    Pode operar em modo real (com Raspberry Pi e RPi.GPIO) ou em modo simulado.
    """
    # --- SINAL UNIFICADO ---
    pid_data_updated = pyqtSignal(dict) # Emite um dicionário com os dados de ambos os motores

    def __init__(self):
        super().__init__() # <-- 4. CHAMAR O __INIT__ DA CLASSE PAI
        self.left_speed_percent = 0
        self.right_speed_percent = 0
        self.is_moving = False
        
        # --- NOVO: Lock para proteger o acesso aos contadores de ticks ---
        self.ticks_lock = threading.Lock()
        
        # --- NOVO: Controle de frequência de emissão de sinal ---
        self.last_emit_time = 0
        self.emit_interval = 0.2  # segundos (200ms)

        # --- NOVO: Atributos para o modo de simulação ---
        self.simulated_left_tps = 0.0
        self.simulated_right_tps = 0.0
        self.last_sim_time = time.time()
        
        # --- ATRIBUTOS DO PID ---
        # Movidos para fora do bloco 'if GPIO_AVAILABLE' para que existam
        # tanto em modo real quanto simulado.
        # Aumentando o limite de saída para 90% para dar ao PID mais autoridade para vencer a inércia.
        self.pid_left = PIDController(Kp=0.26, Ki=0.23, Kd=0.0, setpoint=0, output_limits=(-90, 90))
        self.pid_right = PIDController(Kp=0.26, Ki=0.23, Kd=0.0, setpoint=0, output_limits=(-90, 90))
        self.pid_enabled = False

        # Atributos para feedback de velocidade
        self.left_hall_ticks = 0
        self.right_hall_ticks = 0
        self.last_speed_check_time = time.time()
        self.current_left_tps = 0.0
        self.current_right_tps = 0.0

        # --- CORREÇÃO: Contadores de ticks dedicados para odometria ---
        # Estes contadores são usados pelo RobotNavigator e zerados a cada chamada de get_and_reset_ticks
        self.left_ticks_for_odometry = 0
        self.right_ticks_for_odometry = 0
        
        # --- NOVO: Evento para desligamento limpo das threads ---
        self.shutdown_event = threading.Event()
        
        # --- NOVO: Interruptor para o controle PID ---
        # self.pid_enabled = False # Movido para cima

        if GPIO_AVAILABLE and GPIO:
            print("Inicializando controlador de motores em MODO REAL (Raspberry Pi).")
            GPIO.setmode(GPIO.BCM)
            GPIO.setwarnings(False)

            # --- Pinos Originais Restaurados ---
            # PINOS DO MOTOR ESQUERDO
            self.dir_E = 5      # Direção
            self.break_E = 6    # Freio
            self.speed_E = 18   # PWM para Velocidade
            self.hall_E = 16    # Sensor Hall (Encoder)

            # PINOS DO MOTOR DIREITO
            self.dir_D = 23     # Direção
            self.break_D = 24   # Freio
            self.speed_D = 12   # PWM para Velocidade
            self.hall_D = 17    # Sensor Hall (Encoder)
            
            # Configura pinos de saída
            for pin in [self.dir_E, self.break_E, self.speed_E, self.dir_D, self.break_D, self.speed_D]:
                GPIO.setup(pin, GPIO.OUT)

            # Configura pinos de entrada para os sensores Hall
            GPIO.setup(self.hall_E, GPIO.IN, pull_up_down=GPIO.PUD_DOWN)
            GPIO.setup(self.hall_D, GPIO.IN, pull_up_down=GPIO.PUD_DOWN)
            
            # Inicializa o estado anterior para o Polling
            self.last_hall_E_state = GPIO.input(self.hall_E)
            self.last_hall_D_state = GPIO.input(self.hall_D)

            # Inicializa PWM a 20Hz ANTES de iniciar as threads
            self.pwm_D = GPIO.PWM(self.speed_D, 20)
            self.pwm_E = GPIO.PWM(self.speed_E, 20)
            self.pwm_D.start(0)
            self.pwm_E.start(0)

            # Inicializa os controladores PID, mas o loop nao comeca a controlar ainda
            # Ganhos iniciais (precisarao de ajuste fino)
            # Kp: Aumentado para dar forca suficiente para o robo sair da inercia.
            # Ki: Aumentado para ajudar a vencer o atrito inicial.
            # Kd: Mantido baixo para evitar instabilidade.
            # NOVOS GANHOS (MUITO MAIS CONSERVADORES) PARA ESTABILIZAR O ROBÔ EM BAIXA VELOCIDADE
            # O objetivo é eliminar o movimento circular.
            # AUMENTANDO O Ki PARA DAR MAIS "INSISTÊNCIA" AO ROBÔ NA APROXIMAÇÃO FINAL.
            # --- ATUALIZAÇÃO: Reduzindo drasticamente os limites para calibração fina ---
            # A inicialização foi movida para fora deste bloco
            # self.pid_left = PIDController(Kp=0.05, Ki=0.05, Kd=0.01, setpoint=0, output_limits=(-20, 20))
            # self.pid_right = PIDController(Kp=0.05, Ki=0.05, Kd=0.01, setpoint=0, output_limits=(-20, 20))

            # Inicia a thread de monitoramento dos sensores Hall por Polling
            monitor_thread = threading.Thread(target=self._hall_sensor_monitor_thread, daemon=True)
            monitor_thread.start()

            # Inicia a thread de controle PID
            pid_control_thread = threading.Thread(target=self._pid_control_loop, daemon=True)
            pid_control_thread.start()

            # Ativa o freio dos motores como estado inicial seguro
            GPIO.output(self.break_D, GPIO.HIGH)
            GPIO.output(self.break_E, GPIO.HIGH)
        else:
            print("Inicializando controlador de motores em MODO SIMULADO.")

    def _hall_sensor_monitor_thread(self):
        """
        Thread que monitora os sensores Hall via Polling para evitar o uso
        de 'add_event_detect' que estava se mostrando instável.
        """
        # Garante que o GPIO esteja disponível antes de entrar no loop
        if not GPIO_AVAILABLE or not GPIO:
            return

        # Debug: Contadores para monitorar os ticks
        debug_counter = 0
        last_debug_time = time.time()

        while not self.shutdown_event.is_set():
            # Leitura do sensor esquerdo
            try:
                current_state_E = GPIO.input(self.hall_E)
                if current_state_E == 1 and self.last_hall_E_state == 0:
                    # --- FILTRO DEBOUNCE AGRESSIVO ---
                    time.sleep(0.01) # Pausa por 10ms
                    if GPIO.input(self.hall_E) == 1:
                        with self.ticks_lock:
                            self.left_hall_ticks += 1
                            self.left_ticks_for_odometry += 1 # Incrementa o contador para odometria
                self.last_hall_E_state = current_state_E

                # Leitura do sensor direito
                current_state_D = GPIO.input(self.hall_D)
                if current_state_D == 1 and self.last_hall_D_state == 0:
                    # --- FILTRO DEBOUNCE AGRESSIVO ---
                    time.sleep(0.01) # Pausa por 10ms
                    if GPIO.input(self.hall_D) == 1:
                        with self.ticks_lock:
                            self.right_hall_ticks += 1
                            self.right_ticks_for_odometry += 1 # Incrementa o contador para odometria
                self.last_hall_D_state = current_state_D
            
            except RuntimeError:
                # Se o GPIO foi limpo, a thread deve parar.
                break
            
            # Debug: A cada 1000 iterações, mostra o status dos encoders
            debug_counter += 1
            if debug_counter >= 1000:
                current_time = time.time()
                if current_time - last_debug_time > 5.0:  # A cada 5 segundos
                    with self.ticks_lock:
                        print(f"DEBUG ENCODER: L:{self.left_hall_ticks} ticks, R:{self.right_hall_ticks} ticks | Estados: L:{current_state_E}, R:{current_state_D}")
                    last_debug_time = current_time
                debug_counter = 0
            
            # Pausa muito curta para evitar 100% de uso da CPU
            time.sleep(0.001) # Poll a ~1000Hz

    def _pid_control_loop(self):
        """
        Thread que executa o loop de controle PID continuamente.
        """
        if not GPIO_AVAILABLE:
            return
            
        while not self.shutdown_event.is_set():
            if not self.pid_enabled:
                time.sleep(0.1) # Dorme se desativado para nao usar CPU
                continue

            # 1. Calcula a velocidade real atual (ticks/s)
            self._update_current_speed()
            
            # 2. Calcula a saida de potencia usando o PID
            left_power = self.pid_left.update(self.current_left_tps)
            right_power = self.pid_right.update(self.current_right_tps)
            
            # --- SOLUÇÃO DEFINITIVA: Piso de potência mínima ---
            # Se o PID gerar potência muito baixa mas há setpoint, aplica potência mínima
            MIN_POWER_THRESHOLD = 4.0  # Se PID gerar menos que 4%, usa piso mínimo
            MIN_POWER_FLOOR = 7.0     # AUMENTADO: Piso de potência mínima (era 6.0)
            
            # --- REMOVIDO: O piso de potência estava causando oscilação ou travamento.
            # A abordagem correta é ajustar os ganhos do PID para que ele mesmo
            # possa superar a inércia inicial de forma suave.
            
            # --- DESABILITADO: Print do PID para logs limpos ---
            # print(f"DEBUG PID: Target L:{self.pid_left.setpoint:.1f}tps R:{self.pid_right.setpoint:.1f}tps | Real L:{self.current_left_tps:.1f}tps R:{self.current_right_tps:.1f}tps | Output L:{left_power:.1f}% R:{right_power:.1f}%")
            
            # --- Emite o sinal em uma frequência controlada para não sobrecarregar a GUI ---
            current_time = time.time()
            if current_time - self.last_emit_time > self.emit_interval:
                combined_data = {
                    'left': {'setpoint': self.pid_left.setpoint, 'real_speed': self.current_left_tps, 'output': left_power},
                    'right': {'setpoint': self.pid_right.setpoint, 'real_speed': self.current_right_tps, 'output': right_power}
                }
                self.pid_data_updated.emit(combined_data)
                self.last_emit_time = current_time

            # 3. Aplica a potencia aos motores COM A LÓGICA DE DIREÇÃO CORRETA
            if GPIO_AVAILABLE and GPIO:
                # --- MOTOR ESQUERDO ---
                if left_power >= 0: # Para frente
                    GPIO.output(self.dir_E, GPIO.HIGH)  # ESQUERDO: HIGH = frente
                else: # Para trás
                    GPIO.output(self.dir_E, GPIO.LOW)   # ESQUERDO: LOW = trás
                self.pwm_E.ChangeDutyCycle(min(abs(left_power), 100))

                # --- MOTOR DIREITO - LÓGICA CORRETA CONFORME gpio_test.py ---
                # IMPORTANTE: Motores têm lógicas DIFERENTES por design físico!
                # Motor esquerdo: HIGH=frente, LOW=trás
                # Motor direito:  LOW=frente, HIGH=trás (OPOSTO por design)
                if right_power >= 0: # Para frente
                    GPIO.output(self.dir_D, GPIO.LOW)   # DIREITO: LOW = frente (conforme gpio_test.py)
                else: # Para trás
                    GPIO.output(self.dir_D, GPIO.HIGH)  # DIREITO: HIGH = trás (conforme gpio_test.py)
                self.pwm_D.ChangeDutyCycle(min(abs(right_power), 100))

                # Libera os freios se houver qualquer potência
                if abs(left_power) > 0.1 or abs(right_power) > 0.1:
                    GPIO.output(self.break_E, GPIO.LOW)
                    GPIO.output(self.break_D, GPIO.LOW)
                else:
                    GPIO.output(self.break_E, GPIO.HIGH)
                    GPIO.output(self.break_D, GPIO.HIGH)
            
            # 4. Define a frequencia do loop de controle (ex: 20Hz)
            time.sleep(0.05)

    def _update_current_speed(self):
        """
        Calcula e atualiza a velocidade instantanea (ticks/s) para uso no PID.
        """
        current_time = time.time()
        delta_time = current_time - self.last_speed_check_time

        # AUMENTADO: Intervalo de atualização de 0.01s para 0.1s (10Hz em vez de 100Hz)
        # Isso permite que os ticks se acumulem adequadamente
        if delta_time > 0.1: # Atualiza a cada 100ms em vez de 10ms
            with self.ticks_lock:
                self.current_left_tps = self.left_hall_ticks / delta_time
                self.current_right_tps = self.right_hall_ticks / delta_time

                # Debug: Mostra quando há ticks sendo processados
                if self.left_hall_ticks > 0 or self.right_hall_ticks > 0:
                    print(f"DEBUG SPEED: Processando ticks - L:{self.left_hall_ticks}, R:{self.right_hall_ticks} em {delta_time:.3f}s")

                self.left_hall_ticks = 0
                self.right_hall_ticks = 0
            
            self.last_speed_check_time = current_time

    def set_target_speed(self, left_tps: float, right_tps: float):
        """
        Define a velocidade alvo para o controle PID em ticks por segundo (tps).
        Ativa o controle PID se ele estiver desativado.
        """
        print(f"🚀 SYNC_DEBUG: set_target_speed(left={left_tps:.1f}, right={right_tps:.1f})")
        if not self.pid_enabled:
            self.enable_pid_control()

        self.pid_left.set_setpoint(left_tps)
        self.pid_right.set_setpoint(right_tps)

        # --- CORREÇÃO PARA SIMULAÇÃO ---
        # Se não estiver no hardware, armazena a velocidade alvo para simular os ticks.
        if not GPIO_AVAILABLE:
            self.simulated_left_tps = left_tps
            self.simulated_right_tps = right_tps

    def set_pid_gains(self, side, Kp, Ki, Kd):
        """
        Atualiza os ganhos do PID para um dos motores.
        """
        if side == 'left':
            self.pid_left.set_gains(Kp, Ki, Kd)
            print(f"PID Aply: Lado=left, Kp={Kp:.2f}, Ki={Ki:.2f}, Kd={Kd:.2f}")
        elif side == 'right':
            self.pid_right.set_gains(Kp, Ki, Kd)
            print(f"PID Aply: Lado=right, Kp={Kp:.2f}, Ki={Ki:.2f}, Kd={Kd:.2f}")

    def enable_pid_control(self):
        """Ativa o loop de controle PID."""
        print("DEBUG: Controle PID ATIVADO.")
        self.pid_enabled = True

    def disable_pid_control(self):
        """Desativa o loop de controle PID e reseta os controladores."""
        print("DEBUG: Controle PID DESATIVADO e motores parados.")
        self.pid_enabled = False
        # Para os motores fisicamente
        if GPIO_AVAILABLE and GPIO:
            self.pwm_E.ChangeDutyCycle(0)
            self.pwm_D.ChangeDutyCycle(0)
            GPIO.output(self.break_E, GPIO.HIGH)
            GPIO.output(self.break_D, GPIO.HIGH)
        # Reseta o estado dos PIDs para a próxima ativação
        self.pid_left.reset()
        self.pid_right.reset()

    def set_speed(self, left_speed: float, right_speed: float):
        """
        Método de compatibilidade para definir a velocidade dos motores.
        Se as velocidades forem zero, para os motores usando o novo sistema.
        Caso contrário, converte a porcentagem de velocidade para tps e usa o PID.
        """
        print(f"🎯 SYNC_DEBUG: set_speed(left={left_speed}, right={right_speed})")
        if left_speed == 0 and right_speed == 0:
            self.stop_motors()
        else:
            # Assumindo que a velocidade máxima (100%) corresponde a um valor de tps
            # Este valor pode precisar de calibração
            MAX_TPS = 50 # Exemplo: 50 ticks por segundo na potência máxima
            left_tps = (left_speed / 100.0) * MAX_TPS
            right_tps = (right_speed / 100.0) * MAX_TPS
            print(f"🎯 SYNC_DEBUG: → Convertido para TPS: left={left_tps:.1f}, right={right_tps:.1f}")
            self.set_target_speed(left_tps, right_tps)

    def _set_motor_speed_real(self, motor: str, speed_percent: float):
        """Controla um motor específico via GPIO."""
        if not GPIO_AVAILABLE or not GPIO:
            return

        if motor == "left":
            pwm = self.pwm_E
            pin_dir = self.dir_E
            pin_break = self.break_E
        elif motor == "right":
            pwm = self.pwm_D
            pin_dir = self.dir_D
            pin_break = self.break_D
        else:
            return

        if abs(speed_percent) < 1:
            # Para o motor e ativa o freio
            pwm.ChangeDutyCycle(0)
            GPIO.output(pin_break, GPIO.HIGH)
            return

        # Libera o freio
        GPIO.output(pin_break, GPIO.LOW)
        
        # Define a direção
        if speed_percent > 0:
            # Para frente - LÓGICA CORRETA restaurada com base na fiação do robô.
            # Esquerda = HIGH, Direita = LOW
            direction = GPIO.HIGH if motor == "left" else GPIO.LOW
        else:
            # Para trás - Lógica invertida da de cima.
            direction = GPIO.LOW if motor == "left" else GPIO.HIGH
        
        GPIO.output(pin_dir, direction)
        
        # Define a velocidade (Duty Cycle)
        duty_cycle = abs(speed_percent)
        pwm.ChangeDutyCycle(duty_cycle)

    def _simulate_movement(self):
        """Simula o movimento do robô para depuração sem hardware."""
        self.is_moving = self.left_speed_percent != 0 or self.right_speed_percent != 0
        # print(f"SIM: Movimento {'ativo' if self.is_moving else 'parado'}. "
        #       f"Velocidades: E={self.left_speed_percent}%, D={self.right_speed_percent}%")

    def get_and_reset_ticks(self) -> dict:
        """
        Retorna os ticks acumulados e os zera. Este é o coração da odometria.
        - Em modo real, aplica o sinal (+/-) baseado na direção do setpoint do PID.
        - Em modo simulado, calcula os ticks com base na velocidade alvo e no tempo.
        """
        if GPIO_AVAILABLE:
            with self.ticks_lock:
                # Determina a direção com base no setpoint do PID para o robô real
                left_direction = 1 if self.pid_left.setpoint >= 0 else -1
                right_direction = 1 if self.pid_right.setpoint >= 0 else -1

                ticks_to_return = {
                    "left": self.left_ticks_for_odometry * left_direction,
                    "right": self.right_ticks_for_odometry * right_direction
                }
                self.left_ticks_for_odometry = 0
                self.right_ticks_for_odometry = 0
            return ticks_to_return
        else:
            # Em modo simulado, calcula os ticks com base na velocidade alvo e no tempo
            current_time = time.time()
            delta_t = current_time - self.last_sim_time
            
            # Os `simulated_..._tps` já têm o sinal correto (positivo/negativo)
            simulated_left_ticks = self.simulated_left_tps * delta_t
            simulated_right_ticks = self.simulated_right_tps * delta_t
            
            self.last_sim_time = current_time
            
            return {
                "left": simulated_left_ticks,
                "right": simulated_right_ticks
            }

    def get_real_time_speed(self) -> dict:
        """Retorna a velocidade em tempo real (TPS) de cada motor."""
        return {"left": self.current_left_tps, "right": self.current_right_tps}

    def stop(self):
        """Método de conveniência para parar os motores. Usa o novo sistema PID."""
        self.stop_motors()

    def stop_motors(self):
        """Para ambos os motores e o controle PID de forma segura."""
        self.set_target_speed(0, 0)
        self.disable_pid_control()

    def cleanup(self):
        """Limpa os recursos do GPIO de forma segura."""
        if GPIO_AVAILABLE and GPIO:
            print("INFO: Iniciando limpeza dos recursos do RobotMotorController...")
            # 1. Sinaliza para as threads pararem
            self.shutdown_event.set()
            
            # 2. Pequena pausa para permitir que as threads terminem seus loops
            time.sleep(0.1)
            
            # 3. Para os motores (garantia extra)
            self.stop()
            
            # 4. Limpa os pinos GPIO
            GPIO.cleanup()
            print("INFO: Limpeza do GPIO concluída.")