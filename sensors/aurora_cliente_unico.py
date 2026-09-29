"""
sensors/aurora_cliente_unico.py
Um cliente só no Aurora (decisão 6 de 29/09/2026).

Não sabemos se o Aurora aceita dois programas conectados ao mesmo tempo. Se
não aceitar, um script de bancada rodando junto com o frota-robo poderia
derrubar a pose no meio de uma missão. Por isso os scripts de bancada que
falam com o Aurora chamam `exigir_servico_parado()` antes de conectar: com o
serviço ativo, eles se recusam e dizem como parar. Não depende de lembrar.
"""

import shutil
import subprocess
import sys

SERVICOS = ("frota-robo",)


def servico_ativo(nome: str) -> bool:
    if shutil.which("systemctl") is None:
        return False            # fora da Pi (PC de desenvolvimento)
    try:
        r = subprocess.run(["systemctl", "is-active", "--quiet", nome],
                           timeout=5)
        return r.returncode == 0
    except Exception:
        return False


def exigir_servico_parado():
    ativos = [s for s in SERVICOS if servico_ativo(s)]
    if ativos:
        print("RECUSADO: o frota-robo está rodando e já é o cliente do Aurora.\n"
              "Um segundo cliente pode derrubar a pose do serviço.\n"
              "Pare os serviços antes (o rosto religa o frota-robo):\n"
              "  sudo systemctl stop frota-rosto frota-robo\n"
              "e confira que os dois pararam.")
        sys.exit(2)
