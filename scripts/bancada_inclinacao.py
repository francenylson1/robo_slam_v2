#!/usr/bin/env python3
"""
scripts/bancada_inclinacao.py
Quanto o robô INCLINA e BALANÇA — a medida do "antes" e do "depois" da base
nova (05/10/2026).

Por quê: a base nova troca 4 rodízios rígidos por 2 com mola e o corpo passa a
ficar em 3 montantes soldados. O professor vê o corpo "balançando muito"; com
molas, o robô também vai cabecear um pouco na freada. Sem um número de antes,
"ficou melhor" vira opinião. Dois sensores, gravados juntos:
  - Aurora, no TOPO (~1,45 m): roll/pitch da pose a ~10 Hz — o que o corpo faz;
  - BNO085, onde estiver montado: pitch/roll do quadro RVC a 100 Hz (o
    serviço só usa o yaw; aqui o quadro inteiro é decodificado).
Os eixos de cada sensor dependem de como ele está montado: o relatório mostra
os dois ângulos de cada um, e a freada diz qual é o de frente-trás.

TESTES:
  PARADO  nenhum motor. Grava --duracao s; o professor empurra o TOPO e solta
          (de lado e de frente), com intervalos. Mede cada balanço: quanto
          inclinou, em que frequência oscila e quanto demora para assentar.
  FREADA  reta a --pct (12% = ~21,7 cm/s) por --tempo s e stop(), como a
          missão para; grava 3 s depois. Sem correção de rumo (o BNO aqui é só
          medida, e pode faltar: 1,5 s de reta não precisa dele). Repete --rep vezes (o robô anda
          ~33 cm por vez: ~1,5 m livres à frente). Bumper do C1 fail-closed:
          frente bloqueada → não sai ou para na hora.

SEGURANÇA: só com os serviços parados (o rosto religa o frota-robo, e o serviço
é o único cliente do Aurora e dono da UART do BNO); força entre 8% e o teto da
missão; tempo de reta ≤ 2 s; SIGINT/SIGTERM param; stop() num finally.

ANTES:  sudo systemctl stop frota-rosto frota-robo   (e conferir os dois)
USO:    .venv/bin/python scripts/bancada_inclinacao.py --teste PARADO --duracao 40
        .venv/bin/python scripts/bancada_inclinacao.py --teste FREADA --rep 3
DEPOIS: sudo systemctl start frota-robo frota-rosto   + "Localizar na fita"
"""

import argparse
import csv
import math
import os
import signal
import statistics
import sys
import time

_RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _RAIZ)

PASTA = os.path.join(_RAIZ, "data", "inclinacao")
TEMPO_MAXIMO_RETA_S = 2.0
LIMIAR_EVENTO_DEG = 0.3      # desvio que conta como "balançou"
LIMIAR_ASSENTOU_DEG = 0.15   # dentro disto, "assentou"
_motors = None


def _parar_tudo(*_):
    if _motors is not None:
        try:
            _motors.stop()
        except Exception:
            pass
    sys.exit(1)


# ─────────────────────────────────────────
# ANÁLISE (pura — sem hardware)
# ─────────────────────────────────────────
def linha_base(amostras, t_ini, t_fim):
    """Mediana do sinal numa janela parada. amostras: [(t, valor)]."""
    v = [x for t, x in amostras if t_ini <= t <= t_fim]
    return statistics.median(v) if v else None


def resposta(amostras, base, t_ini, t_fim):
    """Como o sinal se comportou em [t_ini, t_fim] em relação à base.
    Devolve pico (graus, com sinal), pico-a-pico, frequência da oscilação
    (cruzamentos da base depois do pico) e o tempo até assentar."""
    jan = [(t, x - base) for t, x in amostras if t_ini <= t <= t_fim]
    if len(jan) < 3:
        return None
    t_pico, pico = max(jan, key=lambda p: abs(p[1]))
    dev = [d for _, d in jan]
    cruz = []
    depois = [(t, d) for t, d in jan if t >= t_pico]
    for (t0, d0), (t1, d1) in zip(depois, depois[1:]):
        if d0 == 0 or (d0 > 0) != (d1 > 0):
            cruz.append(t0 + (t1 - t0) * (abs(d0) / (abs(d0) + abs(d1) or 1)))
    freq = None
    if len(cruz) >= 3:
        freq = (len(cruz) - 1) / (2.0 * (cruz[-1] - cruz[0]))
    fora = [t for t, d in jan if abs(d) > LIMIAR_ASSENTOU_DEG]
    assentou = (fora[-1] - t_ini) if fora else 0.0
    return {"pico": pico, "pp": max(dev) - min(dev), "freq_hz": freq,
            "assentou_s": assentou, "t_pico": t_pico}


def eventos(amostras, base, separacao_s=1.5):
    """Trechos em que o desvio passa de LIMIAR_EVENTO_DEG (empurrões)."""
    ev, ini, ult = [], None, None
    for t, x in amostras:
        if abs(x - base) > LIMIAR_EVENTO_DEG:
            if ini is None or t - ult > separacao_s:
                if ini is not None:
                    ev.append((ini, ult))
                ini = t
            ult = t
    if ini is not None:
        ev.append((ini, ult))
    return ev


def fmt(r):
    if r is None:
        return "sem dados"
    f = f"{r['freq_hz']:.1f} Hz" if r["freq_hz"] else "sem oscilação clara"
    return (f"pico {r['pico']:+.2f}° · pico-a-pico {r['pp']:.2f}° · {f} · "
            f"assentou em {r['assentou_s']:.1f} s")


# ─────────────────────────────────────────
# SENSORES
# ─────────────────────────────────────────
def _bno_com_inclinacao():
    from sensors.heading_lock import HeadingLock

    class BNOInclinacao(HeadingLock):
        """O mesmo leitor do serviço; só guarda também pitch/roll/aceleração."""
        def __init__(self):
            super().__init__()
            self.amostras = []      # (t, yaw, pitch, roll, ax_mg, ay_mg, az_mg)

        def parse_rvc_frame(self, frame):
            yaw = HeadingLock.parse_rvc_frame(frame)
            if yaw is not None:
                i16 = [int.from_bytes(frame[k:k + 2], "little", signed=True)
                       for k in range(3, 15, 2)]
                self.amostras.append((time.monotonic(), i16[0] / 100.0,
                                      i16[1] / 100.0, i16[2] / 100.0,
                                      i16[3], i16[4], i16[5]))
            return yaw

    return BNOInclinacao()


class Gravador:
    def __init__(self, sdk, bno):
        self.sdk, self.bno = sdk, bno
        self.aurora = []            # (t, roll, pitch, yaw) em graus
        self.marcas = []            # (t, texto)
        self._ult_ts = None

    def coleta(self):
        try:
            pos, rpy, ts = self.sdk.data_provider.get_current_pose(use_se3=False)
        except Exception:
            return
        if ts != self._ult_ts:
            self._ult_ts = ts
            self.aurora.append((time.monotonic(), math.degrees(rpy[0]),
                                math.degrees(rpy[1]), math.degrees(rpy[2])))

    def esperar(self, s):
        fim = time.monotonic() + s
        while time.monotonic() < fim:
            self.coleta()
            time.sleep(0.03)

    def marca(self, texto):
        self.marcas.append((time.monotonic(), texto))

    def canais(self):
        a, b = self.aurora, self.bno.amostras
        return {"Aurora roll": [(t, r) for t, r, _, _ in a],
                "Aurora pitch": [(t, p) for t, _, p, _ in a],
                "BNO pitch": [(s[0], s[2]) for s in b],
                "BNO roll": [(s[0], s[3]) for s in b]}

    def salvar(self, nome):
        os.makedirs(PASTA, exist_ok=True)
        carimbo = time.strftime("%Y%m%d_%H%M%S")
        base = os.path.join(PASTA, f"{nome}_{carimbo}")
        with open(base + "_aurora.csv", "w", newline="") as fh:
            w = csv.writer(fh)
            w.writerow(["t_s", "roll_graus", "pitch_graus", "yaw_graus"])
            w.writerows(self.aurora)
        with open(base + "_bno.csv", "w", newline="") as fh:
            w = csv.writer(fh)
            w.writerow(["t_s", "yaw", "pitch", "roll", "ax_mg", "ay_mg", "az_mg"])
            w.writerows(self.bno.amostras)
        with open(base + "_marcas.csv", "w", newline="") as fh:
            w = csv.writer(fh)
            w.writerow(["t_s", "marca"])
            w.writerows(self.marcas)
        return base


# ─────────────────────────────────────────
# TESTES
# ─────────────────────────────────────────
def teste_parado(g, duracao):
    print(f"\nPARADO: gravando {duracao:.0f} s. Empurre o TOPO e solte, de lado e "
          f"de frente, com ~5 s entre um e outro.")
    t0 = time.monotonic()
    g.marca("inicio")
    g.esperar(duracao)
    g.marca("fim")
    for nome, s in g.canais().items():
        base = linha_base(s, t0, t0 + 2.0)
        if base is None:
            print(f"  {nome}: sem dados")
            continue
        ev = eventos(s, base)
        print(f"  {nome}: base {base:+.2f}° · {len(ev)} balanço(s)")
        for k, (a, b) in enumerate(ev, 1):
            print(f"    #{k} em {a - t0:5.1f} s: {fmt(resposta(s, base, a - 0.2, b + 1.0))}")


def teste_freada(g, motors, bumper, pct, tempo, rep, espera):
    for k in range(1, rep + 1):
        print(f"\nFREADA {k}/{rep}: reta a {pct}% por {tempo} s. Saia da frente: {espera:.0f} s.")
        t_parado = time.monotonic()
        g.esperar(espera)
        if bumper.blocked_front:
            print("  frente BLOQUEADA (ou C1 sem dado) — nada foi comandado.")
            return
        g.marca(f"partida_{k}")
        t_part = time.monotonic()
        motivo = "tempo"
        while time.monotonic() - t_part < tempo:
            if bumper.blocked_front:
                motivo = "bumper"
                break
            motors.set_speed(pct, pct)
            g.coleta()
            time.sleep(0.02)
        motors.stop()
        t_stop = time.monotonic()
        g.marca(f"stop_{k}_{motivo}")
        g.esperar(3.0)
        print(f"  parou por {motivo} após {t_stop - t_part:.2f} s")
        bno = g.bno.amostras
        ax = [s[4] for s in bno if t_stop - 0.1 <= s[0] <= t_stop + 0.8]
        if ax:
            print(f"  aceleração no BNO na freada: {min(ax)} a {max(ax)} mg (eixo X do sensor)")
        for nome, s in g.canais().items():
            base = linha_base(s, t_parado + 0.5, t_part - 0.1)
            if base is None:
                print(f"  {nome}: sem dados")
                continue
            print(f"  {nome}: partida {fmt(resposta(s, base, t_part, t_part + 1.0))}")
            print(f"  {' ' * len(nome)}  freada  {fmt(resposta(s, base, t_stop, t_stop + 3.0))}")


def main() -> int:
    global _motors
    from config.settings import AURORA_IP, MISSAO_TETO_PCT, MISSAO_RETO_PCT
    from sensors.aurora_cliente_unico import exigir_servico_parado

    ap = argparse.ArgumentParser(description="Inclinação e balanço do robô.")
    ap.add_argument("--teste", choices=["PARADO", "FREADA"], required=True)
    ap.add_argument("--duracao", type=float, default=40.0, help="PARADO: segundos")
    ap.add_argument("--pct", type=float, default=MISSAO_RETO_PCT)
    ap.add_argument("--tempo", type=float, default=1.5, help="FREADA: s de reta")
    ap.add_argument("--rep", type=int, default=3)
    ap.add_argument("--espera", type=float, default=5.0)
    a = ap.parse_args()

    if os.system("systemctl is-active --quiet frota-rosto") == 0:
        print("RECUSADO: pare os serviços antes (o rosto religa o frota-robo):\n"
              "  sudo systemctl stop frota-rosto frota-robo")
        return 2
    exigir_servico_parado()
    if a.teste == "FREADA":
        if not (8.0 <= a.pct <= MISSAO_TETO_PCT):
            print(f"RECUSADO: força {a.pct}% fora de 8–{MISSAO_TETO_PCT}%.")
            return 2
        if not (0.3 <= a.tempo <= TEMPO_MAXIMO_RETA_S) or not (1 <= a.rep <= 5):
            print(f"RECUSADO: --tempo entre 0,3 e {TEMPO_MAXIMO_RETA_S} s; --rep entre 1 e 5.")
            return 2
    if not (5.0 <= a.duracao <= 180.0):
        print("RECUSADO: --duracao entre 5 e 180 s.")
        return 2

    signal.signal(signal.SIGINT, _parar_tudo)
    signal.signal(signal.SIGTERM, _parar_tudo)

    from slamtec_aurora_sdk import AuroraSDK
    sdk = AuroraSDK()
    sdk.connect(connection_string=AURORA_IP)
    time.sleep(1.0)                                # o 1º segundo traz (0,0,0) e saltos
    bno = _bno_com_inclinacao()
    bno.start()
    motors = bumper = None
    g = Gravador(sdk, bno)
    try:
        for _ in range(50):
            if bno.healthy:
                break
            time.sleep(0.2)
        if not bno.healthy:
            print("BNO085 sem leitura — seguindo só com o Aurora.")
        if a.teste == "PARADO":
            teste_parado(g, a.duracao)
        else:
            from core.motor_driver import MotorDriver
            from sensors.safety_bumper import SafetyBumper
            bumper = SafetyBumper()
            bumper.start()
            _motors = motors = MotorDriver()
            teste_freada(g, motors, bumper, a.pct, a.tempo, a.rep, a.espera)
        print(f"\nAurora: {len(g.aurora)} poses · BNO: {len(bno.amostras)} quadros")
        print(f"dados: {g.salvar(a.teste.lower())}_*.csv")
        return 0
    finally:
        if motors is not None:
            motors.stop()
            try:
                motors.cleanup()
            except Exception:
                pass
        if bumper is not None:
            bumper.stop()
        bno.stop()
        for fn in ("disconnect", "release"):
            try:
                getattr(sdk, fn)()
            except Exception:
                pass


if __name__ == "__main__":
    sys.exit(main())
