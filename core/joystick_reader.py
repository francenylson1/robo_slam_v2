"""
core/joystick_reader.py
Leitura do joystick via dongle USB 2.4GHz.
Migrado e refatorado do robo_slam v1 (joystick_controller.py).
Remoção da dependência de PyQt5. Threading e debounce mantidos do original.

Fluxo:
  JoystickReader → callback(evento, valor)
                  → motor_driver.set_speed(left, right)

Timeout de segurança: se nenhum pacote chegar em JOYSTICK_TIMEOUT_MS,
o safety_loop do main.py força velocidade = 0.
"""

import threading
import time
import logging
import os

log = logging.getLogger(__name__)

try:
    os.environ.setdefault('SDL_VIDEODRIVER', 'dummy')  # sem display necessário
    import pygame
    pygame.init()
    pygame.joystick.init()
    PYGAME_OK = True
except Exception as e:
    log.warning(f"[JoystickReader] pygame não disponível: {e}")
    PYGAME_OK = False

from config.settings import JOYSTICK_TIMEOUT_MS, MOTOR_MAX_POWER_PCT


class JoystickReader:
    """
    Monitora o joystick USB em uma thread dedicada.
    Chama `move_callback(left_pct, right_pct)` a cada evento de eixo.
    Chama `button_callback(button_id)` para botões.
    """

    DEBOUNCE_S      = 0.05   # 50ms entre eventos de eixo
    AXIS_DEAD_ZONE  = 0.10   # Zona morta dos analógicos
    AXIS_FORWARD    = 1      # Eixo Y (frente/trás)
    AXIS_TURN       = 0      # Eixo X (esquerda/direita)

    def __init__(self, move_callback=None, button_callback=None):
        self.move_callback   = move_callback    # fn(left_pct, right_pct)
        self.button_callback = button_callback  # fn(button_id)
        self._running        = False
        self._thread         = None
        self._joystick       = None
        self.last_packet_time = time.time()

    # ─────────────────────────────────────────
    # CONTROLE DA THREAD
    # ─────────────────────────────────────────
    def start(self) -> bool:
        if not PYGAME_OK:
            log.error("[JoystickReader] pygame indisponível — não é possível iniciar.")
            return False
        if self._thread and self._thread.is_alive():
            return True
        self._running = True
        self._thread  = threading.Thread(target=self._monitor_loop,
                                          daemon=True, name="JoystickReader")
        self._thread.start()
        log.info("[JoystickReader] Thread iniciada.")
        return True

    def stop(self):
        self._running = False
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=1.5)
        if self._joystick:
            try:
                self._joystick.quit()
            except Exception:
                pass
        log.info("[JoystickReader] Parado.")

    def is_connected(self) -> bool:
        return self._joystick is not None

    def timed_out(self) -> bool:
        """Retorna True se o joystick ficou silencioso além do timeout de segurança."""
        elapsed_ms = (time.time() - self.last_packet_time) * 1000
        return elapsed_ms > JOYSTICK_TIMEOUT_MS

    # ─────────────────────────────────────────
    # LOOP DE MONITORAMENTO
    # ─────────────────────────────────────────
    def _monitor_loop(self):
        try:
            count = pygame.joystick.get_count()
            if count == 0:
                log.warning("[JoystickReader] Nenhum joystick encontrado.")
                return

            self._joystick = pygame.joystick.Joystick(0)
            self._joystick.init()
            log.info(f"[JoystickReader] Conectado: {self._joystick.get_name()}")

            last_event = time.time()

            while self._running:
                for event in pygame.event.get():

                    if event.type == pygame.JOYAXISMOTION:
                        now = time.time()
                        if now - last_event < self.DEBOUNCE_S:
                            continue
                        last_event = now
                        self.last_packet_time = now
                        self._handle_axis()

                    elif event.type == pygame.JOYBUTTONDOWN:
                        self.last_packet_time = time.time()
                        if self.button_callback:
                            self.button_callback(event.button)

                time.sleep(0.02)  # ~50Hz de polling

        except Exception as e:
            log.error(f"[JoystickReader] Erro no loop: {e}")
        finally:
            if self._joystick:
                try:
                    self._joystick.quit()
                except Exception:
                    pass
            log.info("[JoystickReader] Thread encerrada.")

    # ─────────────────────────────────────────
    # CONVERSÃO EIXOS → VELOCIDADES
    # ─────────────────────────────────────────
    def _handle_axis(self):
        if not self._joystick:
            return
        try:
            raw_fwd  = -self._joystick.get_axis(self.AXIS_FORWARD)  # invertido: cima = positivo
            raw_turn =  self._joystick.get_axis(self.AXIS_TURN)

            # Zona morta
            fwd  = raw_fwd  if abs(raw_fwd)  > self.AXIS_DEAD_ZONE else 0.0
            turn = raw_turn if abs(raw_turn) > self.AXIS_DEAD_ZONE else 0.0

            # Cinemática diferencial: fwd ± turn
            left_pct  = (fwd + turn) * MOTOR_MAX_POWER_PCT
            right_pct = (fwd - turn) * MOTOR_MAX_POWER_PCT

            # Clipping dentro do limite (a Regra 0 já está no motor_driver)
            left_pct  = max(-MOTOR_MAX_POWER_PCT, min(MOTOR_MAX_POWER_PCT, left_pct))
            right_pct = max(-MOTOR_MAX_POWER_PCT, min(MOTOR_MAX_POWER_PCT, right_pct))

            if self.move_callback:
                self.move_callback(left_pct, right_pct)

        except pygame.error as e:
            log.warning(f"[JoystickReader] Erro de leitura do eixo: {e}")
