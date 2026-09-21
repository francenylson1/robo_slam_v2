#!/usr/bin/env python3
"""
scripts/set_web_password.py
Define o usuário e a senha do dashboard do robô (Fase 2).

Grava FROTA_WEB_USER e FROTA_WEB_PASSWORD_HASH em /etc/frota.conf — o mesmo
arquivo que o systemd lê como EnvironmentFile. A senha em texto NUNCA é
gravada: só o hash (PBKDF2, via werkzeug).

Uso NA PI:
    sudo python3 scripts/set_web_password.py
    sudo systemctl restart frota-robo

Sem isso, o robô sorteia uma senha a cada reinício e a publica no log:
    journalctl -u frota-robo | grep SENHA
"""

import getpass
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    from werkzeug.security import generate_password_hash
except ImportError:
    sys.exit("werkzeug ausente. Rode dentro do venv: source .venv/bin/activate")

CONF = os.environ.get("FROTA_CONF", "/etc/frota.conf")
MIN_LEN = 8


def escrever_chave(linhas: list[str], chave: str, valor: str) -> list[str]:
    """Substitui a linha de `chave` se existir; senão acrescenta."""
    padrao = re.compile(rf"^\s*{re.escape(chave)}\s*=")
    nova = f"{chave}={valor}\n"
    for i, ln in enumerate(linhas):
        if padrao.match(ln):
            linhas[i] = nova
            return linhas
    if linhas and not linhas[-1].endswith("\n"):
        linhas[-1] += "\n"
    linhas.append(nova)
    return linhas


def main() -> int:
    if not os.access(os.path.dirname(CONF) or "/", os.W_OK):
        print(f"Sem permissão de escrita em {CONF}. Use: sudo python3 {sys.argv[0]}",
              file=sys.stderr)
        return 1

    print(f"Configurando o acesso ao dashboard em {CONF}\n")

    usuario = input("Usuário [operador]: ").strip() or "operador"

    senha = getpass.getpass("Senha: ")
    if len(senha) < MIN_LEN:
        print(f"Senha muito curta — mínimo {MIN_LEN} caracteres.", file=sys.stderr)
        return 1
    if senha != getpass.getpass("Repita a senha: "):
        print("As senhas não conferem.", file=sys.stderr)
        return 1

    linhas: list[str] = []
    if os.path.exists(CONF):
        with open(CONF) as f:
            linhas = f.readlines()

    linhas = escrever_chave(linhas, "FROTA_WEB_USER", usuario)
    # Aspas simples: o hash do werkzeug contém "$", que o systemd expandiria.
    linhas = escrever_chave(linhas, "FROTA_WEB_PASSWORD_HASH",
                            "'" + generate_password_hash(senha) + "'")

    with open(CONF, "w") as f:
        f.writelines(linhas)
    os.chmod(CONF, 0o600)

    print(f"\nGravado em {CONF} (modo 600 — só o root lê).")
    print("A senha em texto não foi gravada; só o hash PBKDF2.")
    print("\nAplique com:  sudo systemctl restart frota-robo")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
