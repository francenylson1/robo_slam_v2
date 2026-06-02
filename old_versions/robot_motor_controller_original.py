# modules/robot_motor_controller.py
import time
import RPi.GPIO as GPIO


class RobotMotorController:
    def __init__(self):
        # Configuração inicial
        GPIO.setmode(GPIO.BCM)
        GPIO.setwarnings(False)

        # PINOS DO MOTOR ESQUERDO
        self.dir_E = 5  # cinza
        self.break_E = 6
        self.speed_E = 18

        # PINOS DO MOTOR DIREITO
        self.dir_D = 23  # cinza
        self.break_D = 24
        self.speed_D = 12

        # CONFIGURAÇÃO GPIOS
        # MOTOR ESQUERDO
        GPIO.setup(self.dir_E, GPIO.OUT)
        GPIO.setup(self.break_E, GPIO.OUT)
        GPIO.setup(self.speed_E, GPIO.OUT)

        # MOTOR DIREITO
        GPIO.setup(self.dir_D, GPIO.OUT)
        GPIO.setup(self.break_D, GPIO.OUT)
        GPIO.setup(self.speed_D, GPIO.OUT)

        # Inicialização PWM
        self.speedDIR = GPIO.PWM(self.speed_D, 20)
        self.speedDIR.start(0)
        self.speedESQ = GPIO.PWM(self.speed_E, 20)
        self.speedESQ.start(0)

        # Inicializando com o motor parado para evitar acidentes
        GPIO.output(self.break_D, GPIO.HIGH)
        GPIO.output(self.break_E, GPIO.HIGH)

        # Velocidades
        self.vel = 11
        self.vel1 = 11
        self.vel2 = 11
        self.vel3 = 11
        self.vel4 = 11

    def stop(self):
        """Para os motores"""
        self.speedDIR.start(1)
        self.speedESQ.start(1)
        # MOTOR EM BREAK
        GPIO.output(self.break_D, GPIO.HIGH)
        GPIO.output(self.break_E, GPIO.HIGH)
        print("STOP")

    def up_side(self):
        """Movimento para frente"""
        self.speedDIR.start(self.vel3)
        self.speedESQ.start(self.vel3)
        # libera o motor do break para iniciar o giro
        GPIO.output(self.break_D, GPIO.LOW)
        GPIO.output(self.break_E, GPIO.LOW)
        print("girar para FRENTE")
        GPIO.output(self.dir_D, GPIO.LOW)
        time.sleep(0.0001)
        GPIO.output(self.dir_E, GPIO.HIGH)

    def left_side(self):
        """Movimento para esquerda"""
        self.speedESQ.start(self.vel)
        self.speedDIR.start(self.vel2)
        # libera o motor do break para iniciar o giro
        GPIO.output(self.break_E, GPIO.LOW)
        GPIO.output(self.break_D, GPIO.LOW)
        # 1a. ação girar para lado PADRÃO
        GPIO.output(self.dir_E, GPIO.LOW)
        GPIO.output(self.dir_D, GPIO.LOW)
        print("girar para ESQUERDA")

    def right_side(self):
        """Movimento para direita"""
        # define velocidade do pwm
        self.speedDIR.start(self.vel)
        self.speedESQ.start(self.vel2)
        GPIO.output(self.break_D, GPIO.LOW)
        GPIO.output(self.break_E, GPIO.LOW)
        # girar para lado PADRÃO
        GPIO.output(self.dir_D, GPIO.HIGH)
        GPIO.output(self.dir_E, GPIO.HIGH)  # sentido anti-horário para melhorar performace da curva
        print("girar para DIREITA")

    def down_side(self):
        """Movimento para trás"""
        self.speedDIR.start(self.vel1)
        self.speedESQ.start(self.vel1)
        # libera o motor do break para iniciar o giro
        GPIO.output(self.break_D, GPIO.LOW)
        GPIO.output(self.break_E, GPIO.LOW)
        print("girar para TRÁS")
        GPIO.output(self.dir_D, GPIO.HIGH)
        time.sleep(0.01)
        GPIO.output(self.dir_E, GPIO.LOW)

    def set_speed(self, speed):
        """Define velocidade dos motores (0-15)"""
        self.vel = self.vel1 = self.vel2 = self.vel3 = self.vel4 = min(11, max(0, speed))
        print(f"DEBUG_MOTOR: Velocidade solicitada: {speed}, Velocidade aplicada: {self.vel}")

    def move_with_joystick(self, forward_value, turn_value):
        """Controle do robô baseado em valores de joystick (-1 a 1)"""
        # Filtrar pequenos movimentos (deadzone)
        if abs(forward_value) < 0.1 and abs(turn_value) < 0.1:
            self.stop()
            return

        # Escalar velocidade baseado no valor do joystick
        speed = int(abs(forward_value) * 11)
        self.set_speed(speed)

        # Determinar direção
        if forward_value > 0.1:
            if turn_value > 0.3:
                self.right_side()
            elif turn_value < -0.3:
                self.left_side()
            else:
                self.up_side()
        elif forward_value < -0.1:
            if turn_value > 0.3:
                self.right_side()
            elif turn_value < -0.3:
                self.left_side()
            else:
                self.down_side()
        else:
            # Apenas virando no mesmo lugar
            if turn_value > 0.1:
                self.right_side()
            elif turn_value < -0.1:
                self.left_side()
            else:
                self.stop()

    def cleanup(self):
        """Limpa recursos dos motores"""
        self.stop()
        self.speedDIR.stop()
        self.speedESQ.stop()
        # Não chame GPIO.cleanup() aqui, pois pode interferir com outros sistemas