#!/usr/bin/env python3
"""
scripts/aurora_carregar_mapa.py
Carrega um mapa salvo no Aurora e faz o robô se localizar nele.

A SEQUÊNCIA QUE FUNCIONA (descoberta na bancada de 25/09/2026):
  1. zerar o mapa        — é o que põe o rastreio para rodar depois de religar
  2. carregar o .stcm    — upload do mapa salvo
  3. relocalizar         — o Aurora se acha no mapa (status 13)

O que NÃO funciona depois de religar o Aurora (luz amarela fixa, pose zerada):
upload + relocalizar direto (falha com status 14), nem com o modo
só-localização ou o modo de mapeamento pedidos antes.

Medido em 25/09 com o mapa da metade do laboratório: depois da relocalização,
empurrões de 1,00 m e 1,50 m na trena deram 98,6 cm e 151,1 cm no Aurora, com
giro de 0,1–0,2°.

SÓ VALE RESPOSTA NOVA: o Aurora guarda o último status. Cada passo anota o
carimbo de tempo do status antes do pedido e só aceita um status com carimbo
diferente. Sem isso, a 1ª versão deste script leu o sucesso de uma
relocalização anterior e disse VERDE com o aparelho em "falha de
inicialização" (status 1).

⚠️ O robô precisa estar PARADO do começo ao fim. O passo 1 apaga o mapa que
está DENTRO do Aurora (o arquivo .stcm não é tocado).

Só fala com o Aurora — não comanda motor nem toca em GPIO.

Uso (na Pi):
  .venv/bin/python scripts/aurora_carregar_mapa.py data/aurora/mapas/lab_metade_20260925.stcm
"""

import argparse
import math
import os
import sys
import time

# Valores do SDK (slamtec_aurora_sdk.data_types, DEVICE_STATUS_*)
INICIALIZADO   = 0
INIT_FALHOU    = 1   # passageiro: em 25/09 veio 1 e, depois de >15 s, 0 (luz verde)
MAPA_CARREGADO = 11
RELOC_OK       = 13
RELOC_FALHOU   = 14


def mostrar(sdk, rotulo):
    p, r, _ = sdk.data_provider.get_current_pose(use_se3=False)
    st, _ = sdk.data_provider.get_last_device_status()
    print(f"    {rotulo}: x={p[0]:+.3f} m  y={p[1]:+.3f} m  "
          f"rumo={math.degrees(r[2]):+.1f}°  (status {st})")


def pedir(sdk, acao, esperado, falhas, limite_s):
    """
    Anota o carimbo do status atual, executa `acao` e espera um status NOVO.
    Devolve o status novo que for `esperado` ou estiver em `falhas`, ou None
    se nada novo chegar no prazo.
    """
    _, carimbo0 = sdk.data_provider.get_last_device_status()
    if acao() is False:
        return None
    t0 = time.time()
    while time.time() - t0 < limite_s:
        st, carimbo = sdk.data_provider.get_last_device_status()
        if carimbo != carimbo0 and (st == esperado or st in falhas):
            return st
        time.sleep(0.25)
    return None


def main():
    ap = argparse.ArgumentParser(description="Carrega um mapa no Aurora e relocaliza.")
    ap.add_argument("mapa", help="arquivo .stcm salvo do Aurora")
    ap.add_argument("--ip", default="192.168.11.1")
    args = ap.parse_args()

    if not os.path.isfile(args.mapa):
        print(f"Mapa não encontrado: {args.mapa}")
        return 1

    from slamtec_aurora_sdk import AuroraSDK
    sdk = AuroraSDK()
    try:
        sdk.connect(connection_string=args.ip)
        time.sleep(1.5)
        print("Robô PARADO? O mapa dentro do Aurora vai ser zerado.")
        mostrar(sdk, "antes")

        print("\n[1] Zerar o mapa (liga o rastreio) — pode levar até 1 min")
        # A inicialização pode passar por "falhou" (1) antes de dar certo (0):
        # espera só o 0, até 60 s.
        st = pedir(sdk, sdk.controller.require_map_reset, INICIALIZADO, set(), 60)
        if st != INICIALIZADO:
            print("    FALHA: o Aurora não inicializou em 60 s. Robô parado? "
                  "Câmera livre? Luz verde?")
            return 1
        time.sleep(2)
        mostrar(sdk, "inicializado")

        print(f"\n[2] Carregar {os.path.basename(args.mapa)}")
        st = pedir(sdk, lambda: sdk.map_manager.upload_map(args.mapa, timeout_seconds=180),
                   MAPA_CARREGADO, set(), 20)
        if st != MAPA_CARREGADO:
            print(f"    FALHA: o Aurora não confirmou o mapa carregado (status {st}).")
            return 1
        time.sleep(4)
        mostrar(sdk, "mapa carregado")

        print("\n[3] Relocalizar")
        st = pedir(sdk, lambda: sdk.controller.require_relocalization(timeout_ms=20000),
                   RELOC_OK, {RELOC_FALHOU}, 25)
        if st == RELOC_OK:
            mostrar(sdk, "relocalizado")
            print("\nRESULTADO: VERDE ✅ — o robô se achou no mapa (luz verde fixa).")
            return 0
        mostrar(sdk, "sem relocalização")
        print(f"\nRESULTADO: a relocalização FALHOU ❌ (status {st}) — "
              f"o robô está numa área do mapa? Está parado?")
        return 1
    except Exception as e:
        print(f"FALHA: {e}")
        return 1
    finally:
        try:
            sdk.disconnect()
            sdk.release()
        except Exception:
            pass


if __name__ == "__main__":
    sys.exit(main())
