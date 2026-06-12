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
    check("health() expõe healthy/fail_closed/last_scan_age_s para a telemetria",
          set(hb) == {"healthy", "fail_closed", "last_scan_age_s"})

    dev = SafetyBumper()   # MOCK puro: fail-closed automático fica inativo
    check("MOCK puro (fail_closed auto-inativo) → False sem varredura "
          "(dev não trava)", dev.blocked_front is False)


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

    lp = run_control_loop(
        state,
        motors=_NullMotors(), bumper=bmp, heading=hl, battery=bat,
        joystick=None, duration_s=5.0,
    )
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
    test_battery()
    test_bumper()
    test_heading()
    test_loop()
    test_bumper_fail_closed()

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
