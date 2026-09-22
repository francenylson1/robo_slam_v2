#!/usr/bin/env python3
"""
scripts/validate_phase1.py
Harness de validação do Gate da Fase 1 (Percepção) — Frota Mista v2.

Prova, em modo MOCK, os quatro critérios do Gate (+ blindagem da Fase 1.5):
  1. Leitura de tensão da bateria com precisão ±0.5V
  2. LIDAR (bumper) bloqueia a flag com objeto a 45cm
  3. BNO085 (heading) retorna Yaw estável sem drift (lógica/normalização)
  4. Loop 50Hz sem jitter acima de 5ms (medido com time.perf_counter())
  5. Fase 1.5 — bumper FAIL-CLOSED: sem varredura fresca → bloqueado
  6. Fase 1.5 — WATCHDOG: loop alimenta; travamento seria detectado

Uso (no PC de dev ou na Raspberry Pi via SSH):
    python3 scripts/validate_phase1.py

Saída: relatório verde/vermelho por item. Exit code 0 (tudo PASS) / 1 (qualquer FAIL).

NOTA: este script prova a LÓGICA e a MATEMÁTICA em MOCK. A confirmação FÍSICA
(multímetro, objeto real a 45cm, BNO085 sem drift por alguns minutos) é um
checklist de hardware separado, descrito no README.
"""

import os
import sys

# Garante saída UTF-8 mesmo em consoles legados (Windows cp1252).
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

# Força MOCK ANTES de importar config.settings (decide MOCK_MODE no import).
os.environ["FROTA_MOCK"] = "1"

# Permite rodar a partir da raiz do projeto ou de dentro de scripts/.
_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from sensors.battery_monitor import BatteryMonitor
from sensors.safety_bumper   import SafetyBumper
from sensors.heading_lock    import HeadingLock
from core.control_loop       import run_control_loop
from core.watchdog           import HardwareWatchdog
from config.settings import (
    OBSTACLE_STOP_DISTANCE_M, BATTERY_MIN_V, BATTERY_MAX_V,
    LIDAR_FRESH_TIMEOUT_S,
)

# ─────────────────────────────────────────────
# Util de relatório
# ─────────────────────────────────────────────
# Cores ANSI só quando a saída é um terminal compatível (evita lixo no console
# legado do Windows e em pipes/arquivos).
_USE_COLOR = sys.stdout.isatty() and os.name != "nt"
GREEN = "\033[92m" if _USE_COLOR else ""
RED   = "\033[91m" if _USE_COLOR else ""
BOLD  = "\033[1m"  if _USE_COLOR else ""
RESET = "\033[0m"  if _USE_COLOR else ""

_results = []   # (nome, ok, detalhe)


def check(name: str, ok: bool, detail: str = ""):
    _results.append((name, ok, detail))
    tag = f"{GREEN}PASS{RESET}" if ok else f"{RED}FALHA{RESET}"
    line = f"  [{tag}] {name}"
    if detail:
        line += f"  — {detail}"
    print(line)


def section(title: str):
    print(f"\n{BOLD}{title}{RESET}")


# ─────────────────────────────────────────────
# 0. REGRA DE SEGURANÇA Nº 0 — o teto de 15%
#
# Esta seção existe porque a regra mais importante do projeto não tinha
# NENHUMA verificação automatizada (descoberto em 22/09/2026, a pedido do
# professor). Um refactor poderia afrouxar o teto em silêncio e os três
# gates continuariam verdes.
#
# Roda ANTES de tudo, e num harness que já é regressão obrigatória — assim a
# regra não depende de alguém lembrar de rodar um script extra.
# ─────────────────────────────────────────────
def test_regra_zero():
    section("0. REGRA Nº 0 — teto de 15% e Emergency Stop em ≥20%")
    from core.motor_driver import MotorDriver
    from config.settings import MOTOR_MAX_POWER_PCT, MOTOR_EMERGENCY_STOP_PCT

    # 0a. os valores SÃO a regra: mudou o número, falhou o gate
    check("Teto de potência = 15% (MOTOR_MAX_POWER_PCT)",
          MOTOR_MAX_POWER_PCT == 15.0, f"{MOTOR_MAX_POWER_PCT}%")
    check("Emergency Stop em ≥20% (MOTOR_EMERGENCY_STOP_PCT)",
          MOTOR_EMERGENCY_STOP_PCT == 20.0, f"{MOTOR_EMERGENCY_STOP_PCT}%")
    check("O teto é menor que o gatilho de emergência",
          MOTOR_MAX_POWER_PCT < MOTOR_EMERGENCY_STOP_PCT)

    # 0a-bis. o PID não pode PASSAR do teto — se passar, ele mesmo dispara a
    #         emergência e trava o robô na operação normal (bloqueador achado
    #         em 22/09/2026, antes do primeiro movimento da Fase 3)
    from config.settings import PID_OUTPUT_MIN, PID_OUTPUT_MAX
    check("O PID satura NO teto, não acima dele",
          PID_OUTPUT_MAX <= MOTOR_MAX_POWER_PCT
          and PID_OUTPUT_MIN >= -MOTOR_MAX_POWER_PCT,
          f"PID em [{PID_OUTPUT_MIN}, {PID_OUTPUT_MAX}]")
    check("O PID nunca alcança o gatilho de emergência sozinho",
          PID_OUTPUT_MAX < MOTOR_EMERGENCY_STOP_PCT)

    # 0b. o clipping, no ponto único onde a regra vive
    m = MotorDriver()
    check("Abaixo do teto passa intacto (10% → 10%)",
          m._apply_safety_clip(10.0) == 10.0)
    check("Acima do teto é cortado, não recusado (16% → 15%)",
          m._apply_safety_clip(16.0) == MOTOR_MAX_POWER_PCT)
    check("Ré obedece ao mesmo teto (-16% → -15%)",
          m._apply_safety_clip(-16.0) == -MOTOR_MAX_POWER_PCT)
    check("Exatamente no teto é permitido (15% → 15%)",
          m._apply_safety_clip(15.0) == MOTOR_MAX_POWER_PCT)

    # 0c. o Emergency Stop — as linhas CRITICAL no log abaixo são ESPERADAS
    m2 = MotorDriver()
    saida = m2._apply_safety_clip(20.0)
    check("20% aciona Emergency Stop e devolve potência ZERO",
          saida == 0.0 and m2._emergency is True, f"devolveu {saida}")
    check("Depois do Emergency Stop, novo comando é IGNORADO",
          (m2.set_speed(10.0, 10.0) or True) and m2._emergency is True)

    # 0d. pela API pública, que é por onde o robô é comandado de verdade
    m3 = MotorDriver()
    m3.set_speed(80.0, 80.0)
    check("set_speed(80%, 80%) não move o robô — dispara a Regra 0",
          m3._emergency is True)

    m4 = MotorDriver()
    m4.set_speed(12.0, -12.0)
    check("Operação normal (12%) NÃO dispara emergência",
          m4._emergency is False)

    # 0e. o operador não consegue furar o teto nem com o manche no fim
    fonte_joy = open(os.path.join(_ROOT, "core", "joystick_reader.py"),
                     encoding="utf-8").read()
    check("O joystick ESCALA pelo teto (manche cheio = 15%, não 100%)",
          "* MOTOR_MAX_POWER_PCT" in fonte_joy)
    check("O joystick ainda aplica clamp explícito depois da escala",
          "min(MOTOR_MAX_POWER_PCT" in fonte_joy)

    # 0e-bis. RETENÇÃO AO PARAR (Fase 3) — o "freio" é um enable INVERTIDO.
    #         Provado fisicamente em 22/09/2026 empurrando o robô: nível BAIXO
    #         segura, nível ALTO solta. O código fazia o contrário ao parar, e
    #         o robô ficava livre toda vez que parava.
    from config.settings import (BRAKE_HOLD_S, BRAKE_LEVEL_FREE,
                                 BRAKE_LEVEL_HOLD)
    check("Segurar e soltar são níveis OPOSTOS",
          BRAKE_LEVEL_HOLD != BRAKE_LEVEL_FREE,
          f"segura={BRAKE_LEVEL_HOLD} solta={BRAKE_LEVEL_FREE}")
    check("Segurar é o nível BAIXO (driver ligado) — medido no robô",
          BRAKE_LEVEL_HOLD == 0)

    m5 = MotorDriver()
    m5.set_speed(10.0, 10.0)
    check("Mover marca o robô como NÃO parado", m5._stopped is False)
    m5.stop()
    check("Parar marca o robô como parado e agenda a soltura",
          m5._stopped is True)
    # O loop de 50 Hz chama stop() a cada ciclo: se cada chamada reagendasse o
    # temporizador, a retenção nunca soltaria. Só a TRANSIÇÃO agenda.
    antes = m5._timer_ret
    m5.stop(); m5.stop()
    check("stop() repetido NÃO reagenda a soltura (o loop chama a 50 Hz)",
          m5._timer_ret is antes)
    m5.set_speed(10.0, 10.0)
    check("Voltar a mover CANCELA a soltura agendada",
          m5._timer_ret is None)
    m5.stop()

    check("Há tempo de retenção configurado (0 = segurar sempre, p/ rampa)",
          BRAKE_HOLD_S >= 0, f"{BRAKE_HOLD_S}s")

    # 0f. ninguém pode desviar do ponto único de controle
    #     (é assim que um bypass futuro é pego: escrevendo direto no PWM/GPIO)
    infratores = []
    for pasta, _, arquivos in os.walk(_ROOT):
        if "old_versions" in pasta or "__pycache__" in pasta or ".git" in pasta:
            continue
        for nome in arquivos:
            if not nome.endswith(".py"):
                continue
            caminho = os.path.join(pasta, nome)
            if os.path.normpath(caminho).endswith(
                    os.path.join("core", "motor_driver.py")):
                continue        # o dono legítimo do hardware
            if os.path.abspath(caminho) == os.path.abspath(__file__):
                continue        # este arquivo cita os nomes para procurá-los
            try:
                texto = open(caminho, encoding="utf-8").read()
            except Exception:
                continue
            if "ChangeDutyCycle" in texto or "GPIO.output" in texto:
                infratores.append(os.path.relpath(caminho, _ROOT))

    check("Só o motor_driver.py toca em PWM/GPIO — ninguém contorna a Regra 0",
          not infratores,
          ("contornando: " + ", ".join(infratores)) if infratores else "")


# ─────────────────────────────────────────────
# 1. BATERIA — precisão ±0.5V
# ─────────────────────────────────────────────
def test_battery():
    section("1. Bateria — precisão ±0.5V (round-trip Vbat→Vout→Vbat)")
    bat = BatteryMonitor()
    last_percent = None
    monotonic_ok = True
    for vbat in [42.0, 40.0, 38.0, 36.0, 33.0, 30.0]:
        bat.set_mock_voltage(vbat)
        status = bat.read_once()
        measured = status["voltage_v"]
        err = abs(measured - vbat)
        check(f"Vbat={vbat:.1f}V → leitura {measured:.2f}V (erro {err:.3f}V ≤ 0.5)",
              err <= 0.5)
        # percent deve cair monotonicamente conforme a tensão cai
        if last_percent is not None and status["percent"] > last_percent + 1e-6:
            monotonic_ok = False
        last_percent = status["percent"]
        if not (0.0 <= status["percent"] <= 100.0):
            monotonic_ok = False
    check(f"Percentual monotônico e dentro de [0,100] "
          f"(faixa {BATTERY_MIN_V:.0f}–{BATTERY_MAX_V:.0f}V)", monotonic_ok)


# ─────────────────────────────────────────────
# 2. BUMPER — bloqueio a 45cm
# ─────────────────────────────────────────────
def test_bumper():
    section(f"2. Bumper — bloqueio frontal (limite {OBSTACLE_STOP_DISTANCE_M*100:.0f}cm)")
    bmp = SafetyBumper()

    blocked = bmp.set_mock_obstacle(0.45, angle_deg=0.0)
    check("Objeto a 45cm à frente (0°) → blocked_front = True", blocked is True)

    free = bmp.set_mock_obstacle(0.60, angle_deg=0.0)
    check("Objeto a 60cm à frente (0°) → blocked_front = False", free is False)

    side = bmp.set_mock_obstacle(0.45, angle_deg=90.0)
    check("Objeto a 45cm na lateral (90°, fora do arco ±30°) → False", side is False)

    edge = bmp.set_mock_obstacle(0.45, angle_deg=330.0)
    check("Objeto a 45cm em 330° (dentro do arco) → True", edge is True)


# ─────────────────────────────────────────────
# 3. HEADING — Yaw estável + normalização do erro
# ─────────────────────────────────────────────
def test_heading():
    section("3. Heading — Yaw estável (sem drift) e normalização ±180°")
    hl = HeadingLock()

    # Trava em 90° e alimenta amostras com ruído limitado (±0.3°), drift zero.
    hl.set_mock_yaw(90.0)
    hl.read_once()
    hl.lock_heading()
    hl.mock_noise_deg = 0.3

    max_err = 0.0
    errs = []
    for _ in range(300):                 # ~300 amostras
        hl.read_once()
        e = hl.get_yaw_error()
        errs.append(e)
        max_err = max(max_err, abs(e))
    mean_err = sum(errs) / len(errs)
    check(f"Erro máximo ≤ 1.0° sob ruído ±0.3° (máx {max_err:.3f}°)", max_err <= 1.0)
    check(f"Sem drift sistemático: |média do erro| ≤ 0.2° (média {mean_err:.3f}°)",
          abs(mean_err) <= 0.2)

    # Wrap-around: travar em 179° e ler -179° → erro pequeno (~2°), não ~358°.
    hl.mock_noise_deg = 0.0
    hl.set_mock_yaw(179.0)
    hl.read_once()
    hl.lock_heading()
    hl.set_mock_yaw(-179.0)
    hl.read_once()
    wrap_err = hl.get_yaw_error()
    check(f"Wrap ±180°: travado 179°, lido -179° → erro {wrap_err:.1f}° (|erro| ≤ 5)",
          abs(wrap_err) <= 5.0)

    # Parser UART-RVC (quadro sintético) — o BNO085 migrou de I2C para
    # UART-RVC por causa do bug de clock stretching da Pi.
    import struct
    body = bytes([0xAA, 0xAA, 0x00]) + struct.pack(
        "<6h", 12345, -500, 30, 0, 0, 981) + b"\x00\x00\x00"
    good = body + bytes([sum(body[2:]) & 0xFF])
    yaw = HeadingLock.parse_rvc_frame(good)
    check(f"RVC: quadro válido → yaw {yaw}° (esperado 123.45°)", yaw == 123.45)
    bad_sum = good[:-1] + bytes([(good[-1] + 1) & 0xFF])
    check("RVC: checksum corrompido → rejeitado (None)",
          HeadingLock.parse_rvc_frame(bad_sum) is None)
    bad_hdr = b"\xAB" + good[1:]
    check("RVC: header inválido → rejeitado (None)",
          HeadingLock.parse_rvc_frame(bad_hdr) is None)
    check("RVC: tamanho errado → rejeitado (None)",
          HeadingLock.parse_rvc_frame(good[:-2]) is None)


# ─────────────────────────────────────────────
# 5. BUMPER FAIL-CLOSED (Fase 1.5)
# ─────────────────────────────────────────────
def test_bumper_fail_closed():
    import time
    section(f"5. Bumper FAIL-CLOSED (Fase 1.5) — dado velho (> "
            f"{LIDAR_FRESH_TIMEOUT_S*1000:.0f}ms) → bloqueado")
    bmp = SafetyBumper(fail_closed=True)

    check("Sem nenhuma varredura desde o boot → blocked_front = True",
          bmp.blocked_front is True)
    check("healthy = False sem varredura", bmp.healthy is False)

    free = bmp.set_mock_obstacle(2.0, angle_deg=0.0)
    check("Varredura fresca com caminho livre (2m) → blocked_front = False",
          free is False and bmp.blocked_front is False)
    check("healthy = True com dado fresco", bmp.healthy is True)

    # Simula LIDAR mudo: simplesmente deixa o dado envelhecer além do timeout
    time.sleep(LIDAR_FRESH_TIMEOUT_S + 0.1)
    check(f"LIDAR mudo por {LIDAR_FRESH_TIMEOUT_S + 0.1:.1f}s → blocked_front = True "
          "(fail-closed)", bmp.blocked_front is True)
    check("healthy = False com dado velho", bmp.healthy is False)

    blocked_again = bmp.set_mock_obstacle(2.0, angle_deg=0.0)
    check("LIDAR volta a alimentar (caminho livre) → libera sozinho (False)",
          blocked_again is False and bmp.blocked_front is False)

    hb = bmp.health()
    # Contrato EXATO de health(). Comparação por igualdade, não por "contém":
    # se um campo for acrescentado ou removido, este teste precisa falhar e
    # obrigar a decisão a ser consciente. Os dois últimos entraram na Fase 2
    # para o rosto animado olhar na direção do obstáculo.
    check("health() expõe o contrato completo para a telemetria e para o rosto",
          set(hb) == {"healthy", "fail_closed", "last_scan_age_s",
                      "nearest_deg", "nearest_m"},
          ", ".join(sorted(hb)))

    dev = SafetyBumper()   # MOCK puro: fail-closed automático fica inativo
    check("MOCK puro (fail_closed auto-inativo) → False sem varredura "
          "(dev não trava)", dev.blocked_front is False)


# ─────────────────────────────────────────────
# 6. WATCHDOG (Fase 1.5)
# ─────────────────────────────────────────────
def test_watchdog():
    import time
    section("6. Watchdog (Fase 1.5) — alimentação e detecção de travamento")
    wd = HardwareWatchdog(timeout_s=0.3, pet_interval_s=0.05)

    check("Desarmado: não 'dispararia'", wd.would_have_fired is False)
    wd.arm()
    check("Armado em modo MOCK no PC (sem /dev/watchdog)",
          wd.mode == "mock" and wd.armed is True)
    wd.pet(force=True)
    check("Alimentado → não dispararia", wd.would_have_fired is False)

    # Simula loop travado: ninguém alimenta por mais que o timeout
    time.sleep(0.4)
    check("Loop 'travado' por 0.4s (> 0.3s) → dispararia "
          "(na Pi: systemd reinicia o serviço / HW reinicia a placa)",
          wd.would_have_fired is True)

    wd.pet(force=True)
    check("Loop voltou a alimentar → não dispararia", wd.would_have_fired is False)

    wd.disarm()
    check("Desarmado no shutdown gracioso → não dispararia (sem reboot)",
          wd.armed is False and wd.would_have_fired is False)

    hb = wd.health()
    check("health() expõe mode/armed/last_pet_age_s para a telemetria",
          set(hb) == {"mode", "armed", "last_pet_age_s"})


# ─────────────────────────────────────────────
# 4. LOOP 50Hz — jitter < 5ms
# ─────────────────────────────────────────────
class _NullMotors:
    def stop(self):
        pass


def test_loop():
    section("4. Loop 50Hz — jitter abaixo de 5ms (5s de execução)")
    state = {
        "running": True, "mode": "JOYSTICK",
        "blocked": False, "yaw_error": 0.0,
        "battery": {"voltage_v": 0.0, "percent": 0.0},
        "loop": {},
    }
    bat = BatteryMonitor()
    bmp = SafetyBumper()
    hl  = HeadingLock()
    wd  = HardwareWatchdog()
    wd.arm()

    lp = run_control_loop(
        state,
        motors=_NullMotors(), bumper=bmp, heading=hl, battery=bat,
        joystick=None, watchdog=wd, duration_s=5.0,
    )
    check("Watchdog alimentado pelo loop 50Hz (sem disparo em 5s)",
          wd.would_have_fired is False and
          state.get("watchdog", {}).get("armed") is True)
    wd.disarm()
    print(f"     medido: {lp['hz']:.1f}Hz | jitter avg {lp['jitter_ms_avg']:.3f}ms "
          f"| max {lp['jitter_ms_max']:.3f}ms | atrasados {lp['late_pct']:.2f}% "
          f"({lp['late_count']}/{lp['cycles']})")

    # Critérios válidos em qualquer SO: a média deve ficar muito abaixo de 5ms e a
    # frequência próxima de 50Hz.
    check(f"Jitter médio {lp['jitter_ms_avg']:.3f}ms < 5.0ms", lp["jitter_ms_avg"] < 5.0)
    check(f"Frequência ≈ 50Hz (medido {lp['hz']:.1f}Hz, tolerância ±2Hz)",
          abs(lp["hz"] - 50.0) <= 2.0)

    # Jitter por-ciclo (Gate: "sem jitter acima de 5ms"): só é uma garantia REAL na
    # plataforma-alvo (Pi/Linux headless dedicada). Num PC multitarefa o escalonador
    # preempta a thread e gera picos que NÃO vêm do nosso código — lá o resultado é
    # apenas informativo.
    _on_target = sys.platform.startswith("linux")
    if _on_target:
        check(f"≥99% dos ciclos dentro de 5ms (atrasados {lp['late_pct']:.2f}%)",
              lp["late_pct"] < 1.0)
        check(f"Jitter máximo {lp['jitter_ms_max']:.3f}ms < 5.0ms",
              lp["jitter_ms_max"] < 5.0)
    else:
        print(f"     [INFO] jitter por-ciclo (max {lp['jitter_ms_max']:.1f}ms, "
              f"atrasados {lp['late_pct']:.2f}%) é informativo neste SO "
              f"(multitarefa) — o veredito do Gate deve ser obtido NA PI.")


# ─────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────
def main():
    print(f"{BOLD}═══ Validação do Gate da Fase 1 — Frota Mista v2 (MOCK) ═══{RESET}")
    test_regra_zero()
    test_battery()
    test_bumper()
    test_heading()
    test_loop()
    test_bumper_fail_closed()
    test_watchdog()

    total  = len(_results)
    passed = sum(1 for _, ok, _ in _results if ok)
    print(f"\n{BOLD}Resultado: {passed}/{total} verificações OK{RESET}")
    if passed == total:
        print(f"{GREEN}{BOLD}GATE DA FASE 1: VERDE ✅{RESET}")
        print("Lembrete: confirme as provas FÍSICAS na Pi (checklist do README).")
        return 0
    print(f"{RED}{BOLD}GATE DA FASE 1: VERMELHO ❌ — há verificações falhando.{RESET}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
