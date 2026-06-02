import time

class PIDController:
    """
    Uma implementacao de um controlador Proporcional-Integral-Derivativo (PID).
    """
    def __init__(self, Kp, Ki, Kd, setpoint, output_limits=(-100, 100)):
        """
        Inicializa o controlador PID.

        Args:
            Kp (float): Ganho Proporcional.
            Ki (float): Ganho Integral.
            Kd (float): Ganho Derivativo.
            setpoint (float): O valor desejado que o controlador tentara alcancar.
            output_limits (tuple): Uma tupla (min, max) para limitar a saida do controlador.
        """
        self.Kp = Kp
        self.Ki = Ki
        self.Kd = Kd
        
        self.setpoint = setpoint
        self.output_limits = output_limits
        
        self.proportional_term = 0.0
        self.integral_term = 0.0
        self.derivative_term = 0.0
        
        self.last_error = 0.0
        self.last_time = time.time()
        
        self.reset()

    def update(self, process_variable):
        """
        Calcula a saida do controlador PID com base no valor atual do processo.

        Args:
            process_variable (float): O valor medido atual do sistema (ex: velocidade real).

        Returns:
            float: O valor de controle calculado para ser aplicado ao sistema (ex: potencia do motor).
        """
        current_time = time.time()
        delta_time = current_time - self.last_time

        # Evita divisao por zero ou picos em caso de reset
        if delta_time == 0:
            return self.last_output

        error = self.setpoint - process_variable
        
        # --- Termo Proporcional ---
        self.proportional_term = self.Kp * error
        
        # --- Termo Integral (com anti-windup) ---
        self.integral_term += error * delta_time
        # Anti-windup: limita o termo integral para evitar que ele cresca indefinidamente
        # (Isso sera melhorado apos a integracao inicial)

        # --- Termo Derivativo ---
        delta_error = error - self.last_error
        self.derivative_term = 0.0
        if delta_time > 0:
            self.derivative_term = delta_error / delta_time
        
        # --- Saida Final ---
        output = self.proportional_term + (self.Ki * self.integral_term) + (self.Kd * self.derivative_term)
        
        # Limita a saida
        output = max(self.output_limits[0], min(self.output_limits[1], output))

        # Guarda os valores para a proxima iteracao
        self.last_error = error
        self.last_time = current_time
        self.last_output = output
        
        return output

    def set_setpoint(self, setpoint):
        """Atualiza o valor desejado."""
        self.setpoint = setpoint
        self.reset()

    def set_gains(self, Kp, Ki, Kd):
        """
        Permite ajustar os ganhos do PID em tempo real.
        """
        self.Kp = Kp
        self.Ki = Ki
        self.Kd = Kd
        self.reset()

    def reset(self):
        """Reseta o estado do controlador PID."""
        self.proportional_term = 0.0
        self.integral_term = 0.0
        self.derivative_term = 0.0
        self.last_error = 0.0
        self.last_time = time.time()
        self.last_output = 0.0 