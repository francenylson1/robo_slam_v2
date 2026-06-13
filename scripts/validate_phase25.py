#!/usr/bin/env python3
"""
scripts/validate_phase25.py
Harness de validação da Fase 2.5 (Torre de Controle / MQTT) — em MOCK.

Prova, sem broker real (backend mock = barramento em memória):
  1. Roteamento de tópicos com wildcards MQTT (+ e #) e retained
  2. Telemetria robô → Torre (payload completo, snapshot da frota)
  3. E-STOP GERAL: Torre publica → robô para; liberar → robô volta
  4. Retained: robô que conecta DEPOIS do E-Stop também para
  5. Loop de controle re-asserta a parada enquanto fleet_estop ativo

Uso: python3 scripts/validate_phase25.py
Saída: relatório PASS/FALHA. Exit 0 = tudo OK.

NOTA: prova a LÓGICA em MOCK. A prova física (mosquitto na Torre, robôs na
rede real) é o checklist da Fase 2.5 no README.
"""

import os
import sys
import json
import time

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

os.environ["FROTA_MOCK"] = "1"

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from fleet.link import FleetLink, _MockBus
from tower.main import create_tower_app
from core.control_loop import run_control_loop
from sensors.battery_monitor import BatteryMonitor
from sensors.safety_bumper   import SafetyBumper
from sensors.heading_lock    import HeadingLock
from config.settings import MQTT_BASE_TOPIC

_results = []


def check(name: str, ok: bool):
    _results.append((name, ok))
    print(f"  [{'PASS' if ok else 'FALHA'}] {name}")


def section(title: str):
    print(f"\n{title}")


# ─────────────────────────────────────────────
# 1. ROTEAMENTO (wildcards + retained)
# ─────────────────────────────────────────────
def test_routing():
    section("1. Roteamento de tópicos — wildcards e retained")
    m = _MockBus._match
    check("frota/robos/+/telemetria casa frota/robos/3/telemetria",
          m("frota/robos/+/telemetria", "frota/robos/3/telemetria"))
    check("frota/robos/+/telemetria NÃO casa frota/robos/3/status",
          not m("frota/robos/+/telemetria", "frota/robos/3/status"))
    check("frota/# casa qualquer subtópico",
          m("frota/#", "frota/comandos/estop"))
    check("Filtro mais longo que o tópico não casa",
          not m("frota/robos/+/telemetria", "frota/robos/3"))

    bus = _MockBus()
    got = []
    bus.publish("a/b", "retido", retain=True)
    bus.subscribe("a/+", lambda t, p: got.append((t, p)))
    check("Retained entregue a assinante posterior", got == [("a/b", "retido")])


# ─────────────────────────────────────────────
# 2–4. ROBÔ ↔ TORRE (fluxo completo em MOCK)
# ─────────────────────────────────────────────
def test_robot_tower():
    section("2. Telemetria robô → Torre")
    # Torre (injetando FleetLink mock explícito)
    tower_link = FleetLink("torre", backend="mock")
    app, _ = create_tower_app(link=tower_link)
    tower_link.start()

    # Robô 7 simulado
    state7 = {"fleet_estop": False}
    robot7 = FleetLink("robo-7",
                       status_topic=f"{MQTT_BASE_TOPIC}/robos/7/status",
                       backend="mock")

    def estop7(topic, payload):
        state7["fleet_estop"] = payload.strip().lower() in ("on", "1", "true")

    robot7.subscribe(f"{MQTT_BASE_TOPIC}/comandos/estop", estop7)
    robot7.start()
    robot7.publish(f"{MQTT_BASE_TOPIC}/robos/7/telemetria", {
        "robot_id": 7, "mode": "JOYSTICK",
        "battery": {"voltage_v": 39.5, "percent": 79.2},
        "blocked": False, "fleet_estop": False, "loop_hz": 50.0,
    })

    client = app.test_client()
    snap = client.get("/api/frota").get_json()
    r7 = snap["robots"].get("7")
    check("Robô 7 aparece no snapshot da Torre", r7 is not None)
    check("Telemetria íntegra (39.5V / 79.2%)",
          r7 and r7["telemetry"]["battery"]["voltage_v"] == 39.5)
    check("Robô 7 marcado ONLINE (telemetria fresca)", r7 and r7["online"])

    section("3. E-STOP GERAL — Torre aciona, robô para; liberar volta")
    resp = client.post("/api/estop", json={"on": True}).get_json()
    check("POST /api/estop {'on': true} → ok", resp.get("estop") is True)
    check("Robô 7 recebeu o E-Stop (fleet_estop = True)",
          state7["fleet_estop"] is True)

    snap = client.get("/api/frota").get_json()
    check("Snapshot da Torre reflete estop = True", snap["estop"] is True)

    section("4. Retained — robô que chega DEPOIS do E-Stop também para")
    state9 = {"fleet_estop": False}
    robot9 = FleetLink("robo-9", backend="mock")
    robot9.subscribe(f"{MQTT_BASE_TOPIC}/comandos/estop",
                     lambda t, p: state9.update(
                         fleet_estop=p.strip().lower() in ("on", "1", "true")))
    robot9.start()
    check("Robô 9 (conectou após o acionamento) já nasce parado",
          state9["fleet_estop"] is True)

    resp = client.post("/api/estop", json={"on": False}).get_json()
    check("Liberar frota → estop = False", resp.get("estop") is False)
    check("Robô 7 liberado", state7["fleet_estop"] is False)
    check("Robô 9 liberado", state9["fleet_estop"] is False)


# ─────────────────────────────────────────────
# 5. LOOP DE CONTROLE re-asserta a parada
# ─────────────────────────────────────────────
class _SpyMotors:
    def __init__(self):
        self.stop_calls = 0

    def stop(self):
        self.stop_calls += 1


def test_loop_enforces_estop():
    section("5. Loop 50Hz re-asserta motors.stop() sob fleet_estop")
    motors = _SpyMotors()
    state = {"running": True, "mode": "JOYSTICK", "fleet_estop": True, "loop": {}}
    run_control_loop(state, motors=motors, bumper=SafetyBumper(),
                     heading=HeadingLock(), battery=BatteryMonitor(),
                     joystick=None, duration_s=0.3)
    check(f"stop() chamado a cada ciclo ({motors.stop_calls}x em ~0.3s ≥ 10)",
          motors.stop_calls >= 10)

    motors2 = _SpyMotors()
    state2 = {"running": True, "mode": "JOYSTICK", "fleet_estop": False, "loop": {}}
    run_control_loop(state2, motors=motors2, bumper=SafetyBumper(),
                     heading=HeadingLock(), battery=BatteryMonitor(),
                     joystick=None, duration_s=0.3)
    check("Sem fleet_estop → nenhum stop() forçado", motors2.stop_calls == 0)


# ─────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────
def main():
    print("═══ Validação da Fase 2.5 — Torre de Controle (MOCK) ═══")
    test_routing()
    test_robot_tower()
    test_loop_enforces_estop()

    total  = len(_results)
    passed = sum(1 for _, ok in _results if ok)
    print(f"\nResultado: {passed}/{total} verificações OK")
    if passed == total:
        print("FASE 2.5 (SOFTWARE): VERDE ✅")
        print("Prova física: mosquitto na Torre + robôs reais (checklist do README).")
        return 0
    print("FASE 2.5: VERMELHO ❌ — há verificações falhando.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
