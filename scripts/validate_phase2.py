#!/usr/bin/env python3
"""
scripts/validate_phase2.py
Harness de validação do Gate da Fase 2 (Interface PRO) — Frota Mista v2.

Prova, em modo MOCK e sem subir servidor (usa o test_client do Flask):

  1. AUTENTICAÇÃO
     - rotas de comando e de dados exigem sessão;
     - a PARADA DE EMERGÊNCIA funciona SEM login (decisão de segurança);
     - login correto libera; senha errada não;
     - APIs respondem 401 em JSON, navegação redireciona para /login;
     - bloqueio temporário após tentativas repetidas;
     - logout encerra a sessão.

Uso:
    python3 scripts/validate_phase2.py

Exit code 0 (tudo PASS) / 1 (qualquer FALHA).
"""

import os
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

os.environ["FROTA_MOCK"] = "1"

# Credenciais determinísticas para o teste — definidas ANTES de importar
# config.settings, que lê o ambiente no import.
_SENHA = "senha-de-teste-123"
os.environ["FROTA_WEB_AUTH"] = "1"
os.environ["FROTA_WEB_USER"] = "operador"

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from werkzeug.security import generate_password_hash

os.environ["FROTA_WEB_PASSWORD_HASH"] = generate_password_hash(_SENHA)

from core.motor_driver import MotorDriver
from web.server        import create_app
import web.auth        as auth

_USE_COLOR = sys.stdout.isatty() and os.name != "nt"
GREEN = "\033[92m" if _USE_COLOR else ""
RED   = "\033[91m" if _USE_COLOR else ""
BOLD  = "\033[1m"  if _USE_COLOR else ""
RESET = "\033[0m"  if _USE_COLOR else ""

_results = []


def check(name: str, ok: bool, detail: str = ""):
    _results.append((name, ok, detail))
    tag = f"{GREEN}PASS{RESET}" if ok else f"{RED}FALHA{RESET}"
    print(f"  [{tag}] {name}" + (f"  — {detail}" if detail else ""))


def section(title: str):
    print(f"\n{BOLD}{title}{RESET}")


def novo_app():
    state = {"robot_id": 1, "mode": "JOYSTICK", "blocked": False,
             "battery": {"voltage_v": 38.0, "percent": 80.0},
             "lidar": {}, "watchdog": {}, "fleet_estop": False}
    app = create_app(motors=MotorDriver(), state=state)
    app.config["TESTING"] = True
    return app


# ─────────────────────────────────────────────
# 1. ROTAS PROTEGIDAS
# ─────────────────────────────────────────────
def test_protegidas():
    section("1. Rotas protegidas — sem sessão, ninguém comanda o robô")
    app = novo_app()
    c = app.test_client()

    r = c.get("/", follow_redirects=False)
    check("GET / sem login → redireciona para o login",
          r.status_code in (301, 302) and "/login" in r.headers.get("Location", ""),
          f"HTTP {r.status_code} → {r.headers.get('Location')}")

    r = c.get("/api/status")
    check("GET /api/status sem login → 401 em JSON",
          r.status_code == 401 and r.is_json and r.get_json().get("ok") is False,
          f"HTTP {r.status_code}")

    r = c.post("/api/mode", json={"mode": "AUTONOMO"})
    check("POST /api/mode sem login → 401 (não troca o modo)",
          r.status_code == 401, f"HTTP {r.status_code}")

    r = c.get("/events")
    check("GET /events sem login → 401 (telemetria protegida)",
          r.status_code == 401, f"HTTP {r.status_code}")

    r = c.get("/video")
    check("GET /video sem login → redireciona (câmera protegida)",
          r.status_code in (301, 302), f"HTTP {r.status_code}")


# ─────────────────────────────────────────────
# 2. PARADA DE EMERGÊNCIA SEM LOGIN
# ─────────────────────────────────────────────
def test_estop_publico():
    section("2. Parada de emergência — funciona SEM login (decisão de segurança)")
    app = novo_app()
    c = app.test_client()

    r = c.post("/api/stop")
    check("POST /api/stop sem login → 200 (a parada nunca depende de senha)",
          r.status_code == 200 and r.get_json().get("ok") is True,
          f"HTTP {r.status_code}")

    check("A tela de login é acessível sem sessão",
          c.get("/login").status_code == 200)


# ─────────────────────────────────────────────
# 3. LOGIN E LOGOUT
# ─────────────────────────────────────────────
def test_login():
    section("3. Login, sessão e logout")
    app = novo_app()
    c = app.test_client()

    r = c.post("/login", data={"usuario": "operador", "senha": "errada"})
    check("Senha errada → não autentica (HTTP 401)", r.status_code == 401,
          f"HTTP {r.status_code}")

    r = c.post("/login", data={"usuario": "invasor", "senha": _SENHA})
    check("Usuário errado → não autentica", r.status_code == 401,
          f"HTTP {r.status_code}")

    r = c.post("/login", data={"usuario": "operador", "senha": _SENHA},
               follow_redirects=False)
    check("Credencial correta → redireciona autenticado",
          r.status_code in (301, 302), f"HTTP {r.status_code}")

    r = c.get("/api/status")
    check("Depois do login, /api/status responde 200 com telemetria",
          r.status_code == 200 and r.is_json and "robot_id" in r.get_json(),
          f"HTTP {r.status_code}")

    r = c.post("/api/mode", json={"mode": "AUTONOMO"})
    check("Depois do login, /api/mode troca o modo",
          r.status_code == 200 and r.get_json().get("mode") == "AUTONOMO",
          f"HTTP {r.status_code}")

    c.get("/logout")
    r = c.get("/api/status")
    check("Depois do logout, /api/status volta a 401", r.status_code == 401,
          f"HTTP {r.status_code}")


# ─────────────────────────────────────────────
# 4. DESTINO APÓS O LOGIN
# ─────────────────────────────────────────────
def test_destino():
    section("4. O login devolve a pessoa à página que ela pediu")
    app = novo_app()
    c = app.test_client()

    r = c.get("/", follow_redirects=False)
    check("O redirecionamento carrega o destino original",
          "proximo=%2F" in r.headers.get("Location", "")
          or "proximo=/" in r.headers.get("Location", ""),
          r.headers.get("Location", ""))

    r = c.post("/login", data={"usuario": "operador", "senha": _SENHA,
                               "proximo": "/api/status"}, follow_redirects=False)
    check("Após entrar, volta para o destino pedido",
          r.headers.get("Location", "").endswith("/api/status"),
          r.headers.get("Location", ""))

    r = c.post("/login", data={"usuario": "operador", "senha": _SENHA,
                               "proximo": "https://site-malicioso.exemplo/x"},
               follow_redirects=False)
    check("Destino externo é recusado (sem redirecionamento aberto)",
          r.headers.get("Location", "").endswith("/"),
          r.headers.get("Location", ""))


# ─────────────────────────────────────────────
# 5. FREIO CONTRA FORÇA BRUTA
# ─────────────────────────────────────────────
def test_forca_bruta():
    section("5. Freio contra tentativa repetida de senha")
    app = novo_app()
    c = app.test_client()
    auth._tentativas.clear()

    for _ in range(auth._MAX_TENTATIVAS):
        c.post("/login", data={"usuario": "operador", "senha": "errada"})

    r = c.post("/login", data={"usuario": "operador", "senha": _SENHA})
    check(f"Após {auth._MAX_TENTATIVAS} falhas, até a senha CERTA é barrada",
          r.status_code == 401 and "Aguarde" in r.get_data(as_text=True),
          f"HTTP {r.status_code}")

    r = c.post("/api/stop")
    check("Mesmo bloqueado, a parada de emergência continua respondendo",
          r.status_code == 200, f"HTTP {r.status_code}")

    auth._tentativas.clear()
    r = c.post("/login", data={"usuario": "operador", "senha": _SENHA},
               follow_redirects=False)
    check("Passado o bloqueio, a senha correta volta a funcionar",
          r.status_code in (301, 302), f"HTTP {r.status_code}")


# ─────────────────────────────────────────────
# 6. MODO SEM SENHA CONFIGURADA
# ─────────────────────────────────────────────
def test_sem_senha_configurada():
    section("6. Sem senha configurada, o robô NÃO fica aberto")
    import importlib
    os.environ["FROTA_WEB_PASSWORD_HASH"] = ""
    import config.settings as cfg
    importlib.reload(cfg)
    importlib.reload(auth)
    import web.server as srv
    importlib.reload(srv)

    state = {"robot_id": 1, "mode": "JOYSTICK"}
    app = srv.create_app(motors=MotorDriver(), state=state)
    app.config["TESTING"] = True
    c = app.test_client()

    resumo = app.config.get("FROTA_AUTH", {})
    check("Uma senha é sorteada e anunciada no log",
          resumo.get("senha_sorteada") is True, str(resumo))

    r = c.get("/api/status")
    check("Sem senha configurada, /api/status ainda exige login (401)",
          r.status_code == 401, f"HTTP {r.status_code}")

    r = c.post("/api/stop")
    check("E a parada de emergência segue aberta", r.status_code == 200,
          f"HTTP {r.status_code}")


# ─────────────────────────────────────────────
# 7. TELEMETRIA E DASHBOARD
# ─────────────────────────────────────────────
def test_dashboard():
    section("7. Dashboard responsivo e telemetria")
    import importlib, time
    os.environ["FROTA_WEB_PASSWORD_HASH"] = generate_password_hash(_SENHA)
    import config.settings as cfg
    importlib.reload(cfg)
    importlib.reload(auth)
    import web.server as srv
    importlib.reload(srv)

    state = {"robot_id": 1, "mode": "JOYSTICK", "blocked": False,
             "battery": {"voltage_v": 38.0, "percent": 80.0},
             "lidar": {}, "watchdog": {}, "fleet_estop": False}
    app = srv.create_app(motors=MotorDriver(), state=state)
    app.config["TESTING"] = True
    c = app.test_client()
    c.post("/login", data={"usuario": "operador", "senha": _SENHA})

    d1 = c.get("/api/status").get_json()
    check("Telemetria traz carimbo de tempo do servidor (ts)",
          isinstance(d1.get("ts"), (int, float)), str(d1.get("ts")))
    check("Telemetria informa se há câmera",
          isinstance(d1.get("camera"), bool), str(d1.get("camera")))
    check("Sem webcam conectada, camera = False", d1.get("camera") is False)

    time.sleep(0.05)
    d2 = c.get("/api/status").get_json()
    check("O carimbo avança entre leituras (permite detectar telemetria parada)",
          d2["ts"] > d1["ts"], f"{d2['ts'] - d1['ts']:.3f}s")

    html = c.get("/").get_data(as_text=True)
    check("A página declara viewport (obrigatório para celular e 7\")",
          'name="viewport"' in html)
    check("Tem os três pontos de quebra dos 4 tamanhos",
          "min-width:700px" in html and "min-width:1600px" in html
          and "pointer: coarse" in html)
    check("Alvos crescem sob toque (pointer: coarse), não só por largura",
          "--alvo:60px" in html)
    check("Botão de parada presente e destacado", 'class="parar"' in html)
    check("Tem aviso visível de TELEMETRIA PARADA (nada de valor congelado mudo)",
          "TELEMETRIA PARADA" in html and "IDADE_MAX_MS" in html)
    check("Reage ao E-STOP GERAL da Torre", "frota-parada" in html)
    check("Trata 401 recarregando o login em vez de falhar em silêncio",
          "r.status === 401" in html)


# ─────────────────────────────────────────────
# 8. ROSTO ANIMADO
# ─────────────────────────────────────────────
def test_rosto():
    section("8. Rosto animado — a tela de bordo do robô")
    from sensors.safety_bumper import SafetyBumper

    # 8a. o bumper passou a dizer ONDE está o obstáculo
    b = SafetyBumper(fail_closed=False)
    b.feed_scan([(15, 20.0, 300.0), (15, 100.0, 200.0)])   # 0,3 m a +20° (e um fora do arco)
    h = b.health()
    check("Bumper informa a direção do obstáculo frontal (direita = +)",
          h["nearest_deg"] == 20.0 and h["nearest_m"] == 0.3, str(h))

    b.feed_scan([(15, 340.0, 250.0)])                      # 0,25 m a -20°
    h = b.health()
    check("Obstáculo à esquerda vira ângulo NEGATIVO",
          h["nearest_deg"] == -20.0, str(h))

    b.feed_scan([(15, 100.0, 200.0)])                      # só fora do arco frontal
    h = b.health()
    check("Ponto fora do arco de ±30° não vira 'obstáculo à frente'",
          h["nearest_deg"] is None and h["nearest_m"] is None, str(h))

    b.feed_scan([(15, 10.0, 900.0)])                       # 0,9 m: perto, mas não bloqueia
    h = b.health()
    check("Direção é reportada mesmo sem bloqueio (rosto acompanha antes de parar)",
          h["nearest_deg"] == 10.0 and b.blocked_front is False, str(h))

    # 8b. rotas públicas
    app = novo_app()
    c = app.test_client()

    r = c.get("/rosto")
    check("GET /rosto SEM login → 200 (a tela do robô acende no boot)",
          r.status_code == 200, f"HTTP {r.status_code}")

    r = c.get("/rosto/eventos")
    check("GET /rosto/eventos sem login → 200 (telemetria da expressão)",
          r.status_code == 200, f"HTTP {r.status_code}")

    # 8c. payload reduzido
    import json as _json
    bruto = next(r.response).decode("utf-8")
    dados = _json.loads(bruto.split("data: ", 1)[1].strip())
    r.close()
    for campo in ("ts", "blocked", "nearest_deg", "bateria", "fleet_estop", "lidar_ok"):
        check(f"O rosto recebe '{campo}'", campo in dados)
    for proibido in ("camera", "watchdog", "lidar", "battery"):
        check(f"O rosto NÃO recebe '{proibido}' (payload reduzido)",
              proibido not in dados)

    # 8d. a página
    html = c.get("/rosto").get_data(as_text=True)
    check("Sem telemetria fresca, o rosto vai para 'offline' em vez de fingir alegria",
          "IDADE_MAX" in html and "COR.offline" in html)
    check("Olha para o lado do obstáculo usando nearest_deg",
          "nearest_deg / 30" in html)
    check("Tem expressão para o E-STOP da frota", "PARADA GERAL" in html)
    check("Tem expressão de bateria baixa", "Preciso carregar" in html)
    check("Tela de quiosque: sem rolagem e sem cursor",
          "overflow:hidden" in html and "cursor:none" in html)


def main():
    print(f"{BOLD}═══ Validação do Gate da Fase 2 — Interface PRO (MOCK) ═══{RESET}")
    test_protegidas()
    test_estop_publico()
    test_login()
    test_destino()
    test_forca_bruta()
    test_sem_senha_configurada()
    test_dashboard()
    test_rosto()

    total  = len(_results)
    passed = sum(1 for _, ok, _ in _results if ok)
    print(f"\n{BOLD}Resultado: {passed}/{total} verificações OK{RESET}")
    if passed == total:
        print(f"{GREEN}{BOLD}FASE 2 (auth + dashboard + rosto): VERDE ✅{RESET}")
        print("Pendente da Fase 2: voz Piper.")
        return 0
    print(f"{RED}{BOLD}FASE 2: VERMELHO ❌{RESET}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
