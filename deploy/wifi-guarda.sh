#!/bin/sh
# deploy/wifi-guarda.sh — o robô não fica fora do Wi-Fi até alguém religar.
#
# 24/11/2026 (robô 2, três vezes no mesmo dia): ao ligar, a 1ª associação
# falhou ("4-Way Handshake failed", falso — a senha estava certa) e o
# NetworkManager marcou a rede como "sem senha" e PAROU de tentar, mesmo com
# autoconnect-retries 0 (para sempre); noutra vez o roteador recusou a
# associação (status 16) por alguns minutos depois de um corte de energia.
# Daqui: se o wlan0 está fora há mais de 20 s, pede para conectar de novo.
# Roda pelo wifi-guarda.timer a cada 30 s. Não mexe em senha nem em perfil.
# (A economia de energia do Wi-Fi fica desligada no perfil:
#  nmcli connection modify <rede> 802-11-wireless.powersave 2.)

conectado() { nmcli -t -f DEVICE,STATE device 2>/dev/null | grep -q '^wlan0:connected'; }

conectado && exit 0
sleep 20
conectado && exit 0
logger -t wifi-guarda "wlan0 fora da rede há mais de 20 s — pedindo para conectar de novo"
if nmcli --wait 40 device connect wlan0 >/dev/null 2>&1; then
    logger -t wifi-guarda "wlan0 conectado de novo"
else
    logger -t wifi-guarda "wlan0 ainda não conectou — tento de novo em 30 s"
fi
