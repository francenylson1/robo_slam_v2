#!/usr/bin/env python3
"""
scripts/bancada_aurora_mapeamento.py — 02/10/2026 (Etapa B, antes do desenho).

Mede, SÓ LENDO, o que o modo mapeamento pelo painel vai precisar do Aurora:
  1. baixar o mapa (.stcm) de dentro de um processo que continua lendo a pose
     a 10 Hz: quanto tempo leva e se a pose falha durante o download;
  2. o mapa baixado é o mesmo arquivo que foi enviado (sha)?
  3. gerar a grade 2D (planta) no mesmo processo: tempo e efeito na pose;
  4. os keyframes do mapa: quantos, com que campos (pose otimizada? carimbo?)
     — se der para corrigir as poses gravadas durante o mapeamento.

NÃO zera, NÃO carrega, NÃO relocaliza: o mapa do Aurora fica como está.
Exige o serviço parado (um cliente só):  sudo systemctl stop frota-robo
Uso:  python3 scripts/bancada_aurora_mapeamento.py [--saida /tmp/bancada_b]
"""
import argparse
import hashlib
import json
import os
import sys
import threading
import time

_RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _RAIZ not in sys.path:
    sys.path.insert(0, _RAIZ)
from sensors.aurora_cliente_unico import exigir_servico_parado  # noqa: E402


class VigiaPose(threading.Thread):
    """Lê a pose a 10 Hz e anota o maior intervalo sem pose NOVA por fase."""

    def __init__(self, sdk):
        super().__init__(daemon=True)
        self.sdk, self.fase, self.parar = sdk, "inicio", False
        self.por_fase = {}
        self._lock = threading.Lock()

    def marcar(self, fase):
        with self._lock:
            self.fase = fase

    def run(self):
        ult_ts, ult_t = None, time.monotonic()
        while not self.parar:
            t0 = time.monotonic()
            try:
                _pos, _rpy, ts = self.sdk.data_provider.get_current_pose(use_se3=False)
                erro = None
            except Exception as e:                       # noqa: BLE001
                ts, erro = None, str(e)
            dt = time.monotonic() - t0
            with self._lock:
                f = self.por_fase.setdefault(self.fase, {"consultas": 0, "erros": 0,
                                                          "consulta_max_ms": 0.0,
                                                          "sem_pose_nova_max_ms": 0.0})
                f["consultas"] += 1
                f["consulta_max_ms"] = max(f["consulta_max_ms"], dt * 1000)
                if erro:
                    f["erros"] += 1
                    f["ultimo_erro"] = erro[:120]
                agora = time.monotonic()
                if ts is not None and ts != ult_ts:
                    ult_ts, ult_t = ts, agora
                f["sem_pose_nova_max_ms"] = max(f["sem_pose_nova_max_ms"], (agora - ult_t) * 1000)
            time.sleep(max(0.0, 0.1 - dt))


def sha(c):
    h = hashlib.sha256()
    with open(c, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ip", default="192.168.11.1")
    ap.add_argument("--saida", default="/tmp/bancada_b")
    args = ap.parse_args()
    exigir_servico_parado()
    os.makedirs(args.saida, exist_ok=True)

    from slamtec_aurora_sdk import AuroraSDK
    from slamtec_aurora_sdk.data_types import GridMapGenerationOptions
    import config.settings as S
    res = {"quando": time.strftime("%Y-%m-%d %H:%M:%S")}

    sdk = AuroraSDK()
    sdk.connect(connection_string=args.ip)
    vig = VigiaPose(sdk)
    try:
        time.sleep(1.5)
        st, _ = sdk.data_provider.get_last_device_status()
        res["status"] = str(st)
        print(f"status do Aurora: {st} (13 = relocalizado no mapa)")
        try:
            res["mapas"] = [str(m) for m in sdk.data_provider.get_all_map_info()]
        except Exception as e:                           # noqa: BLE001
            res["mapas"] = f"erro: {e}"
        print("mapas no Aurora:", res["mapas"])
        vig.start()
        time.sleep(5)                                    # referência, sem nada rodando

        # 1-2. download
        vig.marcar("download")
        destino = os.path.join(args.saida, "baixado.stcm")
        t0 = time.monotonic()
        ok = sdk.map_manager.download_map(destino, timeout_seconds=300)
        res["download_s"] = round(time.monotonic() - t0, 1)
        res["download_ok"] = bool(ok)
        if ok and os.path.isfile(destino):
            res["download_mb"] = round(os.path.getsize(destino) / 1e6, 1)
            res["download_sha"] = sha(destino)
            res["igual_ao_enviado"] = res["download_sha"] == S.AURORA_MAPA_SHA256
        print(f"download: ok={ok} em {res['download_s']} s, {res.get('download_mb')} MB, "
              f"igual ao .stcm enviado: {res.get('igual_ao_enviado')}")
        vig.marcar("depois_download"); time.sleep(3)

        # 3. grade 2D (planta) no mesmo processo
        sdk.enable_map_data_syncing(True)
        from slamtec_aurora_sdk.utils import wait_for_map_data
        vig.marcar("sincronizar")
        t0 = time.monotonic()
        wait_for_map_data(sdk.data_provider, min_keyframes=10, min_sync_ratio=0.95,
                          max_wait_time=90.0)
        res["sincronizar_s"] = round(time.monotonic() - t0, 1)
        try:
            gi = sdk.data_provider.get_global_mapping_info()
            res["global"] = {k: gi.get(k) for k in ("total_kf_count", "total_kf_count_fetched",
                                                    "totalMapCount", "totalMPCount")}
        except Exception as e:                           # noqa: BLE001
            res["global"] = f"erro: {e}"
        print(f"sincronizar mapa: {res['sincronizar_s']} s; {res['global']}")
        for r_m in (0.05, 0.02):
            vig.marcar(f"grade_{r_m}")
            o = GridMapGenerationOptions()
            o.resolution = r_m
            o.map_canvas_width = 200.0
            o.map_canvas_height = 200.0
            o.active_map_only = 1
            o.height_range_specified = 1
            o.min_height = -0.5
            o.max_height = 2.0
            t0 = time.monotonic()
            gm = sdk.lidar_2d_map_builder.generate_fullmap_ondemand(
                o, wait_for_data_sync=True, timeout_ms=120000)
            d = gm.get_map_dimension()
            res[f"grade_{r_m}_s"] = round(time.monotonic() - t0, 1)
            res[f"grade_{r_m}_m"] = [round(d.max_x - d.min_x, 2), round(d.max_y - d.min_y, 2)]
            print(f"grade {r_m} m: {res[f'grade_{r_m}_s']} s, {res[f'grade_{r_m}_m']} m")

        # 4. keyframes
        vig.marcar("keyframes")
        t0 = time.monotonic()
        md = sdk.data_provider.get_map_data(fetch_kf=True, fetch_mp=False, fetch_mapinfo=True)
        res["keyframes_s"] = round(time.monotonic() - t0, 1)
        kfs = md.get("keyframes") or []
        res["keyframes"] = len(kfs)
        res["loop_closures"] = len(md.get("loop_closures") or [])
        if kfs:
            res["kf_campos"] = sorted(kfs[0].keys())
            res["kf_exemplos"] = [{k: (v if not isinstance(v, (list, tuple)) else list(v)[:7])
                                   for k, v in kf.items()} for kf in kfs[:3]]
        print(f"keyframes: {len(kfs)} em {res['keyframes_s']} s; loop closures: "
              f"{res['loop_closures']}; campos: {res.get('kf_campos')}")
        for e in res.get("kf_exemplos", []):
            print("  ", e)
        vig.marcar("fim"); time.sleep(2)
    finally:
        vig.parar = True
        try:
            sdk.enable_map_data_syncing(False)
        except Exception:                                # noqa: BLE001
            pass
        sdk.disconnect()

    res["pose_por_fase"] = vig.por_fase
    print("\npose por fase (10 Hz):")
    for f, v in vig.por_fase.items():
        print(f"  {f:18s} consultas {v['consultas']:4d}  erros {v['erros']}  "
              f"consulta máx {v['consulta_max_ms']:6.1f} ms  sem pose nova máx "
              f"{v['sem_pose_nova_max_ms']:7.1f} ms")
    with open(os.path.join(args.saida, "resultado.json"), "w", encoding="utf-8") as f:
        json.dump(res, f, indent=1, ensure_ascii=False, default=str)
    print(f"\ngravado: {args.saida}/resultado.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
