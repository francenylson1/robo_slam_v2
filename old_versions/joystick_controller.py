# modules/joystick_controller.py
import pygame
import threading
import time
import os


class JoystickController:
    def __init__(self, button_callback=None):
        self.button_callback = button_callback
        self.running = False
        self.thread = None
        self.joystick = None
        self.current_selection = 0
        self.total_buttons = 10

        # Inicialização do pygame
        os.environ['SDL_VIDEODRIVER'] = 'dummy'  # Previne erros de display
        pygame.init()
        pygame.joystick.init()

    def start(self):
        """Inicia o monitoramento do joystick em uma thread separada"""
        if self.thread is None or not self.thread.is_alive():
            self.running = True
            self.thread = threading.Thread(target=self._monitor_joystick)
            self.thread.daemon = True
            self.thread.start()
            return True
        return False

    def stop(self):
        """Para o monitoramento do joystick"""
        self.running = False
        if self.thread and self.thread.is_alive():
            self.thread.join(timeout=1.0)

    def _monitor_joystick(self):
        """Monitora eventos do joystick"""
        try:
            # Verificar se há joysticks conectados
            joystick_count = pygame.joystick.get_count()
            if joystick_count > 0:
                self.joystick = pygame.joystick.Joystick(0)
                try:
                    self.joystick.init()
                    print(f"Joystick iniciado: {self.joystick.get_name()}")
                except pygame.error as e:
                    print(f"Erro ao inicializar joystick: {e}")
                    return
            else:
                print("Nenhum joystick encontrado!")
                return

            last_button_press = time.time()
            debounce_time = 0.3

            while self.running:
                for event in pygame.event.get():
                    if event.type == pygame.JOYBUTTONDOWN:
                        current_time = time.time()
                        if current_time - last_button_press > debounce_time:
                            if self.button_callback:
                                self.button_callback("select", self.current_selection)
                            last_button_press = current_time

                    elif event.type == pygame.JOYAXISMOTION:
                        current_time = time.time()
                        if current_time - last_button_press > debounce_time:
                            try:
                                y_axis = self.joystick.get_axis(1)

                                if y_axis > 0.5:  # Movimento para baixo
                                    self.current_selection = min(self.current_selection + 1, self.total_buttons - 1)
                                    if self.button_callback:
                                        self.button_callback("navigate", self.current_selection)
                                    last_button_press = current_time
                                elif y_axis < -0.5:  # Movimento para cima
                                    self.current_selection = max(self.current_selection - 1, 0)
                                    if self.button_callback:
                                        self.button_callback("navigate", self.current_selection)
                                    last_button_press = current_time
                            except pygame.error:
                                pass  # Ignorar erros de leitura do joystick

                time.sleep(0.05)

        except Exception as e:
            print(f"Erro no monitoramento do joystick: {str(e)}")
        finally:
            if self.joystick:
                self.joystick.quit()
            pygame.joystick.quit()
            print("Monitoramento do joystick encerrado.")