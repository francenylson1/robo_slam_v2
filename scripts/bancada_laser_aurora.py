#!/usr/bin/env python3
"""
scripts/bancada_laser_aurora.py — 01/10/2026.
Mede quanto custa ler o laser do Aurora, e onde (SÓ LEITURA: não mexe no
modo do Aurora, não toca em motor nem GPIO). Recusa com o frota-robo no ar
(um cliente só no Aurora).

Motivo: a leitura do laser (gravador, campo "a145") rodava na mesma thread da
pose e a envelhecia até 0,39 s (3 missões "pose velha" em 01/10). Antes de
corrigir, medir:
  1. o pedido ao Aurora (peek_recent_lidar_scan) com 8192 e com 3000 pontos;
  2. a conversão em Python, ponto a ponto (como no aurora_pose.py de hoje);
  3. a conversão em bloco (numpy), se o tipo dos pontos permitir;
  4. duas threads na mesma conexão: pose a 10 Hz + laser a 1 Hz — erros?
     idade máxima da pose?

Uso (na Pi, serviço parado, robô parado):
  .venv/bin/python scripts/bancada_laser_aurora.py [--segundos 20]
"""
import argparse, math, os, statistics, sys, threading, time

_RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _RAIZ)
from sensors.aurora_cliente_unico import exigir_servico_parado  # noqa: E402
from sensors.aurora_pose import _laser_do_sdk                   # noqa: E402
from config.settings import AURORA_IP                            # noqa: E402


def ms(v):
    v = sorted(v)
    return (f"mediana {statistics.median(v)*1000:6.1f} ms, p90 {v[int(len(v)*.9)]*1000:6.1f}, "
            f"máx {v[-1]*1000:6.1f} (n={len(v)})")


def conv_python(pontos):
    return [[int(round(math.degrees(pt.angle) * 100)) % 36000,
             int(round(pt.dist * 1000)), int(pt.quality)]
            for pt in pontos if pt.quality > 0 and pt.dist > 0]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--segundos", type=float, default=20.0)
    args = ap.parse_args()
    exigir_servico_parado()
    import numpy as np
    from slamtec_aurora_sdk import AuroraSDK
    sdk = AuroraSDK()
    sdk.connect(connection_string=AURORA_IP)
    time.sleep(1.5)
    try:
        r = _laser_do_sdk(sdk, 8192)
        info, pontos, pose = r
        print(f"tipo dos pontos: {type(pontos).__name__}, len {len(pontos)}; "
              f"item {type(pontos[0]).__name__ if len(pontos) else '-'}; "
              f"info: {[a for a in dir(info) if not a.startswith('_')][:12]}")

        print("\n1-2. uma thread, em sequência (20 repetições):")
        t_pose, t8, t3, tconv, tnp, npts = [], [], [], [], [], []
        np_ok = None
        for _ in range(20):
            a = time.perf_counter(); sdk.data_provider.get_current_pose(use_se3=False); t_pose.append(time.perf_counter() - a)
            a = time.perf_counter(); r = _laser_do_sdk(sdk, 8192); t8.append(time.perf_counter() - a)
            a = time.perf_counter(); _laser_do_sdk(sdk, 3000); t3.append(time.perf_counter() - a)
            _i, pts, _p = r
            a = time.perf_counter(); out = conv_python(pts); tconv.append(time.perf_counter() - a)
            npts.append(len(out))
            try:
                a = time.perf_counter()
                arr = np.ctypeslib.as_array(pts) if not isinstance(pts, list) else None
                if arr is not None and arr.dtype.names:
                    m = (arr["quality"] > 0) & (arr["dist"] > 0)
                    _o = np.stack([(np.round(np.degrees(arr["angle"][m]) * 100) % 36000).astype(int),
                                   np.round(arr["dist"][m] * 1000).astype(int),
                                   arr["quality"][m].astype(int)], 1).tolist()
                    tnp.append(time.perf_counter() - a); np_ok = True
                else:
                    np_ok = f"sem campos ({type(pts).__name__})"
            except Exception as e:
                np_ok = f"falhou: {e}"
            time.sleep(0.2)
        print(f"  pose             {ms(t_pose)}")
        print(f"  laser, 8192 pts  {ms(t8)}")
        print(f"  laser, 3000 pts  {ms(t3)}")
        print(f"  conversão Python {ms(tconv)}  ({statistics.median(npts):.0f} pontos válidos)")
        print(f"  conversão numpy  {ms(tnp) if tnp else np_ok}")

        print(f"\n4. duas threads na mesma conexão ({args.segundos:.0f} s): pose 10 Hz + laser 1 Hz")
        fim = time.time() + args.segundos
        idades, erros_p, erros_l, lat_l = [], [], [], []
        ultimo = {"ts": None, "quando": time.perf_counter()}

        def pose_loop():
            while time.time() < fim:
                try:
                    _pos, _rpy, ts = sdk.data_provider.get_current_pose(use_se3=False)
                    agora = time.perf_counter()
                    if ts != ultimo["ts"]:
                        idades.append(agora - ultimo["quando"]); ultimo["ts"] = ts; ultimo["quando"] = agora
                except Exception as e:
                    erros_p.append(str(e))
                time.sleep(0.1)

        def laser_loop():
            while time.time() < fim:
                try:
                    a = time.perf_counter(); r = _laser_do_sdk(sdk, 8192); conv_python(r[1]); lat_l.append(time.perf_counter() - a)
                except Exception as e:
                    erros_l.append(str(e))
                time.sleep(1.0)

        th = [threading.Thread(target=pose_loop), threading.Thread(target=laser_loop)]
        [t.start() for t in th]; [t.join() for t in th]
        print(f"  intervalo entre poses novas: {ms(idades[1:])}")
        print(f"  laser (pedido + conversão): {ms(lat_l)}")
        print(f"  erros: pose {len(erros_p)} {erros_p[:2]}, laser {len(erros_l)} {erros_l[:2]}")
        print(f"  conexão viva no fim: {sdk.controller.is_device_connection_alive()}")
    finally:
        sdk.disconnect(); sdk.release()


if __name__ == "__main__":
    main()
