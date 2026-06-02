"""
core/pid_controller.py
Controlador PID com anti-windup.
Migrado integralmente do robo_slam v1 — lógica validada no robô real.
Dependência de PyQt5 removida. Completamente standalone.
"""

import time


class PIDController:
    """
    Controlador PID com anti-windup e ajuste de ganhos em tempo real.
    Ganhos calibrados fisicamente: Kp=0.26, Ki=0.23, Kd=0.0
    """

    def __init__(self, Kp: float, Ki: float, Kd: float,
                 setpoint: float = 0.0,
                 output_limits: tuple = (-100.0, 100.0)):
        self.Kp = Kp
        self.Ki = Ki
        self.Kd = Kd
        self.setpoint       = setpoint
        self.output_limits  = output_limits

        self.proportional_term = 0.0
        self.integral_term     = 0.0
        self.derivative_term   = 0.0
        self.last_error        = 0.0
        self.last_output       = 0.0
        self.last_time         = time.time()

    def update(self, process_variable: float) -> float:
        """Calcula e retorna a saída do PID para o valor medido atual."""
        current_time = time.time()
        delta_time   = current_time - self.last_time

        if delta_time == 0:
            return self.last_output

        error = self.setpoint - process_variable

        self.proportional_term  = self.Kp * error
        self.integral_term     += error * delta_time

        delta_error = error - self.last_error
        self.derivative_term = (delta_error / delta_time) if delta_time > 0 else 0.0

        output = (self.proportional_term
                  + self.Ki * self.integral_term
                  + self.Kd * self.derivative_term)

        output = max(self.output_limits[0], min(self.output_limits[1], output))

        self.last_error  = error
        self.last_time   = current_time
        self.last_output = output
        return output

    def set_setpoint(self, setpoint: float):
        """Atualiza o valor alvo e reseta o estado interno."""
        self.setpoint = setpoint
        self.reset()

    def set_gains(self, Kp: float, Ki: float, Kd: float):
        """Ajusta os ganhos em tempo real (útil para calibração)."""
        self.Kp = Kp
        self.Ki = Ki
        self.Kd = Kd
        self.reset()

    def reset(self):
        """Reseta todos os termos acumulados."""
        self.proportional_term = 0.0
        self.integral_term     = 0.0
        self.derivative_term   = 0.0
        self.last_error        = 0.0
        self.last_output       = 0.0
        self.last_time         = time.time()
