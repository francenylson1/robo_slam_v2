#!/usr/bin/env bash
# scripts/install_rosto.sh — instala o quiosque do rosto animado (Fase 2)
# Rodar NA RASPBERRY PI, a partir da raiz do projeto:
#   sudo bash scripts/install_rosto.sh [url]
#
# Padrão da url: http://127.0.0.1:5000/rosto
#
# ─────────────────────────────────────────────────────────────────────────
# COMO ISTO CONVIVE COM O PROJETO v1
#
# Esta Pi já tinha, desde 12/09/2026, um sistema de telas do projeto v1
# (~/robo_slam): kanshi com o perfil das duas telas, regras de janela em
# ~/.config/labwc/rc.xml e o vitrine-telas.service abrindo as janelas.
# NADA DISSO É SUBSTITUÍDO. O que este instalador faz:
#
#   1. sobe o compositor (labwc) como serviço de sistema — necessário porque
#      a Pi passou a rodar em multi-user.target, sem sessão gráfica;
#   2. abre a janela do rosto NOVO (v2, porta 5000) no lugar do antigo;
#   3. liga ROBO_SEM_ROSTO=1 no vitrine-telas.service do v1, usando o gancho
#      que o próprio script do v1 já previa, para ele abrir SÓ a vitrine da
#      tela de 15,6" e não disputar o 7" com o rosto novo.
#
# A escolha de tela NÃO está aqui: quem posiciona é a regra
# <windowRule identifier="*robot_face*"> do rc.xml, e quem configura as saídas
# é o kanshi do v1.
# ─────────────────────────────────────────────────────────────────────────
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
RUN_HOME="$(getent passwd "${RUN_USER}" | cut -d: -f6)"

for prog in /usr/bin/labwc /usr/bin/chromium /usr/bin/xauth; do
    if [[ ! -x "${prog}" ]]; then
        echo "ERRO: ${prog} não encontrado." >&2
        echo "Instale com: sudo apt install -y labwc chromium xauth" >&2
        exit 1
    fi
done

# O compositor precisa falar com a placa de vídeo e com os dispositivos de
# entrada. Sem estes grupos, ele sobe e morre sem mensagem útil.
for grupo in video render input; do
    if ! id -nG "${RUN_USER}" | tr ' ' '\n' | grep -qx "${grupo}"; then
        echo "── acrescentando ${RUN_USER} ao grupo ${grupo}"
        usermod -aG "${grupo}" "${RUN_USER}"
    fi
done

echo "── Usuário do quiosque: ${RUN_USER} (uid ${RUN_UID})"
echo "── URL do rosto: ${URL}"

# ── 1. serviço do compositor + rosto ────────────────────────────────────
sed -e "s|__USER__|${RUN_USER}|g" \
    -e "s|__UID__|${RUN_UID}|g" \
    -e "s|__URL__|${URL}|g" \
    -e "s|__PROJECT_DIR__|${PROJECT_DIR}|g" \
    "${PROJECT_DIR}/deploy/frota-rosto.service" > /etc/systemd/system/frota-rosto.service

if grep -q "__USER__\|__UID__\|__URL__\|__PROJECT_DIR__" \
        /etc/systemd/system/frota-rosto.service; then
    echo "ERRO: sobrou placeholder no unit instalado." >&2
    exit 1
fi

# ── 2. o v1 abre só a vitrine (gancho previsto pelo próprio v1) ─────────
VIT="${RUN_HOME}/.config/systemd/user/vitrine-telas.service"
if [[ -e "${VIT}" ]]; then
    DROPIN="${RUN_HOME}/.config/systemd/user/vitrine-telas.service.d"
    mkdir -p "${DROPIN}"
    cat > "${DROPIN}/10-rosto-v2.conf" <<'EOF'
# Instalado por robo_slam_v2/scripts/install_rosto.sh.
# ROBO_SEM_ROSTO=1 é o gancho do próprio lancar_telas.sh do v1: com ele, o v1
# abre SÓ a vitrine da tela de 15,6" e deixa o 7" para o rosto novo (v2),
# servido pelo frota-robo na porta 5000.
# Para voltar ao rosto antigo, apague este arquivo e recarregue:
#   systemctl --user daemon-reload && systemctl --user restart vitrine-telas
[Service]
Environment=ROBO_SEM_ROSTO=1
EOF
    chown -R "${RUN_USER}:${RUN_USER}" "${DROPIN}"
    echo "── vitrine-telas (v1): ROBO_SEM_ROSTO=1 — o v1 abre só a vitrine"
    sudo -u "${RUN_USER}" XDG_RUNTIME_DIR="/run/user/${RUN_UID}" \
        systemctl --user daemon-reload 2>/dev/null || true
else
    echo "── vitrine-telas (v1) não encontrado — seguindo só com o rosto"
fi

# ── 3. mapeamento do toque do 7" (ficou só no rc.xml.antes-vitrine) ─────
RC="${RUN_HOME}/.config/labwc/rc.xml"
if [[ -f "${RC}" ]] && ! grep -q "<touch " "${RC}"; then
    TOQUE="$(grep -h "<touch " "${RUN_HOME}"/.config/labwc/rc.xml.* 2>/dev/null | head -1 || true)"
    if [[ -n "${TOQUE}" ]]; then
        cp "${RC}" "${RC}.bak-$(date +%Y%m%d-%H%M)"
        python3 - "$RC" "$TOQUE" <<'PY'
import sys
caminho, toque = sys.argv[1], sys.argv[2].strip()
with open(caminho, encoding="utf-8") as f:
    texto = f.read()
nota = ('  <!-- Restaurado por robo_slam_v2: o 7" e touchscreen e o mapeamento\n'
        '       havia se perdido na edicao da vitrine. -->\n  ' + toque + '\n\n')
texto = texto.replace("</openbox_config>", nota + "</openbox_config>", 1)
with open(caminho, "w", encoding="utf-8") as f:
    f.write(texto)
PY
        chown "${RUN_USER}:${RUN_USER}" "${RC}"
        echo "── rc.xml: mapeamento de toque do 7\" restaurado (backup ao lado)"
    fi
fi

systemctl daemon-reload
systemctl enable --now frota-rosto.service

echo
systemctl status frota-rosto --no-pager || true
echo
echo "Logs ao vivo:  journalctl -u frota-rosto -f"
echo "Parar tudo:    sudo systemctl stop frota-rosto"
echo
echo "Telas (o kanshi do v1 é quem as configura):"
for c in /sys/class/drm/card*-HDMI*; do
    n="$(basename "$c" | sed 's/^card[0-9]*-//')"
    printf "  %-12s %s  %s\n" "$n" "$(cat "$c/status" 2>/dev/null)" "$(head -1 "$c/modes" 2>/dev/null)"
done
