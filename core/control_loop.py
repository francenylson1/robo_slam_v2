"""
core/control_loop.py
Loop de controle 50Hz reaproveitável — fonte única de verdade para o main.py
(operação) e para scripts/validate_phase1.py (validação do Gate da Fase 1).

Mantido sem dependências de Flask/OpenCV/GPIO para poder ser importado tanto pelo
sistema completo quanto pelo harness de validação sem efeitos colaterais.
"""

import time
import logging

log = logging.getLogger(__name__)

CYCLE_S          = 0.020   # 20ms = 50Hz
_SPIN_GUARD_S    = 0.002   # busy-spin nos últimos ~2ms para cravar o jitter
LATE_THRESHOLD_MS = 5.0    # ciclo é "atrasado" se o jitter ≥ este valor (Gate Fase 1)
# Obs.: time.sleep no Python 3.11+ já usa timer de alta resolução no Windows e
# ~1ms no Linux, então não é necessário winmm.timeBeginPeriod.


def sleep_until(deadline: float):
    """
    Dorme até `deadline` (relógio time.perf_counter) com sleep híbrido: dorme a
    maior parte do intervalo e faz busy-spin nos últimos ~2ms. Robusto contra a
    granularidade grosseira do timer do SO (especialmente Windows), mantendo o
    jitter do ciclo abaixo de 5ms tanto na Pi (Linux) quanto no PC de dev.
    """
    coarse = deadline - _SPIN_GUARD_S
    now = time.perf_counter()
    if coarse > now:
        time.sleep(coarse - now)
    while time.perf_counter() < deadline:
        pass  # busy-spin curto e preciso


def run_control_loop(state, *, motors, bumper, heading, battery,
                     joystick=None, watchdog=None, assist=None,
                     duration_s: float | None = None):
    """
    Executa o loop de percepção/segurança a 50Hz com agendamento por deadline
    absoluto (sem deriva acumulada) e medição de jitter via time.perf_counter().

    Parâmetros:
      state       — dict de estado compartilhado (lê "running"/"mode", escreve
                    "blocked"/"yaw_error"/"battery"/"loop").
      motors      — MotorDriver (precisa de .stop()).
      bumper      — SafetyBumper (lê .blocked_front).
      heading     — HeadingLock (lê .get_yaw_error()).
      battery     — BatteryMonitor (lê .get_status()).
      joystick    — JoystickReader opcional (lê .timed_out()); None em validação.
      assist      — HeadingAssist opcional (malha de rumo da Fase 3); None
                    desliga o passo 3 por completo.
      watchdog    — HardwareWatchdog opcional; alimentado a cada ciclo (o próprio
                    watchdog limita a escrita real a 1x por segundo).
      duration_s  — None → roda até state["running"] virar False (operação normal);
                    N    → roda por ~N segundos (usado no harness de validação).

    Publica métricas em state["loop"]: hz, jitter_ms_max, jitter_ms_avg, cycles.
    """
    start      = time.perf_counter()
    deadline   = start
    cycles     = 0
    late_count = 0          # ciclos com jitter ≥ LATE_THRESHOLD_MS
    jitter_max = 0.0
    jitter_sum = 0.0
    last_log   = start

    while state.get("running", True):
        deadline += CYCLE_S

        # 0. WATCHDOG — prova de vida do loop (Fase 1.5)
        if watchdog is not None:
            watchdog.pet()
            state["watchdog"] = watchdog.health()

        # 1. PERCEPÇÃO
        state["blocked"]   = bumper.blocked_front
        state["lidar"]     = bumper.health()
        state["yaw_error"] = heading.get_yaw_error()
        # Rumo na telemetria: o BNO085 ainda NÃO comanda motor nenhum (o passo 3
        # é implementação da Fase 3), mas mostrar o yaw no painel é o que permite
        # ver, antes de fechar a malha, se o sensor está vivo e coerente.
        state["heading"]   = {"yaw_deg":   round(heading.yaw_deg, 2),
                              "yaw_error": round(state["yaw_error"], 2),
                              "healthy":   heading.healthy,
                              "resets":    getattr(heading, "resets_total", 0)}
        state["battery"]   = battery.get_status()

        # 2. SEGURANÇA — TIMEOUT DO JOYSTICK
        if joystick is not None and state.get("mode") == "JOYSTICK" and joystick.timed_out():
            motors.stop()

        # 2b. E-STOP GERAL DA FROTA (Torre de Controle) — re-asserta a parada
        # a cada ciclo enquanto o estado retained "on" não for liberado.
        if state.get("fleet_estop"):
            motors.stop()

        # 3. CORREÇÃO DE RUMO (somente em linha reta, no modo JOYSTICK)
        # Fecha a malha com o BNO085 — ver core/heading_assist.py. Nasce
        # desligada (HEADING_ASSIST_ENABLED), e é fail-soft: sem sensor ou fora
        # de uma reta, o comando do operador passa intacto.
        if assist is not None and state.get("mode") == "JOYSTICK"                 and not state.get("blocked") and not state.get("fleet_estop"):
            cmd = state.get("cmd_motores")
            if cmd is not None:
                novo = assist.corrigir(cmd[0], cmd[1],
                                       heading.yaw_deg, heading.healthy)
                if novo is not None:
                    motors.set_speed(novo[0], novo[1])
                    state["heading_corr_pct"] = round((novo[1] - novo[0]) / 2.0, 3)
                else:
                    state["heading_corr_pct"] = 0.0
        if assist is not None:
            state["heading_assist"] = assist.health()

        # 4. MODO AUTÔNOMO — delegado ao slam_nav.py (Fase 4)
        # if state.get("mode") == "AUTONOMO":
        #     slam_nav.tick(state)

        # Aguarda o deadline absoluto do ciclo
        sleep_until(deadline)

        # MÉTRICA DE JITTER: atraso do despertar em relação ao deadline ideal
        jitter      = abs((time.perf_counter() - deadline) * 1000.0)
        cycles     += 1
        jitter_sum += jitter
        if jitter > jitter_max:
            jitter_max = jitter
        if jitter >= LATE_THRESHOLD_MS:
            late_count += 1

        now           = time.perf_counter()
        elapsed_total = now - start
        state["loop"] = {
            "hz":            round(cycles / elapsed_total, 1) if elapsed_total > 0 else 0.0,
            "jitter_ms_max": round(jitter_max, 3),
            "jitter_ms_avg": round(jitter_sum / cycles, 3),
            "late_count":    late_count,
            "late_pct":      round(100.0 * late_count / cycles, 3),
            "cycles":        cycles,
        }

        # Resumo periódico (~5s)
        if now - last_log >= 5.0:
            lp = state["loop"]
            log.info(f"[loop] {lp['hz']:.1f}Hz | jitter avg {lp['jitter_ms_avg']:.2f}ms "
                     f"max {lp['jitter_ms_max']:.2f}ms | atrasados {lp['late_pct']:.1f}% "
                     f"| {lp['cycles']} ciclos")
            last_log = now

        if duration_s is not None and elapsed_total >= duration_s:
            break

    return state["loop"]
