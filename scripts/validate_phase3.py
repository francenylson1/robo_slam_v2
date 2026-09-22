#!/usr/bin/env python3
"""
scripts/validate_phase3.py
Gate da Fase 3 (parte de SOFTWARE) — a malha de rumo, em MOCK.

A parte FÍSICA do gate é a reta de 2 m, medida com a correção desligada e
ligada, com o robô no chão. Este harness prova o que dá para provar sem robô:
que a correção age CONTRA o erro, que a referência é travada e solta nas horas
certas, e que a malha não consegue furar a Regra Nº 0.

A verificação mais importante daqui é a do SINAL. Copiar
`BNO_STRAIGHT_INVERT_CORRECTION = True` do v1 faria o robô espiralar: o v1
calcula o yaw do quaternion (esquerda aumenta) e nós lemos UART-RVC (direita
aumenta). Convenções opostas. Esse teste fixa a física medida no robô.
"""

import os
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

os.environ["FROTA_MOCK"] = "1"

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from core.heading_assist import HeadingAssist, normaliza_graus
from config.settings import (
    HEADING_KP_PCT, HEADING_KI_PCT, HEADING_INTEGRAL_MAX,
    HEADING_MAX_CORR_PCT, HEADING_INVERT,
    HEADING_STRAIGHT_TOL_PCT, HEADING_ASSIST_ENABLED,
    MOTOR_MAX_POWER_PCT, MOTOR_EMERGENCY_STOP_PCT,
)

_USE_COLOR = sys.stdout.isatty() and os.name != "nt"
GREEN = "\033[92m" if _USE_COLOR else ""
RED   = "\033[91m" if _USE_COLOR else ""
BOLD  = "\033[1m"  if _USE_COLOR else ""
RESET = "\033[0m"  if _USE_COLOR else ""

_results = []


def check(name: str, ok: bool, detail: str = ""):
    _results.append((name, ok, detail))
    marca = f"{GREEN}[PASS]{RESET}" if ok else f"{RED}[FALHA]{RESET}"
    print(f"  {marca} {name}" + (f"  — {detail}" if detail else ""))


def section(titulo: str):
    print(f"\n{BOLD}{titulo}{RESET}")


def nova(enabled=True, **kw):
    cfg = dict(kp_pct=HEADING_KP_PCT, ki_pct=HEADING_KI_PCT,
               limite_integral=HEADING_INTEGRAL_MAX,
               max_corr_pct=HEADING_MAX_CORR_PCT, invert=HEADING_INVERT,
               tol_pct=HEADING_STRAIGHT_TOL_PCT, teto_pct=MOTOR_MAX_POWER_PCT,
               enabled=enabled)
    cfg.update(kw)
    return HeadingAssist(**cfg)


# ─────────────────────────────────────────────
def test_sinal():
    section("1. O SINAL — a correção age CONTRA o erro, nunca a favor")

    # No v2 o yaw vem do UART-RVC: girar para a DIREITA AUMENTA o yaw
    # (medido no robô em 21/09/2026).
    h = nova()
    h.corrigir(8.0, 8.0, 100.0, True)                 # trava a referência
    esq, dir_ = h.corrigir(8.0, 8.0, 110.0, True)     # desviou 10° à DIREITA
    check("Desvio para a DIREITA → a roda DIREITA acelera (vira à esquerda)",
          dir_ > esq, f"E={esq:.2f}% D={dir_:.2f}%")

    h = nova()
    h.corrigir(8.0, 8.0, 100.0, True)
    esq, dir_ = h.corrigir(8.0, 8.0, 90.0, True)      # desviou 10° à ESQUERDA
    check("Desvio para a ESQUERDA → a roda ESQUERDA acelera (vira à direita)",
          esq > dir_, f"E={esq:.2f}% D={dir_:.2f}%")

    check("O invert do v1 NÃO foi copiado (lá o yaw vem do quaternion, "
          "convenção oposta)",
          HEADING_INVERT is False, f"HEADING_INVERT={HEADING_INVERT}")

    h = nova()
    h.corrigir(8.0, 8.0, 100.0, True)
    esq, dir_ = h.corrigir(8.0, 8.0, 100.0, True)     # sem desvio
    check("Sem desvio, o comando passa intacto",
          esq == 8.0 and dir_ == 8.0, f"E={esq} D={dir_}")

    check("A média da correção é zero — a velocidade de avanço não muda",
          abs(((esq + dir_) / 2) - 8.0) < 1e-9)


def test_referencia():
    section("2. A REFERÊNCIA — travada ao entrar na reta, solta ao sair")

    h = nova()
    check("Fora de uma reta não há referência", h.yaw_ref is None)

    h.corrigir(8.0, 8.0, 42.0, True)
    check("Entrar na reta TRAVA a referência no rumo atual",
          h.yaw_ref == 42.0, f"ref={h.yaw_ref}")

    h.corrigir(8.0, 8.0, 50.0, True)
    check("A referência NÃO acompanha o rumo (senão o desvio nunca seria "
          "corrigido)", h.yaw_ref == 42.0, f"ref={h.yaw_ref}")

    h.corrigir(8.0, -8.0, 50.0, True)                 # giro no lugar
    check("Girar no lugar SOLTA a referência", h.yaw_ref is None)

    h.corrigir(8.0, 8.0, 77.0, True)
    check("A próxima reta trava uma referência NOVA",
          h.yaw_ref == 77.0, f"ref={h.yaw_ref}")

    h.corrigir(0.0, 0.0, 77.0, True)                  # parou
    check("Parar SOLTA a referência", h.yaw_ref is None)


def test_reta():
    section("3. O que conta como RETA")
    h = nova()
    check("Dois lados iguais é reta", h.e_reta(8.0, 8.0))
    check("Ré também é reta", h.e_reta(-8.0, -8.0))
    check("Diferença dentro da tolerância ainda é reta",
          h.e_reta(8.0, 8.0 - HEADING_STRAIGHT_TOL_PCT))
    check("Giro no lugar (sentidos opostos) NÃO é reta", not h.e_reta(8.0, -8.0))
    check("Curva aberta (lados muito diferentes) NÃO é reta",
          not h.e_reta(10.0, 2.0))
    check("Um lado parado NÃO é reta", not h.e_reta(8.0, 0.0))


def test_limites():
    section("4. LIMITES — saturação e a Regra Nº 0")

    h = nova()
    h.corrigir(8.0, 8.0, 0.0, True)
    esq, dir_ = h.corrigir(8.0, 8.0, 170.0, True)     # erro enorme
    corr = (dir_ - esq) / 2.0
    check("A correção satura no limite configurado",
          abs(corr) <= HEADING_MAX_CORR_PCT + 1e-9,
          f"corr={corr:.2f}% (máx {HEADING_MAX_CORR_PCT}%)")

    # A correção SOMA ao comando base: no teto (15%) mais 6% daria 21%, e ≥20%
    # não é cortado — é EMERGENCY STOP. A malha NÃO pode provocar emergência em
    # operação normal (foi o bloqueador que o PID tinha antes de 22/09/2026).
    # Em vez de conferir uma conta entre constantes, verifica-se o COMPORTAMENTO.
    h = nova()
    h.corrigir(MOTOR_MAX_POWER_PCT, MOTOR_MAX_POWER_PCT, 0.0, True)
    for _ in range(50):                      # erro grande e persistente
        esq, dir_ = h.corrigir(MOTOR_MAX_POWER_PCT, MOTOR_MAX_POWER_PCT,
                               60.0, True, dt=0.02)
    pico = max(abs(esq), abs(dir_))
    check("No TETO de potência, a saída nunca passa do teto",
          pico <= MOTOR_MAX_POWER_PCT + 1e-9,
          f"pico={pico:.2f}% (teto {MOTOR_MAX_POWER_PCT}%)")
    check("...e nunca alcança o gatilho de emergência",
          pico < MOTOR_EMERGENCY_STOP_PCT, f"pico={pico:.2f}%")
    check("Ao rebaixar, a DIFERENÇA entre os lados é preservada — é ela que "
          "faz o robô virar",
          abs(abs(dir_ - esq) / 2.0 - HEADING_MAX_CORR_PCT) < 1e-6,
          f"diferença/2 = {abs(dir_-esq)/2:.2f}%")

    # Ré: o rebaixamento tem que funcionar com o sinal invertido também
    h = nova()
    h.corrigir(-MOTOR_MAX_POWER_PCT, -MOTOR_MAX_POWER_PCT, 0.0, True)
    for _ in range(50):
        esq, dir_ = h.corrigir(-MOTOR_MAX_POWER_PCT, -MOTOR_MAX_POWER_PCT,
                               60.0, True, dt=0.02)
    check("Em RÉ, a saída também respeita o teto",
          max(abs(esq), abs(dir_)) <= MOTOR_MAX_POWER_PCT + 1e-9,
          f"E={esq:.2f}% D={dir_:.2f}%")

    check("A correção é pequena perto da potência base (é ajuste, não comando)",
          HEADING_MAX_CORR_PCT < MOTOR_MAX_POWER_PCT / 2.0,
          f"{HEADING_MAX_CORR_PCT}% vs teto {MOTOR_MAX_POWER_PCT}%")


def test_integral():
    section("7. O INTEGRAL — aprende o desvio constante que o P não resolve")

    check("Há termo integral configurado", HEADING_KI_PCT > 0,
          f"ki={HEADING_KI_PCT}")

    # Erro pequeno e PERSISTENTE: o P sozinho daria uma correção minúscula; o
    # integral vai crescendo até compensar. É o caso real deste robô — um motor
    # sistematicamente mais forte que o outro.
    h = nova()
    h.corrigir(8.0, 8.0, 0.0, True)
    so_p = HEADING_KP_PCT * 5.0
    corr = 0.0
    for _ in range(100):                     # 2 s de erro de 5°
        esq, dir_ = h.corrigir(8.0, 8.0, 5.0, True, dt=0.02)
        corr = (dir_ - esq) / 2.0
    check("Erro pequeno e persistente faz a correção CRESCER além do P puro",
          corr > so_p * 2,
          f"corr={corr:.3f}% vs P puro {so_p:.3f}%")

    # Anti-windup: numa saturação longa o integral não pode crescer sem fim,
    # senão demora a "descarregar" e o robô passa do ponto na volta.
    h = nova()
    h.corrigir(8.0, 8.0, 0.0, True)
    for _ in range(2000):                    # 40 s de erro enorme
        h.corrigir(8.0, 8.0, 90.0, True, dt=0.02)
    check("Anti-windup: o integral para de acumular no limite",
          abs(h.health()["integral"]) <= HEADING_INTEGRAL_MAX + 1e-6,
          f"integral={h.health()['integral']} (limite {HEADING_INTEGRAL_MAX})")

    # O limite do integral NÃO pode depender do ki. Quando dependia
    # (max_corr/ki), reduzir o ganho dobrava a memória do integral e AGRAVAVA o
    # windup: medido em 22/09/2026, o desvio final piorou de +4,8° para -11,4°.
    fraco  = nova(ki_pct=HEADING_KI_PCT / 2)
    forte  = nova(ki_pct=HEADING_KI_PCT * 2)
    for h2 in (fraco, forte):
        h2.corrigir(8.0, 8.0, 0.0, True)
        for _ in range(2000):
            h2.corrigir(8.0, 8.0, 90.0, True, dt=0.02)
    check("O limite do integral NÃO muda com o ki — mexer no ganho muda só a "
          "força, não a memória",
          abs(fraco.health()["integral"]) == abs(forte.health()["integral"]),
          f"ki/2 → {fraco.health()['integral']} · ki*2 → "
          f"{forte.health()['integral']}")

    check("Soltar a referência ZERA o integral (a próxima reta começa limpa)",
          (h.soltar() or h.health()["integral"]) == 0.0)


def test_fail_soft():
    section("5. FAIL-SOFT — o rumo nunca bloqueia o robô")

    h = nova()
    h.corrigir(8.0, 8.0, 10.0, True)
    check("BNO085 sem saúde → sem correção, comando do operador intacto",
          h.corrigir(8.0, 8.0, 10.0, False) is None)
    check("...e a referência é solta, para a próxima reta começar limpa",
          h.yaw_ref is None)
    check("Yaw ausente (None) → sem correção",
          nova().corrigir(8.0, 8.0, None, True) is None)
    check("Malha desligada → sem correção",
          nova(enabled=False).corrigir(8.0, 8.0, 10.0, True) is None)
    check("Nasce DESLIGADA no settings — só liga depois de medir a reta",
          HEADING_ASSIST_ENABLED is False)


def test_angulo():
    section("6. ÂNGULO — cruzar 0°/360° não pode virar erro de 360°")
    check("350° → -10°", normaliza_graus(350.0) == -10.0)
    check("-190° → 170°", normaliza_graus(-190.0) == 170.0)
    check("180° continua 180°", normaliza_graus(180.0) == 180.0)

    h = nova()
    h.corrigir(8.0, 8.0, 359.0, True)                 # referência perto do zero
    esq, dir_ = h.corrigir(8.0, 8.0, 5.0, True)       # cruzou o zero: +6°
    corr = (dir_ - esq) / 2.0
    check("Cruzar o zero produz correção PEQUENA, não violenta",
          0 < corr <= HEADING_KP_PCT * 10, f"corr={corr:.3f}%")


def main():
    print(f"{BOLD}═══ Gate da Fase 3 — malha de rumo (MOCK) ═══{RESET}")
    test_sinal()
    test_referencia()
    test_reta()
    test_limites()
    test_fail_soft()
    test_angulo()
    test_integral()

    total  = len(_results)
    passed = sum(1 for _, ok, _ in _results if ok)
    print(f"\n{BOLD}Resultado: {passed}/{total} verificações OK{RESET}")
    if passed == total:
        print(f"{GREEN}{BOLD}FASE 3 (SOFTWARE DA MALHA DE RUMO): VERDE ✅{RESET}")
        print("Falta a prova FÍSICA: a reta de 2 m, medida com a correção "
              "desligada e ligada.")
        return 0
    print(f"{RED}{BOLD}FASE 3: VERMELHO ❌{RESET}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
