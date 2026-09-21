"""
web/auth.py
Autenticação do dashboard do robô (Fase 2 — Interface PRO).

DUAS DECISÕES DE PROJETO, deliberadas:

1. A PARADA DE EMERGÊNCIA FICA FORA DO LOGIN.
   `/api/stop` só consegue tornar o robô mais seguro — nunca mais perigoso.
   Trancá-la atrás de uma tela de senha cria um cenário em que alguém vê o robô
   indo para cima de uma pessoa e perde segundos digitando credencial. Toda
   rota que COMANDA movimento exige login; a que PARA, não.

2. AUTENTICAÇÃO LIGADA POR PADRÃO, SEM MODO ABERTO SILENCIOSO.
   O dashboard comanda motores numa rede de escola. Se não houver senha
   configurada, o sistema NÃO abre o acesso: ele sorteia uma senha forte, a
   publica no log (`journalctl -u frota-robo | grep SENHA`) e segue protegido.
   Para fixar uma senha permanente: `python3 scripts/set_web_password.py`.

A sessão expira em WEB_SESSION_HORAS. A chave de sessão é derivada do hash da
senha + machine-id, então é estável entre reinícios (o watchdog reinicia o
serviço) e é invalidada de propósito quando a senha muda.
"""

import functools
import hashlib
import logging
import secrets
import string
import time

from flask import (redirect, render_template, request, session, url_for,
                   jsonify)
from werkzeug.security import check_password_hash, generate_password_hash

from config.settings import (WEB_AUTH_ENABLED, WEB_USER, WEB_PASSWORD_HASH,
                             WEB_SESSION_HORAS)

log = logging.getLogger(__name__)

# Bloqueio após tentativas falhas, por IP de origem.
_MAX_TENTATIVAS   = 5
_BLOQUEIO_S       = 30.0
_tentativas: dict[str, list] = {}      # ip -> [falhas, instante_do_bloqueio]


def _sortear_senha(n: int = 10) -> str:
    """Senha aleatória legível (sem caracteres ambíguos) para o modo sem configuração."""
    alfabeto = "".join(c for c in (string.ascii_letters + string.digits)
                       if c not in "O0oIl1")
    return "".join(secrets.choice(alfabeto) for _ in range(n))


def _machine_id() -> str:
    for caminho in ("/etc/machine-id", "/var/lib/dbus/machine-id"):
        try:
            with open(caminho) as f:
                return f.read().strip()
        except Exception:
            continue
    return "frota-sem-machine-id"


def init_auth(app) -> dict:
    """
    Prepara a autenticação no app Flask e devolve um resumo do estado
    (usado pela telemetria e pelo harness de validação).
    """
    hash_senha = WEB_PASSWORD_HASH
    senha_sorteada = None

    if WEB_AUTH_ENABLED and not hash_senha:
        senha_sorteada = _sortear_senha()
        hash_senha = generate_password_hash(senha_sorteada)
        log.warning("=" * 62)
        log.warning("[auth] NENHUMA SENHA CONFIGURADA — uma foi sorteada agora.")
        log.warning(f"[auth] USUARIO: {WEB_USER}")
        log.warning(f"[auth] SENHA..: {senha_sorteada}")
        log.warning("[auth] Ela muda a cada reinício. Para fixar uma senha:")
        log.warning("[auth]   python3 scripts/set_web_password.py")
        log.warning("=" * 62)

    app.config["FROTA_HASH_SENHA"] = hash_senha
    app.secret_key = hashlib.sha256(
        (_machine_id() + hash_senha).encode("utf-8")).digest()
    app.permanent_session_lifetime = WEB_SESSION_HORAS * 3600

    if not WEB_AUTH_ENABLED:
        log.warning("[auth] AUTENTICAÇÃO DESLIGADA (FROTA_WEB_AUTH=0). "
                    "Qualquer pessoa na rede comanda este robô.")

    return {
        "enabled":        WEB_AUTH_ENABLED,
        "user":           WEB_USER,
        "senha_sorteada": senha_sorteada is not None,
    }


def _destino_seguro(destino: str) -> str:
    """
    Só aceita caminhos internos. Recusa URL absoluta e também a forma
    protocolo-relativa ("//outro-site") e "/\\outro-site", que começam com "/"
    mas o navegador trata como host externo — seria um open redirect.
    """
    if (not destino
            or not destino.startswith("/")
            or destino.startswith("//")
            or destino.startswith("/\\")):
        return "/"
    return destino


def _bloqueado(ip: str) -> float:
    """Segundos restantes de bloqueio para este IP (0 = liberado)."""
    reg = _tentativas.get(ip)
    if not reg or reg[0] < _MAX_TENTATIVAS:
        return 0.0
    restante = _BLOQUEIO_S - (time.monotonic() - reg[1])
    if restante <= 0:
        _tentativas.pop(ip, None)
        return 0.0
    return restante


def _registrar_falha(ip: str):
    reg = _tentativas.setdefault(ip, [0, 0.0])
    reg[0] += 1
    if reg[0] >= _MAX_TENTATIVAS:
        reg[1] = time.monotonic()


def login_required(fn):
    """
    Exige sessão autenticada. Requisições de API respondem 401 em JSON;
    navegação normal é redirecionada para a tela de login.
    """
    @functools.wraps(fn)
    def _wrap(*a, **kw):
        if not WEB_AUTH_ENABLED or session.get("auth"):
            return fn(*a, **kw)
        if request.path.startswith("/api/") or request.path == "/events":
            return jsonify({"ok": False, "error": "nao autenticado"}), 401
        return redirect(url_for("login", proximo=request.path))
    return _wrap


def registrar_rotas(app, robot_id_fn):
    """Registra /login e /logout."""

    @app.route("/login", methods=["GET", "POST"])
    def login():
        if not WEB_AUTH_ENABLED:
            return redirect(url_for("index"))

        proximo = request.args.get("proximo") or request.form.get("proximo") or "/"
        ip = request.remote_addr or "?"
        erro = None

        espera = _bloqueado(ip)
        if espera > 0:
            erro = f"Muitas tentativas. Aguarde {espera:.0f}s."
        elif request.method == "POST":
            usuario = (request.form.get("usuario") or "").strip()
            senha   = request.form.get("senha") or ""
            confere = check_password_hash(app.config["FROTA_HASH_SENHA"], senha)
            if usuario == WEB_USER and confere:
                _tentativas.pop(ip, None)
                session.permanent = True
                session["auth"] = True
                session["usuario"] = usuario
                log.info(f"[auth] Login de {usuario} em {ip}.")
                return redirect(_destino_seguro(proximo))
            _registrar_falha(ip)
            erro = "Usuário ou senha incorretos."
            log.warning(f"[auth] Tentativa falha de {ip} (usuário={usuario!r}).")

        return render_template("login.html", erro=erro, proximo=proximo,
                               robot_id=robot_id_fn()), (200 if not erro else 401)

    @app.route("/logout")
    def logout():
        session.clear()
        return redirect(url_for("login"))
