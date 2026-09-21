#!/bin/sh
# deploy/rosto-kiosk.sh — abre a janela do rosto (v2) na tela de 7" do robô.
#
# ESTE SCRIPT SEGUE A RECEITA JÁ VALIDADA NO PROJETO v1
# (~/robo_slam/deploy/bin/lancar_telas.sh). As três restrições abaixo estão
# documentadas lá e custaram várias tentativas — não as "simplifique":
#
#  1. --ozone-platform=x11 é OBRIGATÓRIO. Em Wayland nativo o Chromium ignora
#     --window-position em silêncio. Sob XWayland as duas telas viram um
#     desktop único e o posicionamento funciona.
#  2. NÃO usar --kiosk nem --start-fullscreen: os dois sobrepõem a posição e
#     abrem sempre na tela primária. A tela cheia sem decoração vem da regra
#     do labwc em ~/.config/labwc/rc.xml.
#  3. A regra do labwc casa pelo identificador da janela, daí o --class.
#     `robot_face` casa a regra <windowRule identifier="*robot_face*">, que
#     manda a janela para HDMI-A-1 e aplica tela cheia.
#
# A VITRINE DA TELA DE 15,6" NÃO É TRATADA AQUI. Ela continua por conta do v1
# (vitrine-telas.service), que roda com ROBO_SEM_ROSTO=1 para não abrir o rosto
# antigo no 7" e disputar a tela com este.
#
# O user-data-dir é /tmp/rosto_v2 DE PROPÓSITO: o lancar_telas.sh do v1 faz
# `pkill -f 'chromium.*cr_(face|vitrine)'` ao subir, e um diretório chamado
# cr_face_* seria varrido junto a cada reinício da vitrine.

set -u

URL="${ROSTO_URL:-http://127.0.0.1:5000/rosto}"
CLASSE="${ROSTO_CLASSE:-robot_face}"
POS="${ROSTO_POS:-0,0}"
TAM="${ROSTO_TAM:-1024,600}"

log() { echo "[rosto-kiosk] $*" >&2; }

export DISPLAY="${DISPLAY:-:0}"
export XDG_RUNTIME_DIR="${XDG_RUNTIME_DIR:-/run/user/$(id -u)}"
export XAUTHORITY="${XAUTHORITY:-$HOME/.Xauthority}"

# 1) Espera o XWayland. Somos o comando de sessão do labwc, então subimos antes
#    de o servidor X existir — sem esta espera o Chromium morre na largada.
i=0
while [ $i -lt 60 ]; do
    [ -S /tmp/.X11-unix/X0 ] && break
    i=$((i + 1))
    sleep 0.5
done
[ -S /tmp/.X11-unix/X0 ] || log "AVISO: XWayland não apareceu; tentando mesmo assim."

# 2) Cookie do X amarrado ao hostname (mesma correção do v1). Se a Pi for
#    renomeada, o cliente não acha entrada para o nome novo e nenhuma janela
#    abre — sem erro no systemd, com a unit "active" e a tela vazia.
if command -v xauth >/dev/null 2>&1 && [ -f "$XAUTHORITY" ]; then
    if ! xauth -f "$XAUTHORITY" list 2>/dev/null | grep -q "^$(hostname)/unix:0"; then
        COOKIE=$(xauth -f "$XAUTHORITY" list 2>/dev/null \
                 | awk '$2=="MIT-MAGIC-COOKIE-1"{print $3; exit}')
        if [ -n "$COOKIE" ]; then
            xauth -f "$XAUTHORITY" add "$(hostname)/unix:0" \
                  MIT-MAGIC-COOKIE-1 "$COOKIE" 2>/dev/null \
                && log "xauth: entrada criada para $(hostname)/unix:0"
        fi
    fi
fi

# 3) Espera o servidor do robô. Sem isto a janela abriria numa página de erro
#    e ficaria nela — o Chromium não recarrega sozinho.
i=0
while [ $i -lt 90 ]; do
    curl -sf -o /dev/null --max-time 2 "$URL" && break
    i=$((i + 1))
    sleep 1
done

log "abrindo $URL como '$CLASSE' em $POS ($TAM)"

exec chromium \
    --ozone-platform=x11 \
    --class="$CLASSE" \
    --user-data-dir=/tmp/rosto_v2 \
    --no-first-run \
    --disable-infobars \
    --noerrdialogs \
    --disable-session-crashed-bubble \
    --disable-features=TranslateUI \
    --check-for-update-interval=31536000 \
    --overscroll-history-navigation=0 \
    --autoplay-policy=no-user-gesture-required \
    --window-position="$POS" \
    --window-size="$TAM" \
    --app="$URL"
