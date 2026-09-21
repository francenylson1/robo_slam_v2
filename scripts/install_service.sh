#!/usr/bin/env bash
# scripts/install_service.sh — instala o serviço systemd do robô (Fase 1.5)
# Rodar NA RASPBERRY PI, a partir da raiz do projeto:
#   sudo bash scripts/install_service.sh <robot_id>     (padrão: 1)
set -euo pipefail

ROBOT_ID="${1:-1}"
PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"

if [[ $EUID -ne 0 ]]; then
    echo "Use sudo: sudo bash scripts/install_service.sh ${ROBOT_ID}" >&2
    exit 1
fi

# Usuário dono do projeto. NÃO assumir "pi": cada placa da frota pode ter um
# usuário diferente (esta Pi usa "amd"). Preferimos quem chamou o sudo; se não
# houver, caímos no dono do diretório do projeto.
RUN_USER="${SUDO_USER:-$(stat -c '%U' "${PROJECT_DIR}")}"
if [[ -z "${RUN_USER}" || "${RUN_USER}" == "root" ]]; then
    RUN_USER="$(stat -c '%U' "${PROJECT_DIR}")"
fi

VENV_PY="${PROJECT_DIR}/.venv/bin/python"
if [[ ! -x "${VENV_PY}" ]]; then
    echo "ERRO: ${VENV_PY} não existe ou não é executável." >&2
    echo "Crie o venv antes:  python3 -m venv --system-site-packages .venv" >&2
    exit 1
fi

echo "── Usuário do serviço: ${RUN_USER}"
echo "── Diretório do projeto: ${PROJECT_DIR}"

echo "── Identidade do robô: ROBOT_ID=${ROBOT_ID} → /etc/frota.conf"
echo "ROBOT_ID=${ROBOT_ID}" > /etc/frota.conf

echo "── Instalando o serviço frota-robo.service (modelo + substituição)"
sed -e "s|__USER__|${RUN_USER}|g" \
    -e "s|__PROJECT_DIR__|${PROJECT_DIR}|g" \
    "${PROJECT_DIR}/deploy/frota-robo.service" > /etc/systemd/system/frota-robo.service

if grep -q "__USER__\|__PROJECT_DIR__" /etc/systemd/system/frota-robo.service; then
    echo "ERRO: sobrou placeholder no unit instalado." >&2
    exit 1
fi

echo "── Watchdog de HARDWARE: systemd alimenta /dev/watchdog (kernel trava → Pi reinicia)"
mkdir -p /etc/systemd/system.conf.d
cat > /etc/systemd/system.conf.d/10-frota-watchdog.conf <<'EOF'
[Manager]
RuntimeWatchdogSec=10
RebootWatchdogSec=2min
EOF

echo "── Ativando"
systemctl daemon-reload
systemctl daemon-reexec          # aplica o RuntimeWatchdogSec sem reboot
systemctl enable --now frota-robo.service

echo
systemctl status frota-robo --no-pager || true
echo
echo "PROVA DO GATE (Fase 1.5): mate o processo e veja o serviço voltar sozinho:"
echo "  sudo systemctl kill -s SIGKILL frota-robo && sleep 5 && systemctl status frota-robo --no-pager"
echo "Logs ao vivo:  journalctl -u frota-robo -f"
