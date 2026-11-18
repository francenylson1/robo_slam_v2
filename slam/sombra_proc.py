"""
slam/sombra_proc.py
O LOCALIZADOR C1 AO VIVO, num processo à parte (17/11/2026, robô 2).

O Rastreador (slam/sombra.py) é numpy em laço Python: no processo do serviço
ele disputaria o GIL com o loop de 50 Hz. Aqui ele roda num processo filho;
o serviço só entrega as voltas e lê a última pose.

ETAPA "AO LADO" (decidida com o professor em 17/11): a pose calculada aparece
como um FANTASMA no /mapa e na telemetria ("sombra"). Ela NÃO é a fonte de
pose da missão (o robô sem Aurora continua com NullPoseSource): nada aqui move
o robô, nada aqui vale para a missão. Primeiro se confere com a trena.

FLUXO
  bumper (thread do C1 de baixo) → offer(scan) → fila (1 lugar: se o filho
  ainda calcula a anterior, a volta nova é descartada — sempre a mais fresca)
  → filho: Rastreador.passo(baixo, yaw do BNO, volta do C1 de cima)
  → fila de saída → thread leitora → ultima() / health().

SEMEADURA: o robô sem Aurora não sabe onde está ao ligar. "Localizar na fita"
(painel ou partida do serviço) põe a semente na FITA do ambiente e faz as
primeiras voltas com busca larga (±20 cm, ±8°): a fita do robô 1 não é
exatamente onde o robô 2 para (medido em 17/11: ~6 cm).
"""

import collections
import contextlib
import logging
import math
import multiprocessing as mp
import os
import queue
import sys
import threading
import time

log = logging.getLogger(__name__)

LARGA_M, LARGA_DEG, LARGA_VOLTAS = 0.20, 8.0, 3
BUSCA_M, BUSCA_DEG = 0.15, 4.0


@contextlib.contextmanager
def _sem_main():
    """O "spawn" reexecuta o arquivo do __main__ no filho (como __mp_main__).
    O main.py do serviço cria os motores no nível do módulo: em 18/11/2026, no
    robô 2, o filho chegou a MotorDriver() e só não pegou os pinos porque o
    serviço já os tinha. Escondendo __file__/__spec__ do __main__ durante o
    start(), o filho nasce só com este módulo."""
    m = sys.modules.get("__main__")
    guardado = {k: m.__dict__[k] for k in ("__file__", "__spec__") if m and k in m.__dict__}
    try:
        for k in guardado:
            setattr(m, k, None)
        yield
    finally:
        for k, v in guardado.items():
            setattr(m, k, v)


def _filho(pacote_dir, q_in, q_out, busca_m=BUSCA_M):
    """O processo do localizador. Só cálculo: sem pinos, sem serial."""
    # (__mp_main__ sempre existe no filho; o que denuncia é o __main__ ter arquivo.)
    if (getattr(sys.modules.get("__main__"), "__file__", None) is not None
            or "core.motor_driver" in sys.modules):
        q_out.put(("erro", "o processo do localizador carregou o serviço — recusado"))
        return
    import numpy as np
    from slam.sombra import Rastreador, carregar_grade
    g22 = carregar_grade(os.path.join(pacote_dir, "c1_22"))
    g143 = carregar_grade(os.path.join(pacote_dir, "c1_143"))
    if g22 is None:
        q_out.put(("erro", "o ambiente não tem o mapa do C1 de 22 cm"))
        return
    rs = Rastreador(g22, g143, busca_m=busca_m, busca_deg=BUSCA_DEG)
    q_out.put(("pronto", "22 cm" + (" + 1,43 m" if g143 is not None else "")))
    larga = 0
    while True:
        msg = q_in.get()
        if msg[0] == "fim":
            return
        if msg[0] == "semear":
            _, x, y, r = msg
            rs.semear(x, y, r, None)
            larga = LARGA_VOLTAS
            continue
        if msg[0] != "volta" or rs.pose is None:
            continue
        _, t, yaw, ang, dist, topo, centro = msg
        if larga:
            rs.busca_m, rs.busca_deg = LARGA_M, LARGA_DEG
        t0 = time.perf_counter()
        x, y, r, enc, perdido = rs.passo(np.asarray(ang), np.asarray(dist), yaw, topo, centro)
        ms = (time.perf_counter() - t0) * 1000.0
        if larga:
            larga -= 1
            if not larga:
                rs.busca_m, rs.busca_deg = busca_m, BUSCA_DEG
        try:
            q_out.put_nowait(("pose", t, x, y, r, enc, bool(perdido), rs.perdas, ms))
        except queue.Full:
            pass


def volta_do_scan(scan):
    """[(q, ângulo°, mm)] do C1 → (ângulos°, metros) para o Rastreador."""
    ang, dist = [], []
    for _, a, d in scan:
        if d > 0:
            ang.append(a % 360.0)
            dist.append(d / 1000.0)
    return ang, dist


def volta_do_topo(v):
    """{"p": [[ang×100, mm], ...]} do C1Topo → (ângulos°, metros), ou None."""
    if not v or not v.get("p"):
        return None
    return ([p[0] / 100.0 for p in v["p"]], [p[1] / 1000.0 for p in v["p"]])


class SombraAoVivo:

    def __init__(self, pacote_dir, fita_centro, yaw_fn=None, topo_fn=None,
                 clock=time.monotonic, busca_m=BUSCA_M):
        # busca_m: ±0,15 m entre voltas a ~7/s; o harness usa a coleta de 1/s (0,35).
        self.busca_m = busca_m
        self.pacote_dir = pacote_dir
        self.fita = tuple(fita_centro) if fita_centro else None
        self._yaw_fn, self._topo_fn, self._clock = yaw_fn, topo_fn, clock
        self._ctx = mp.get_context("spawn")      # sem herdar threads nem pinos do serviço
        self._q_in = self._ctx.Queue(maxsize=1)
        self._q_out = self._ctx.Queue(maxsize=50)
        self._proc = None
        self._leitora = None
        self._rodando = False
        self._lock = threading.Lock()
        self._ultima = None          # (t_chegada, x, y, rumo, encaixe, perdido)
        self.perdas = 0
        self.ms = None
        self.voltas = 0
        self.descartadas = 0
        self.mapas = None
        self.erro = None
        self.semeado_em = None
        # Ganchos da fonte de pose C1 (sensors/pose_c1.py, 18/11/2026): chamados
        # na thread leitora a cada pose, e depois de cada semeadura.
        self.on_pose = None          # (t_da_volta, x, y, rumo, encaixe, perdido, yaw_do_meio)
        self.on_semeou = None
        self.previsao_fn = None      # () → (x, y) da fusão, ou None: centro da busca
        self._yaw_ant = None
        self._yaw_meio = collections.deque(maxlen=50)   # (t da volta, BNO do meio dela)

    @property
    def disponivel(self) -> bool:
        return (self.fita is not None and
                os.path.isfile(os.path.join(self.pacote_dir or "", "c1_22.png")))

    # ─── ciclo de vida ───────────────────────────────
    def start(self, semear=True):
        if not self.disponivel:
            self.erro = ("sem fita no ambiente" if self.fita is None
                         else "o ambiente não tem os mapas dos C1")
            log.warning(f"[Sombra] Localizador C1 não sobe: {self.erro}.")
            return False
        self._proc = self._ctx.Process(target=_filho, name="LocalizadorC1", daemon=True,
                                       args=(self.pacote_dir, self._q_in, self._q_out, self.busca_m))
        with _sem_main():
            self._proc.start()
        self._rodando = True
        self._leitora = threading.Thread(target=self._ler, daemon=True, name="SombraLeitora")
        self._leitora.start()
        log.info(f"[Sombra] Localizador C1 ao vivo (ao lado, não move o robô) — "
                 f"pacote {os.path.basename(self.pacote_dir)}.")
        if semear:
            self.semear_fita()
        return True

    def stop(self):
        self._rodando = False
        if self._proc is not None and self._proc.is_alive():
            try:
                self._q_in.put(("fim",), timeout=0.5)
            except Exception:
                pass
            self._proc.join(timeout=2.0)
            if self._proc.is_alive():
                self._proc.terminate()

    # ─── lado do serviço ─────────────────────────────
    def semear_fita(self):
        """'Localizar na fita (C1)': o robô está parado sobre a fita."""
        if self.fita is None or self._proc is None:
            return False, "localizador C1 desligado"
        self._entregar(("semear", *self.fita), esperar=True)
        with self._lock:
            self._ultima, self.semeado_em = None, self._clock()
        if self.on_semeou is not None:
            try:
                self.on_semeou()
            except Exception as e:
                log.warning(f"[Sombra] on_semeou falhou: {e}")
        return True, "semeado na fita — as próximas voltas acham o lugar exato"

    def offer(self, scan):
        """Chamado pela thread do C1 de baixo a cada volta. Nunca bloqueia."""
        if not self._rodando:
            return
        try:
            yaw = self._yaw_fn() if self._yaw_fn else None
        except Exception:
            yaw = None
        try:
            topo = volta_do_topo(self._topo_fn()) if self._topo_fn else None
        except Exception:
            topo = None
        ang, dist = volta_do_scan(scan)
        if len(ang) < 20:
            return
        t = self._clock()
        # BNO do MEIO da volta (18/11/2026): a pose é a "foto" da volta inteira
        # (~140 ms); comparar com o BNO do fim deixava o rumo 0,12–0,15 s
        # atrasado e o vigia do giro disparava girando. Meio = média do BNO
        # desta entrega com o da anterior (o fim da volta anterior é o começo desta).
        ant, self._yaw_ant = self._yaw_ant, yaw
        meio = yaw
        if yaw is not None and ant is not None:
            meio = (ant + ((yaw - ant + 180.0) % 360.0 - 180.0) / 2.0 + 180.0) % 360.0 - 180.0
        self._yaw_meio.append((t, meio))
        try:
            centro = self.previsao_fn() if self.previsao_fn else None
        except Exception:
            centro = None
        self._entregar(("volta", t, yaw, ang, dist, topo, centro))

    def _entregar(self, msg, esperar=False):
        try:
            if esperar:
                self._q_in.put(msg, timeout=1.0)
            else:
                self._q_in.put_nowait(msg)
                self.voltas += 1
        except queue.Full:
            self.descartadas += 1

    def _ler(self):
        while self._rodando:
            try:
                m = self._q_out.get(timeout=0.5)
            except queue.Empty:
                if self._proc is not None and not self._proc.is_alive() and self._rodando:
                    self.erro = self.erro or "o processo do localizador parou"
                continue
            except (EOFError, OSError):
                return
            if m[0] == "pronto":
                self.mapas = m[1]
            elif m[0] == "erro":
                self.erro = m[1]
                log.warning(f"[Sombra] {m[1]}")
            elif m[0] == "pose":
                _, t, x, y, r, enc, perdido, perdas, ms = m
                with self._lock:
                    self._ultima = (self._clock(), x, y, r, enc, perdido)
                    self.perdas, self.ms = perdas, ms
                if self.on_pose is not None:
                    yaw_meio = next((ym for tv, ym in reversed(self._yaw_meio) if tv == t), None)
                    try:
                        self.on_pose(t, x, y, r, enc, perdido, yaw_meio)
                    except Exception as e:
                        log.warning(f"[Sombra] on_pose falhou: {e}")

    # ─── leitura ─────────────────────────────────────
    def ultima(self):
        with self._lock:
            return self._ultima

    def health(self) -> dict:
        u = self.ultima()
        h = {"ligado": self._rodando and self.erro is None, "mapas": self.mapas,
             "erro": self.erro, "perdas": self.perdas,
             "ms": None if self.ms is None else round(self.ms, 1),
             "voltas": self.voltas, "descartadas": self.descartadas}
        if u is None:
            h.update(tem_pose=False,
                     motivo=self.erro or ("esperando as voltas do C1" if self.semeado_em
                                          else "não localizado — use Localizar na fita (C1)"))
            return h
        idade = self._clock() - u[0]
        h.update(tem_pose=True, x_cm=round(u[1] * 100, 1), y_cm=round(u[2] * 100, 1),
                 rumo_deg=round((u[3] + 180.0) % 360.0 - 180.0, 1), encaixe=u[4],
                 perdido=u[5], idade_s=round(idade, 2),
                 motivo=("perdido — encaixe baixo ou salto; volte à fita e localize"
                         if u[5] else ("velha" if idade > 1.0 else "")))
        return h


_ = math
