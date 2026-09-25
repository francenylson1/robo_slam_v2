#!/usr/bin/env python3
"""
scripts/bancada_aurora.py
Primeira prova do Slamtec Aurora no robô — SÓ LEITURA.

Não comanda motor, não toca em GPIO e não muda o modo do Aurora (não inicia,
não apaga e não salva mapa). Pode rodar com o frota-robo no ar.

LIGAÇÃO (decidida em 25/09/2026): cabo de rede direto Aurora ↔ Pi.
  Aurora: IP fixo de fábrica 192.168.11.1 (manual, seção 2.3).
  Pi:     perfil NetworkManager "aurora" no eth0 — 192.168.11.2/24, sem
          rota padrão, para o Wi-Fi (e o SSH) continuarem donos da saída.
  Alimentação: 12 V / 2 A, bateria separada de 36 V com step-down.
SDK: slamtec_aurora_python_sdk 2.1.1 (wheel linux_aarch64 do GitHub da
Slamtec, instalado no .venv — não está no PyPI, por isso fora do
requirements.txt).

O QUE ELE PROVA, em ordem (cada etapa só roda se a anterior passou):
  1. Rede   — o Aurora responde ao ping pelo cabo.
  2. SDK    — conecta e lê modelo, firmware e número de série.
  3. Pose   — lê x, y e rumo por N segundos; mede a taxa de poses novas.
  4. Câmera — salva as imagens esquerda e direita em data/aurora/, para ver
              quanto do display de 7" aparece na borda de baixo do olho-de-peixe.

Uso (na Pi):
  .venv/bin/python scripts/bancada_aurora.py                # 10 s de pose + fotos
  .venv/bin/python scripts/bancada_aurora.py --segundos 30 --sem-fotos
"""

import argparse
import math
import os
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PASTA_FOTOS = os.path.join(ROOT, "data", "aurora")


def etapa(n, titulo):
    print(f"\n[{n}] {titulo}")


def ok(msg):
    print(f"    OK   {msg}")


def falha(msg):
    print(f"    FALHA {msg}")


def prova_rede(ip):
    r = subprocess.run(["ping", "-c", "2", "-W", "1", ip],
                       capture_output=True, text=True)
    if r.returncode == 0:
        linha = [l for l in r.stdout.splitlines() if "rtt" in l or "round-trip" in l]
        ok(f"{ip} responde ({linha[0].split('=')[-1].strip() if linha else 'ping ok'})")
        return True
    falha(f"{ip} não responde. Confira: Aurora ligado (luz amarela/verde), "
          f"cabo nas duas pontas, `nmcli con show aurora` ativo no eth0.")
    return False


def prova_pose(sdk, segundos):
    """Lê a pose a ~10 Hz. Rumo em graus (o SDK entrega o rpy em radianos)."""
    t0 = time.time()
    ultimo_ts, novas, erros = None, 0, 0
    primeira = ultima = None
    while time.time() - t0 < segundos:
        try:
            pos, rpy, ts = sdk.data_provider.get_current_pose(use_se3=False)
        except Exception as e:
            erros += 1
            if erros <= 3:
                print(f"    ...  pose ainda não disponível: {e}")
            time.sleep(0.1)
            continue
        if ts != ultimo_ts:
            novas += 1
            ultimo_ts = ts
            ultima = (pos, rpy)
            # O 1º segundo após conectar não é referência: vem (0, 0, 0) e
            # depois um ou dois saltos até a pose assentar (25/09: 5 a 10 cm).
            if primeira is None and time.time() - t0 >= 1.0:
                primeira = ultima
        if novas and novas % 10 == 1:
            x, y, _ = pos
            print(f"    x={x:+7.3f} m  y={y:+7.3f} m  rumo={math.degrees(rpy[2]):+7.1f}°")
        time.sleep(0.1)
    if primeira is None:
        falha(f"nenhuma pose após o 1º segundo ({novas} poses, {erros} erros)")
        return False
    (x0, y0, _), _ = primeira
    (x1, y1, _), rpy1 = ultima
    ok(f"{novas} poses novas em {segundos} s (~{novas / segundos:.1f}/s; "
       f"o script consulta a 10/s) · {erros} erros")
    print(f"    deslocamento após o 1º segundo: {math.hypot(x1 - x0, y1 - y0) * 100:.1f} cm "
          f"(robô parado → deve ficar perto de 0)")
    return True


def prova_camera(sdk):
    import cv2
    os.makedirs(PASTA_FOTOS, exist_ok=True)
    carimbo = time.strftime("%Y%m%d_%H%M%S")
    for tentativa in range(20):
        try:
            esq, dir_ = sdk.data_provider.get_camera_preview()
            break
        except Exception as e:
            if tentativa == 19:
                falha(f"câmera sem imagem: {e}")
                return False
            time.sleep(0.25)
    salvos = []
    for nome, quadro in (("esquerda", esq), ("direita", dir_)):
        img = quadro.to_opencv_image() if quadro.has_image_data() else None
        if img is None:
            falha(f"quadro {nome} vazio")
            continue
        caminho = os.path.join(PASTA_FOTOS, f"{carimbo}_{nome}.png")
        cv2.imwrite(caminho, img)
        salvos.append(caminho)
        ok(f"{nome}: {img.shape[1]}×{img.shape[0]} → {os.path.relpath(caminho, ROOT)}")
    return bool(salvos)


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    ap.add_argument("--ip", default="192.168.11.1")
    ap.add_argument("--segundos", type=float, default=10.0)
    ap.add_argument("--sem-fotos", action="store_true")
    args = ap.parse_args()

    etapa(1, f"Rede — ping em {args.ip} pelo cabo")
    if not prova_rede(args.ip):
        return 1

    etapa(2, "SDK — conectar e identificar o aparelho")
    try:
        from slamtec_aurora_sdk import AuroraSDK
    except ImportError as e:
        falha(f"SDK não instalado no .venv: {e}")
        return 1
    sdk = AuroraSDK()
    try:
        sdk.connect(connection_string=args.ip)
        info = sdk.get_device_info()
        ok(f"{info.device_name} · modelo {info.device_model_string} · "
           f"firmware {info.firmware_version} · série {info.serial_number}")

        etapa(3, f"Pose — {args.segundos:.0f} s com o robô PARADO")
        pose_ok = prova_pose(sdk, args.segundos)

        cam_ok = True
        if not args.sem_fotos:
            etapa(4, "Câmera — fotos para conferir o display na borda de baixo")
            cam_ok = prova_camera(sdk)
    except Exception as e:
        falha(f"conexão/SDK: {e}")
        return 1
    finally:
        try:
            sdk.disconnect()
            sdk.release()
        except Exception:
            pass

    print("\nRESULTADO:", "VERDE ✅" if (pose_ok and cam_ok) else "com falhas ❌")
    return 0 if (pose_ok and cam_ok) else 1


if __name__ == "__main__":
    sys.exit(main())
