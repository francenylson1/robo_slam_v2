#!/usr/bin/env bash
# scripts/install_rosto.sh — instala o quiosque do rosto animado (Fase 2)
# Rodar NA RASPBERRY PI, a partir da raiz do projeto:
#   sudo bash scripts/install_rosto.sh [url]
#
# Padrão da url: http://127.0.0.1:5000/rosto
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
URL="${1:-http://127.0.0.1:5000/rosto}"

if [[ $EUID -ne 0 ]]; then
    echo "Use sudo: sudo bash scripts/install_rosto.sh" >&2
    exit 1
fi

RUN_USER="${SUDO_USER:-$(stat -c '%U' "${PROJECT_DIR}")}"
if [[ -z "${RUN_USER}" || "${RUN_USER}" == "root" ]]; then
    RUN_USER="$(stat -c '%U' "${PROJECT_DIR}")"
fi
RUN_UID="$(id -u "${RUN_USER}")"

for prog in /usr/bin/cage /usr/bin/chromium; do
    if [[ ! -x "${prog}" ]]; then
        echo "ERRO: ${prog} não encontrado." >&2
        echo "Instale com: sudo apt install -y cage chromium" >&2
        exit 1
    fi
done

# O compositor precisa falar com a placa de vídeo e com os dispositivos de
# entrada. Sem estes grupos, `cage` sobe e morre sem mensagem útil.
for grupo in video render input; do
    if ! id -nG "${RUN_USER}" | tr ' ' '\n' | grep -qx "${grupo}"; then
        echo "── acrescentando ${RUN_USER} ao grupo ${grupo}"
        usermod -aG "${grupo}" "${RUN_USER}"
    fi
done

echo "── Usuário do quiosque: ${RUN_USER} (uid ${RUN_UID})"
echo "── URL do rosto: ${URL}"

sed -e "s|__USER__|${RUN_USER}|g" \
    -e "s|__UID__|${RUN_UID}|g" \
    -e "s|__URL__|${URL}|g" \
    "${PROJECT_DIR}/deploy/frota-rosto.service" > /etc/systemd/system/frota-rosto.service

if grep -q "__USER__\|__UID__\|__URL__" /etc/systemd/system/frota-rosto.service; then
    echo "ERRO: sobrou placeholder no unit instalado." >&2
    exit 1
fi

systemctl daemon-reload
systemctl enable --now frota-rosto.service

echo
systemctl status frota-rosto --no-pager || true
echo
echo "Logs ao vivo:   journalctl -u frota-rosto -f"
echo "Parar o rosto:  sudo systemctl stop frota-rosto"
echo
echo "As duas HDMI estão ligadas, e o 'cage -m last' usa só UMA saída."
echo "Se o rosto aparecer na tela errada, troque para a outra com:"
echo "  sudo sed -i 's/-m last/-m extend/' /etc/systemd/system/frota-rosto.service"
echo "ou inverta fisicamente os cabos HDMI."
