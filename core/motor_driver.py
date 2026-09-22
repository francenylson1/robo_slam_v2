"""
core/motor_driver.py
Núcleo de controle dos motores — Frota Mista v2.

⚠️  ATENÇÃO — LEIA ANTES DE EDITAR  ⚠️
A lógica de pinos, direção e PID desta classe foi validada fisicamente no robô real
durante o desenvolvimento do robo_slam v1 (commit d3727e0 / tag v1.0-estavel-base).
Qualquer alteração nos valores de PIN_*, DIR_* ou nos ganhos PID requer
TESTE FÍSICO obrigatório no robô antes de ser aceita.

Novidades v2 (não alteram a lógica de hardware):
  • Regra de Segurança Nº 0: clipping rígido em MOTOR_MAX_POWER_PCT (15%)
  • Emergency Stop automático se potência ≥ MOTOR_EMERGENCY_STOP_PCT (20%)
  • Modo MOCK automático em PC/notebook (sem GPIO)
  • Sem dependência de PyQt5 — standalone Python puro
"""

import time
import threading
import logging

from config.settings import (
    GPIO_AVAILABLE, MOCK_MODE,
    PIN_DIR_E, PIN_BREAK_E, PIN_PWM_E, PIN_HALL_E,
    PIN_DIR_D, PIN_BREAK_D, PIN_PWM_D, PIN_HALL_D,
    DIR_E_FORWARD, DIR_E_REVERSE,
    DIR_D_FORWARD, DIR_D_REVERSE,
    PWM_FREQUENCY_HZ,
    BRAKE_HOLD_S, BRAKE_LEVEL_HOLD, BRAKE_LEVEL_FREE,
    HALL_POLL_INTERVAL_S, HALL_DEBOUNCE_S, SPEED_UPDATE_INTERVAL,
    PID_KP, PID_KI, PID_KD, PID_OUTPUT_MIN, PID_OUTPUT_MAX, PID_LOOP_HZ,
    MOTOR_MAX_POWER_PCT, MOTOR_EMERGENCY_STOP_PCT,
    TICKS_PER_REVOLUTION,
)
from core.pid_controller import PIDController

log = logging.getLogger(__name__)

if GPIO_AVAILABLE:
    try:
        import RPi.GPIO as GPIO
    except (ImportError, RuntimeError):
        log.warning("RPi.GPIO não pôde ser importado — alternando para MOCK.")
        GPIO = None
else:
    GPIO = None


class MotorDriver:
    """
    Controla os dois motores de hoverboard via drivers ZS-X11H V2.

    Modos de operação:
      REAL  — GPIO da Raspberry Pi ativo, PID habilitado, encoders Hall ativos.
      MOCK  — Sem GPIO. Registra comandos em log. Usado nas Fases 0, 1 e 2.
    """

    def __init__(self):
        self._lock          = threading.Lock()
        self._shutdown      = threading.Event()
        self._pid_enabled   = False
        self._emergency     = False
        self._stopped       = True    # estado lógico p/ deduplicar logs de stop()

        # Retenção ao parar: o driver fica LIGADO segurando a posição por
        # BRAKE_HOLD_S e depois solta. Ver config/settings.py.
        self._timer_ret     = None
        self._lock_ret      = threading.Lock()

        # Contadores de encoder (odometria)
        self.left_hall_ticks  = 0
        self.right_hall_ticks = 0
        self.left_ticks_odo   = 0
        self.right_ticks_odo  = 0

        # Velocidade atual (ticks/s)
        self.current_left_tps  = 0.0
        self.current_right_tps = 0.0
        self._last_speed_time  = time.time()

        # PID — ganhos migrados do legado v1
        self.pid_left  = PIDController(PID_KP, PID_KI, PID_KD,
                                        output_limits=(PID_OUTPUT_MIN, PID_OUTPUT_MAX))
        self.pid_right = PIDController(PID_KP, PID_KI, PID_KD,
                                        output_limits=(PID_OUTPUT_MIN, PID_OUTPUT_MAX))

        if GPIO and GPIO_AVAILABLE:
            self._init_gpio()
            self._start_threads()
            log.info("[MotorDriver] Modo REAL — GPIO inicializado.")
        else:
            log.info("[MotorDriver] Modo MOCK — nenhuma saída física.")

        # O robô NASCE segurando (ver _init_gpio) e solta depois de
        # BRAKE_HOLD_S, igual a qualquer outra parada. Sem isto ele ficaria
        # retido para sempre depois do boot — consumindo exatamente na espera
        # longa que a opção 2 quer poupar.
        self._agendar_soltura()

    # ─────────────────────────────────────────
    # INICIALIZAÇÃO GPIO
    # ─────────────────────────────────────────
    def _init_gpio(self):
        GPIO.setmode(GPIO.BCM)
        GPIO.setwarnings(False)

        for pin in [PIN_DIR_E, PIN_BREAK_E, PIN_PWM_E,
                    PIN_DIR_D, PIN_BREAK_D, PIN_PWM_D]:
            GPIO.setup(pin, GPIO.OUT)

        GPIO.setup(PIN_HALL_E, GPIO.IN, pull_up_down=GPIO.PUD_DOWN)
        GPIO.setup(PIN_HALL_D, GPIO.IN, pull_up_down=GPIO.PUD_DOWN)

        self._last_hall_E = GPIO.input(PIN_HALL_E)
        self._last_hall_D = GPIO.input(PIN_HALL_D)

        self.pwm_E = GPIO.PWM(PIN_PWM_E, PWM_FREQUENCY_HZ)
        self.pwm_D = GPIO.PWM(PIN_PWM_D, PWM_FREQUENCY_HZ)
        self.pwm_E.start(0)
        self.pwm_D.start(0)

        # Estado inicial: SEGURANDO (PWM já está em 0). O nível ALTO daqui era
        # o que deixava o robô solto no boot e em toda parada.
        GPIO.output(PIN_BREAK_E, BRAKE_LEVEL_HOLD)
        GPIO.output(PIN_BREAK_D, BRAKE_LEVEL_HOLD)

    def _start_threads(self):
        threading.Thread(target=self._hall_monitor_loop,
                         daemon=True, name="HallMonitor").start()
        threading.Thread(target=self._pid_loop,
                         daemon=True, name="PIDLoop").start()

    # ─────────────────────────────────────────
    # RETENÇÃO AO PARAR (Fase 3)
    # ─────────────────────────────────────────
    def _escrever_retencao(self, nivel: int):
        if GPIO and GPIO_AVAILABLE:
            try:
                GPIO.output(PIN_BREAK_E, nivel)
                GPIO.output(PIN_BREAK_D, nivel)
            except Exception:
                pass

    def _cancelar_retencao(self):
        """Chamado ao voltar a mover: o temporizador não pode soltar o driver
        no meio de um movimento."""
        with self._lock_ret:
            if self._timer_ret is not None:
                self._timer_ret.cancel()
                self._timer_ret = None

    def _agendar_soltura(self):
        """Solta a retenção depois de BRAKE_HOLD_S parado. Zero = segurar
        sempre (para operação em rampa)."""
        if BRAKE_HOLD_S <= 0:
            return
        with self._lock_ret:
            if self._timer_ret is not None:
                self._timer_ret.cancel()
            self._timer_ret = threading.Timer(BRAKE_HOLD_S, self._soltar_retencao)
            self._timer_ret.daemon = True
            self._timer_ret.start()

    def _soltar_retencao(self):
        """Só solta se ainda estiver parado — um movimento que tenha começado
        nesse meio tempo já cancelou o temporizador, mas a checagem é barata."""
        if not self._stopped:
            return
        self._escrever_retencao(BRAKE_LEVEL_FREE)
        log.info(f"[MotorDriver] Retenção solta após {BRAKE_HOLD_S:.0f}s parado.")

    # ─────────────────────────────────────────
    # REGRA DE SEGURANÇA Nº 0
    # ─────────────────────────────────────────
    def _apply_safety_clip(self, power: float) -> float:
        """
        Aplica clipping rígido.
        Qualquer potência ≥ MOTOR_EMERGENCY_STOP_PCT aciona Emergency Stop.
        Potência máxima permitida: MOTOR_MAX_POWER_PCT (15%).
        """
        abs_power = abs(power)
        if abs_power >= MOTOR_EMERGENCY_STOP_PCT:
            log.critical(
                f"[REGRA 0] Potência {abs_power:.1f}% ≥ {MOTOR_EMERGENCY_STOP_PCT}% "
                "→ EMERGENCY STOP ativado!"
            )
            self._trigger_emergency_stop()
            return 0.0
        clipped = min(abs_power, MOTOR_MAX_POWER_PCT)
        return clipped if power >= 0 else -clipped

    def _trigger_emergency_stop(self):
        """Para tudo imediatamente e trava o sistema."""
        self._emergency    = True
        self._pid_enabled  = False
        self._cancelar_retencao()      # emergência NÃO solta sozinha
        if GPIO and GPIO_AVAILABLE:
            try:
                self.pwm_E.ChangeDutyCycle(0)
                self.pwm_D.ChangeDutyCycle(0)
            except Exception:
                pass
        # Segura e NÃO agenda soltura: numa emergência o robô fica retido até
        # alguém reiniciar o sistema de propósito.
        self._escrever_retencao(BRAKE_LEVEL_HOLD)
        log.critical("[MotorDriver] EMERGENCY STOP — sistema desligado.")

    # ─────────────────────────────────────────
    # INTERFACE PÚBLICA
    # ─────────────────────────────────────────
    def set_speed(self, left_pct: float, right_pct: float):
        """
        Define a velocidade direta em % (-100 a +100).
        A Regra 0 aplica clipping automático para ≤ 15%.

        Lógica direcional validada no hardware (v1):
          left > 0  → FRENTE  (dir_E = HIGH)
          left < 0  → TRÁS    (dir_E = LOW)
          right > 0 → FRENTE  (dir_D = LOW  ← oposto ao esquerdo)
          right < 0 → TRÁS    (dir_D = HIGH ← oposto ao esquerdo)
        """
        if self._emergency:
            log.warning("[MotorDriver] Emergency ativo — comando ignorado.")
            return

        if left_pct == 0 and right_pct == 0:
            self.stop()
            return

        left_safe  = self._apply_safety_clip(left_pct)
        right_safe = self._apply_safety_clip(right_pct)
        self._cancelar_retencao()    # não soltar o driver no meio do movimento
        self._stopped = False

        if MOCK_MODE:
            log.info(f"[MOCK] set_speed → L:{left_safe:+.1f}%  R:{right_safe:+.1f}%")
            return

        if GPIO and GPIO_AVAILABLE:
            self._write_motor("left",  left_safe)
            self._write_motor("right", right_safe)

    def set_target_speed_tps(self, left_tps: float, right_tps: float):
        """Define velocidade alvo em ticks/s para o loop PID."""
        if self._emergency:
            return
        self.pid_left.set_setpoint(left_tps)
        self.pid_right.set_setpoint(right_tps)
        self._cancelar_retencao()    # não soltar o driver no meio do movimento
        self._stopped = False
        if not self._pid_enabled:
            self._pid_enabled = True
        if MOCK_MODE:
            log.info(f"[MOCK] set_target_tps → L:{left_tps:.1f}  R:{right_tps:.1f}")

    def stop(self):
        """
        Para os motores com segurança. Idempotente: pode (e deve) ser chamada
        a cada ciclo do loop de segurança — a escrita física é re-assertada
        sempre, mas o log só sai na transição movimento → parado.
        """
        self._pid_enabled = False
        self.pid_left.reset()
        self.pid_right.reset()
        transicao = not self._stopped
        if GPIO and GPIO_AVAILABLE:
            try:
                # PWM zerado SEMPRE — é a re-assertação de segurança que o loop
                # de 50 Hz depende.
                self.pwm_E.ChangeDutyCycle(0)
                self.pwm_D.ChangeDutyCycle(0)
            except Exception:
                pass
        # A retenção é agendada só na transição movimento → parado. Se fosse a
        # cada chamada, o loop de 50 Hz reagendaria o temporizador para sempre e
        # ele nunca soltaria.
        if transicao:
            self._escrever_retencao(BRAKE_LEVEL_HOLD)
            self._stopped = True
            self._agendar_soltura()
            if MOCK_MODE:
                log.info("[MOCK] stop() — segurando por "
                         f"{BRAKE_HOLD_S:.0f}s")
        self._stopped = True

    def set_brake(self, hold: bool):
        """
        SEGURA (True) ou SOLTA (False) o robô, com PWM em ZERO nos dois lados.

        Fala a linguagem do efeito MEDIDO, não a do nome do pino: segurar é
        nível BAIXO (driver ligado, mantendo posição) e soltar é nível ALTO
        (driver desligado, roda livre). Foi assim que se descobriu, em
        22/09/2026, que o projeto tinha os dois invertidos — o professor
        empurrou o robô e ele andou. Ler o pino não prova o efeito.

        Fica no motor_driver de propósito: é o único lugar que pode tocar em
        GPIO (Regra Nº 0, verificada por varredura estática no harness).
        """
        if self._emergency:
            log.warning("[MotorDriver] Emergency ativo — set_brake ignorado.")
            return
        self._cancelar_retencao()    # quem chama aqui quer mandar no estado
        if MOCK_MODE:
            log.info(f"[MOCK] set_brake(hold={hold})")
            return
        if not (GPIO and GPIO_AVAILABLE):
            return
        # PWM zerado ANTES de mexer no driver, sempre.
        self.pwm_E.ChangeDutyCycle(0)
        self.pwm_D.ChangeDutyCycle(0)
        self._escrever_retencao(BRAKE_LEVEL_HOLD if hold else BRAKE_LEVEL_FREE)

    def hall_raw(self) -> dict:
        """Nível BRUTO dos dois pinos de encoder, sem contagem nem debounce.

        Diagnóstico da Etapa B: separa "o sensor não gera sinal" de "o sinal
        chega mas a contagem falha". Só LÊ pino — não comanda nada.
        """
        if not (GPIO and GPIO_AVAILABLE):
            return {"left": None, "right": None}
        return {"left":  GPIO.input(PIN_HALL_E),
                "right": GPIO.input(PIN_HALL_D)}

    def get_and_reset_ticks(self) -> dict:
        """Retorna e zera os ticks de odometria. Usado pelo slam_nav.py."""
        with self._lock:
            left_dir  = 1 if self.pid_left.setpoint  >= 0 else -1
            right_dir = 1 if self.pid_right.setpoint >= 0 else -1
            ticks = {
                "left":  self.left_ticks_odo  * left_dir,
                "right": self.right_ticks_odo * right_dir,
            }
            self.left_ticks_odo  = 0
            self.right_ticks_odo = 0
        return ticks

    def cleanup(self):
        """Libera recursos GPIO com segurança."""
        self._shutdown.set()
        self.stop()
        self._cancelar_retencao()
        if GPIO and GPIO_AVAILABLE:
            time.sleep(0.15)          # deixa a thread do PID terminar o ciclo
            # Os PWMs precisam morrer ANTES do GPIO.cleanup(). Ele invalida o
            # handle do chip, e o destrutor do objeto PWM do rpi-lgpio ainda
            # chama tx_pwm() depois — cuspindo TypeError no encerramento. Era
            # inofensivo (tudo já estava parado), mas é ruído que um dia
            # esconde um erro de verdade. Visto em 22/09/2026, na Etapa A.
            import gc
            pwms = [getattr(self, "pwm_E", None), getattr(self, "pwm_D", None)]
            self.pwm_E = self.pwm_D = None
            for pwm in pwms:
                if pwm is None:
                    continue
                try:
                    pwm.stop()
                except Exception:
                    pass
            del pwms, pwm
            gc.collect()              # destrutores rodam com o handle ainda vivo
            try:
                GPIO.cleanup()
            except Exception:
                pass
        log.info("[MotorDriver] GPIO liberado.")

    # ─────────────────────────────────────────
    # ESCRITA FÍSICA NO GPIO
    # ─────────────────────────────────────────
    def _write_motor(self, side: str, power_pct: float):
        """
        Escreve direção e duty cycle no hardware.
        Lógica direcional: igual ao gpio_test.py validado no v1.
        """
        if side == "left":
            pin_dir   = PIN_DIR_E
            pin_break = PIN_BREAK_E
            pwm       = self.pwm_E
            fwd_val   = DIR_E_FORWARD
        else:
            pin_dir   = PIN_DIR_D
            pin_break = PIN_BREAK_D
            pwm       = self.pwm_D
            fwd_val   = DIR_D_FORWARD

        rev_val = 1 - fwd_val  # oposto lógico

        if abs(power_pct) < 1.0:
            # Este lado fica LIVRE (driver desligado) — é o que já acontecia;
            # só o nome mudou para dizer o efeito real.
            pwm.ChangeDutyCycle(0)
            GPIO.output(pin_break, BRAKE_LEVEL_FREE)
            return

        GPIO.output(pin_break, BRAKE_LEVEL_HOLD)   # driver ligado para acionar
        GPIO.output(pin_dir, fwd_val if power_pct > 0 else rev_val)
        pwm.ChangeDutyCycle(min(abs(power_pct), MOTOR_MAX_POWER_PCT))

    # ─────────────────────────────────────────
    # THREAD: ENCODER HALL (polling)
    # ─────────────────────────────────────────
    def _hall_monitor_loop(self):
        if not (GPIO and GPIO_AVAILABLE):
            return
        while not self._shutdown.is_set():
            try:
                # Motor esquerdo
                state_E = GPIO.input(PIN_HALL_E)
                if state_E == 1 and self._last_hall_E == 0:
                    time.sleep(HALL_DEBOUNCE_S)
                    if GPIO.input(PIN_HALL_E) == 1:
                        with self._lock:
                            self.left_hall_ticks  += 1
                            self.left_ticks_odo   += 1
                self._last_hall_E = state_E

                # Motor direito
                state_D = GPIO.input(PIN_HALL_D)
                if state_D == 1 and self._last_hall_D == 0:
                    time.sleep(HALL_DEBOUNCE_S)
                    if GPIO.input(PIN_HALL_D) == 1:
                        with self._lock:
                            self.right_hall_ticks += 1
                            self.right_ticks_odo  += 1
                self._last_hall_D = state_D

            except RuntimeError:
                break

            time.sleep(HALL_POLL_INTERVAL_S)

    # ─────────────────────────────────────────
    # THREAD: LOOP PID (20Hz)
    # ─────────────────────────────────────────
    def _pid_loop(self):
        if not (GPIO and GPIO_AVAILABLE):
            return
        interval = 1.0 / PID_LOOP_HZ
        while not self._shutdown.is_set():
            if not self._pid_enabled:
                time.sleep(0.1)
                continue

            self._update_speed()

            left_power  = self.pid_left.update(self.current_left_tps)
            right_power = self.pid_right.update(self.current_right_tps)

            # Regra 0 no loop PID
            left_power  = self._apply_safety_clip(left_power)
            right_power = self._apply_safety_clip(right_power)

            if not self._emergency:
                self._write_motor("left",  left_power)
                self._write_motor("right", right_power)

            time.sleep(interval)

    def _update_speed(self):
        now = time.time()
        dt  = now - self._last_speed_time
        if dt >= SPEED_UPDATE_INTERVAL:
            with self._lock:
                self.current_left_tps  = self.left_hall_ticks  / dt
                self.current_right_tps = self.right_hall_ticks / dt
                self.left_hall_ticks   = 0
                self.right_hall_ticks  = 0
            self._last_speed_time = now
