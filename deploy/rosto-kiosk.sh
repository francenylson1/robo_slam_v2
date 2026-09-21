#!/bin/sh
# deploy/rosto-kiosk.sh — cliente do compositor de quiosque do rosto.
#
# POR QUE ESTE INTERMEDIÁRIO EXISTE:
# O robô tem DUAS saídas HDMI ligadas (7" do rosto e 15,6" da sinalização).
# O `cage` não deixa escolher em qual saída desenhar: só oferece "espalhar por
# todas" ou "usar a última". Mas ele implementa wlr-output-management, então
# dá para, já dentro da sessão, desligar as saídas que não queremos e sobrar
# exatamente a tela do rosto.
#
# ROSTO_OUTPUT vem do serviço (ex.: HDMI-A-1). Sem ela, nada é mexido e o
# comportamento é o padrão do cage.

set -u

if [ -n "${ROSTO_OUTPUT:-}" ] && command -v wlr-randr >/dev/null 2>&1; then
    # O compositor pode levar um instante para publicar as saídas.
    saidas=""
    i=0
    while [ $i -lt 20 ]; do
        saidas=$(wlr-randr 2>/dev/null | grep -E '^[A-Za-z]' | cut -d' ' -f1)
        [ -n "$saidas" ] && break
        i=$((i + 1))
        sleep 0.25
    done

    if [ -z "$saidas" ]; then
        echo "[rosto-kiosk] wlr-randr não listou saídas — seguindo com o padrão do cage." >&2
    else
        echo "[rosto-kiosk] saídas vistas: $(echo "$saidas" | tr '\n' ' ')" >&2
        achou=0
        for o in $saidas; do
            if [ "$o" = "$ROSTO_OUTPUT" ]; then
                achou=1
            else
                echo "[rosto-kiosk] desligando $o" >&2
                wlr-randr --output "$o" --off >/dev/null 2>&1 || true
            fi
        done
        if [ "$achou" = "1" ]; then
            wlr-randr --output "$ROSTO_OUTPUT" --on >/dev/null 2>&1 || true
            echo "[rosto-kiosk] rosto em $ROSTO_OUTPUT" >&2
        else
            # Não desliga tudo por causa de um nome errado: melhor o rosto na
            # tela errada do que nenhuma tela acesa.
            echo "[rosto-kiosk] AVISO: $ROSTO_OUTPUT não existe. Saídas: $(echo "$saidas" | tr '\n' ' ')" >&2
            for o in $saidas; do
                wlr-randr --output "$o" --on >/dev/null 2>&1 || true
            done
        fi
    fi
fi

exec /usr/bin/chromium "$@"
