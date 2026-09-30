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

Reconexão (30/09/2026): o controle pode sumir e voltar — sobrecorrente no
USB, receptor recolocado, controle que troca de modo. Antes, o leitor pegava
o controle UMA vez, no início, e ficava mudo até reiniciar o serviço. Agora:
  - sumiu → manda "manche solto" (0, 0) e procura de novo a cada 1 s;
  - voltou com um nome de JOYSTICK_NOMES_ACEITOS → volta a comandar;
  - voltou com outro nome (o receptor já voltou como controle da Nintendo)
    → RECUSADO: nenhum evento dele move o robô, e health() diz o porquê.
"""

import threading
import time
import logging
import os

log = logging.getLogger(__name__)

try:
    os.environ.setdefault('SDL_VIDEODRIVER', 'dummy')  # sem display necessário
    # pygame.init() liga TODOS os subsistemas, inclusive o mixer — e o mixer
    # abre e SEGURA uma placa de som que este módulo nunca usa. Medido em
    # 22/09/2026: o main.py mantinha /dev/snd/pcmC0D0p (HDMI-0) preso desde o
    # boot. Pior que desperdício: se a ordem de enumeração das placas mudar,
    # o pygame pode abocanhar justamente a placa da voz.
    os.environ.setdefault('SDL_AUDIODRIVER', 'dummy')  # aqui só interessa o joystick
    import pygame
    pygame.init()
    pygame.joystick.init()
    PYGAME_OK = True
except Exception as e:
    log.warning(f"[JoystickReader] pygame não disponível: {e}")
    PYGAME_OK = False

from config.settings import (JOYSTICK_TIMEOUT_MS, MOTOR_MAX_POWER_PCT,
                             JOYSTICK_NOMES_ACEITOS, JOYSTICK_PROCURA_S)


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
        self._instance_id    = None
        self.last_packet_time = time.time()
        self._last_axis      = 0.0         # debounce dos eixos
        self._proxima_procura = 0.0
        self._recusado       = None        # nome do controle recusado, se houver
        self._motivo         = "procurando o controle"
        self.conexoes        = 0           # 1 = a primeira; > 1 = reconexões
        self.perdas          = 0

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

    def health(self) -> dict:
        """Para a telemetria e o painel."""
        return {
            "conectado":  self._joystick is not None,
            "nome":       self._joystick.get_name() if self._joystick else None,
            "recusado":   self._recusado,
            "motivo":     self._motivo,
            "reconexoes": max(0, self.conexoes - 1),
            "perdas":     self.perdas,
        }

    # ─────────────────────────────────────────
    # LOOP DE MONITORAMENTO
    # ─────────────────────────────────────────
    def _monitor_loop(self):
        while self._running:
            try:
                self._passo()
            except Exception as e:
                # Nunca deixar a thread morrer: sem ela o joystick fica mudo
                # para sempre. Solta o controle e procura de novo.
                log.error(f"[JoystickReader] Erro no loop: {e}")
                self._perdeu(f"erro de leitura: {e}")
                time.sleep(JOYSTICK_PROCURA_S)   # sem inundar o log
            time.sleep(0.02)  # ~50Hz de polling
        self._soltar_device()
        log.info("[JoystickReader] Thread encerrada.")

    def _passo(self, agora: float | None = None):
        """Um ciclo: trata os eventos e, sem controle, procura um."""
        agora = time.time() if agora is None else agora
        for event in pygame.event.get():
            if event.type == pygame.JOYDEVICEREMOVED:
                if (self._joystick is not None
                        and getattr(event, "instance_id", None) == self._instance_id):
                    self._perdeu("o controle sumiu do USB")
                continue
            if event.type == pygame.JOYDEVICEADDED:
                self._proxima_procura = 0.0     # procura já neste ciclo
                continue
            # Só o controle aceito comanda; evento de qualquer outro é ignorado.
            if self._joystick is None or getattr(event, "instance_id",
                                                 self._instance_id) != self._instance_id:
                continue

            if event.type == pygame.JOYAXISMOTION:
                if agora - self._last_axis < self.DEBOUNCE_S:
                    continue
                self._last_axis = agora
                self.last_packet_time = agora
                self._handle_axis()

            elif event.type == pygame.JOYBUTTONDOWN:
                self.last_packet_time = agora
                if self.button_callback:
                    self.button_callback(event.button)

        if self._joystick is None and self._proxima_procura is None:
            # Acabou de perder: espera um intervalo antes de reabrir, para um
            # controle com defeito não virar um liga-desliga a 50 Hz.
            self._proxima_procura = agora + JOYSTICK_PROCURA_S
        if self._joystick is None and agora >= self._proxima_procura:
            self._proxima_procura = agora + JOYSTICK_PROCURA_S
            self._procurar()

    def _procurar(self):
        nomes = []
        for i in range(pygame.joystick.get_count()):
            js = pygame.joystick.Joystick(i)
            nome = js.get_name()
            if nome in JOYSTICK_NOMES_ACEITOS:
                js.init()
                self._joystick    = js
                self._instance_id = js.get_instance_id()
                self._recusado    = None
                self._motivo      = "ok"
                self.conexoes    += 1
                if self.conexoes == 1:
                    log.info(f"[JoystickReader] Conectado: {nome}")
                else:
                    log.warning(f"[JoystickReader] Reconectado: {nome} "
                                f"(reconexão nº {self.conexoes - 1}).")
                return
            nomes.append(nome)
            try:
                js.quit()           # não segura o que não vai usar
            except Exception:
                pass

        if nomes:
            recusado = nomes[0]
            if recusado != self._recusado:
                log.warning(
                    f"[JoystickReader] Controle RECUSADO: '{recusado}' — os eixos "
                    f"só foram conferidos em {list(JOYSTICK_NOMES_ACEITOS)}. O robô "
                    f"NÃO anda pelo joystick. Acorde o controle pelo HOME; se não "
                    f"voltar, o receptor precisa reenumerar (recolocar ou reiniciar).")
            self._recusado = recusado
            self._motivo   = f"controle em modo não conferido: {recusado}"
        else:
            if self._motivo != "nenhum controle no USB":
                log.warning("[JoystickReader] Nenhum controle no USB.")
            self._recusado = None
            self._motivo   = "nenhum controle no USB"

    def _perdeu(self, motivo: str):
        tinha = self._joystick is not None
        self._soltar_device()
        self._motivo = motivo
        self._proxima_procura = None      # o _passo marca a próxima procura
        if tinha:
            self.perdas += 1
            log.warning(f"[JoystickReader] Controle perdido ({motivo}) — "
                        f"manche solto e procurando de novo.")
            # "Manche solto": o último comando não pode ficar valendo. O
            # timeout do loop já pararia os motores; isto limpa também o
            # comando que a malha de rumo usa.
            if self.move_callback:
                self.move_callback(0.0, 0.0)

    def _soltar_device(self):
        if self._joystick is not None:
            try:
                self._joystick.quit()
            except Exception:
                pass
        self._joystick    = None
        self._instance_id = None

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
            # Controle que sumiu no meio da leitura: trata como perda.
            self._perdeu(f"erro de leitura do eixo: {e}")
