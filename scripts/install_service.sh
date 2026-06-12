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

echo "── Identidade do robô: ROBOT_ID=${ROBOT_ID} → /etc/frota.conf"
echo "ROBOT_ID=${ROBOT_ID}" > /etc/frota.conf

echo "── Instalando o serviço frota-robo.service"
cp "${PROJECT_DIR}/deploy/frota-robo.service" /etc/systemd/system/frota-robo.service

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
