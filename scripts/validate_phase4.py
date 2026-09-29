#!/usr/bin/env python3
"""
scripts/validate_phase4.py
Gate da Fase 4 (parte de SOFTWARE), em MOCK — começa pela POSE DO AURORA.

Prova, sem Aurora e sem robô, o desenho decidido com o professor em 29/09/2026
(fim de docs/FASE4_ARQUITETURA_FROTA.md):

  1. as seis regras que dizem quando a pose VALE (sensors/pose_source.py);
  2. a thread do Aurora e a PARTIDA (zerar → carregar → relocalizar → fita)
     contra um Aurora de mentira que erra de todos os jeitos que já vimos:
     status velho, relocalização no lugar errado, robô que anda no meio,
     mapa trocado, rastreio perdido, cabo puxado;
  3. o robô SEM Aurora fica exatamente como era;
  4. o gravador de varreduras ganha a pose sem mudar o resto;
  5. a rota da partida exige login, e a telemetria leva a pose;
  6. os scripts de bancada se recusam a ser um segundo cliente.

A parte FÍSICA (pose no dashboard, empurrão de 3 m, desligar o Aurora, 1 h
ligado com o cabo puxado) é da bancada.
"""

import json
import math
import os
import sys
import tempfile
import threading
import time

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

os.environ["FROTA_MOCK"] = "1"
os.environ["FROTA_WEB_AUTH"] = "1"
os.environ["FROTA_WEB_USER"] = "operador"
_SENHA = "senha-do-harness-fase4"
from werkzeug.security import generate_password_hash   # noqa: E402
os.environ["FROTA_WEB_PASSWORD_HASH"] = generate_password_hash(_SENHA)

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

import config.settings as S                                   # noqa: E402
from sensors.pose_source import (Pose, PoseValidator,         # noqa: E402
                                 NullPoseSource, normaliza_graus)
from sensors.aurora_pose import (AuroraPose, sha256_arquivo,   # noqa: E402
                                 ST_INICIALIZADO, ST_MAPA_CARREGADO,
                                 ST_RELOC_OK, ST_RELOC_FALHOU,
                                 ST_TRACKING_PERDIDO, ST_TRACKING_RECUPERADO,
                                 ST_MAPA_ZERADO)
from sensors.scan_recorder import ScanRecorder                # noqa: E402

_USE_COLOR = sys.stdout.isatty() and os.name != "nt"
GREEN = "\033[92m" if _USE_COLOR else ""
RED   = "\033[91m" if _USE_COLOR else ""
BOLD  = "\033[1m"  if _USE_COLOR else ""
RESET = "\033[0m"  if _USE_COLOR else ""

_results = []


def check(name: str, ok: bool, detail: str = ""):
    _results.append((name, bool(ok), detail))
    marca = f"{GREEN}[PASS]{RESET}" if ok else f"{RED}[FALHA]{RESET}"
    print(f"  {marca} {name}" + (f"  — {detail}" if detail else ""))


def section(titulo: str):
    print(f"\n{BOLD}{titulo}{RESET}")


FX, FY, FR = S.AURORA_FITA


class Relogio:
    """Relógio de mentira: o harness avança o tempo sem esperar."""
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t

    def anda(self, s):
        self.t += s


def validador(clock):
    return PoseValidator(
        fita=S.AURORA_FITA, fita_tol_m=S.AURORA_FITA_TOL_M,
        fita_tol_deg=S.AURORA_FITA_TOL_DEG, max_idade_s=S.POSE_MAX_IDADE_S,
        salto_m=S.POSE_SALTO_M, salto_deg=S.POSE_SALTO_DEG,
        estavel_s=S.POSE_ESTAVEL_S, aquecimento_s=S.POSE_AQUECIMENTO_S,
        clock=clock)


# ─────────────────────────────────────────────
def test_regras():
    section("1. As regras — quando a pose VALE (relógio de mentira)")
    c = Relogio()
    v = validador(c)

    check("Antes de conectar: não vale ('desconectado')",
          v.avaliar()[1] == "desconectado")

    v.on_conectou()
    v.on_pose(Pose(0.0, 0.0, 0.0, c()))          # o (0,0,0) do 1º segundo
    check("Regra 5: no 1º segundo após conectar não vale ('aquecendo')",
          v.avaliar()[0] is None and "aquecendo" in v.avaliar()[1])
    check("Regra 5: a leitura do 1º segundo nem entra (não vira 'última')",
          v.ultima() is None)

    c.anda(1.1)
    v.on_pose(Pose(FX, FY, FR, c()))
    check("Regra 1: conectado e lendo, mas sem a partida → não vale",
          v.avaliar()[0] is None and "fita" in v.avaliar()[1],
          v.avaliar()[1])

    ok, msg = v.on_localizou(Pose(FX + 0.20, FY, FR, c()))
    check("Regra 2: relocalizou a 20 cm da fita → RECUSADO",
          not ok and "fora da fita" in msg, msg)
    ok, msg = v.on_localizou(Pose(FX, FY, FR + 6.0, c()))
    check("Regra 2: relocalizou 6° torto → RECUSADO", not ok, msg)
    ok, msg = v.on_localizou(Pose(FX + 0.10, FY - 0.05, FR - 4.0, c()))
    check("Regra 2: 11 cm e 4° da fita → aceito (dentro de 15 cm / 5°)", ok, msg)
    check("Depois da partida certa, a pose vale", v.avaliar()[0] is not None)

    # Regra 2 perto de ±180°: a diferença tem que dar a volta certa.
    v2 = validador(c)
    v2.fita = (0.0, 0.0, 179.0)
    v2.on_conectou()
    c.anda(1.1)
    check("Regra 2: fita a 179° e pose a −178° são 3° (dá a volta no 180)",
          v2.on_localizou(Pose(0.0, 0.0, -178.0, c()))[0])

    # O relógio andou no sub-teste acima: uma leitura nova antes da regra 3.
    v.on_pose(Pose(FX + 0.10, FY - 0.05, FR - 4.0, c()))
    c.anda(0.25)
    check("Regra 3: leitura de 0,25 s vale no assistivo (0,5 s)",
          v.avaliar()[0] is not None)
    check("Regra 3: a mesma leitura vale na missão (0,3 s)",
          v.avaliar(S.POSE_MAX_IDADE_MISSAO_S)[0] is not None)
    c.anda(0.1)
    check("Regra 3: leitura de 0,35 s NÃO vale na missão",
          v.avaliar(S.POSE_MAX_IDADE_MISSAO_S)[0] is None,
          v.avaliar(S.POSE_MAX_IDADE_MISSAO_S)[1])
    c.anda(0.2)
    check("Regra 3: leitura de 0,55 s NÃO vale nem no assistivo",
          v.avaliar()[0] is None and "velha" in v.avaliar()[1], v.avaliar()[1])

    # Movimento normal: 3 cm por leitura (30 cm/s a 10 Hz) não é salto.
    x = FX + 0.10
    for _ in range(20):
        c.anda(0.1)
        x += 0.03
        v.on_pose(Pose(x, FY, FR, c()))
    check("Regra 4: andar 3 cm por leitura (30 cm/s) não conta como salto",
          v.saltos == 0 and v.avaliar()[0] is not None)

    c.anda(0.1)
    v.on_pose(Pose(x + 0.30, FY, FR, c()))
    check("Regra 4: salto de 30 cm → não vale ('instável')",
          v.avaliar()[0] is None and "instável" in v.avaliar()[1])
    for _ in range(9):
        c.anda(0.1)
        v.on_pose(Pose(x + 0.30, FY, FR, c()))
    check("Regra 4: 0,9 s depois do salto ainda não vale",
          v.avaliar()[0] is None)
    c.anda(0.15)
    v.on_pose(Pose(x + 0.30, FY, FR, c()))
    check("Regra 4: 1 s estável depois do salto → volta a valer",
          v.avaliar()[0] is not None)

    c.anda(0.1)
    v.on_pose(Pose(x + 0.30, FY, FR + 16.0, c()))
    check("Regra 4: giro de 16° numa leitura também é salto",
          v.avaliar()[0] is None and v.saltos == 2)
    c.anda(1.1)
    v.on_pose(Pose(x + 0.30, FY, FR + 16.0, c()))

    v.on_pose(Pose(x + 0.30, FY, 179.5, c()))
    c.anda(1.1)
    v.on_pose(Pose(x + 0.30, FY, 179.5, c()))
    antes = v.saltos
    c.anda(0.1)
    v.on_pose(Pose(x + 0.30, FY, -179.5, c()))
    check("Regra 4: rumo de 179,5° para −179,5° é 1°, não salto",
          v.saltos == antes)

    v.on_tracking(False)
    check("Regra 6: rastreio perdido → não vale",
          v.avaliar()[0] is None and v.avaliar()[1] == "rastreio perdido")
    v.on_tracking(True)
    check("Regra 6: recuperou → ainda espera 1 s estável",
          v.avaliar()[0] is None)
    c.anda(1.05)
    v.on_pose(Pose(x + 0.30, FY, -179.5, c()))
    check("Regra 6: 1 s depois de recuperar → vale", v.avaliar()[0] is not None)

    v.on_desconectou()
    v.on_conectou()
    c.anda(1.1)
    v.on_pose(Pose(x + 0.30, FY, -179.5, c()))
    check("Reconectar ZERA a localização: precisa da fita de novo",
          v.avaliar()[0] is None and "fita" in v.avaliar()[1])

    check("normaliza_graus(190) = −170 e normaliza_graus(−190) = 170",
          abs(normaliza_graus(190) + 170) < 1e-9
          and abs(normaliza_graus(-190) - 170) < 1e-9)


# ─────────────────────────────────────────────
# O AURORA DE MENTIRA
# ─────────────────────────────────────────────
class Mundo:
    """O que o Aurora de mentira sabe e como ele vai errar."""
    def __init__(self):
        self.lock = threading.Lock()
        self.x, self.y, self.rumo = 3.0, 2.0, 10.0   # longe da fita
        self.pose_ts = 0
        # Status VELHO guardado: uma relocalização de "ontem". Não pode valer.
        self.status, self.status_ts = ST_RELOC_OK, 1
        self.vivo = True
        self.falha_conexao = False
        self.reloc_resultado = ST_RELOC_OK
        self.reloc_pose = (FX + 0.02, FY - 0.01, FR + 0.5)
        self.reloc_canal = 2          # canal próprio: 2 = SUCCEED (de "ontem")
        self.upload_ok = True
        # O caso de 29/09 10:29: logo depois do 11 (e do 13) chega outro
        # evento, e o Aurora só guarda o último.
        self.sobrescreve = False
        self.conexoes = 0

    def evento(self, st):
        with self.lock:
            self.status, self.status_ts = st, self.status_ts + 1


class _Ctrl:
    def __init__(self, m):
        self.m = m

    def is_device_connection_alive(self):
        return self.m.vivo

    def require_map_reset(self, timeout_ms=10000):
        self.m.evento(ST_MAPA_ZERADO)
        self.m.x, self.m.y, self.m.rumo = 0.0, 0.0, 0.0
        self.m.evento(ST_INICIALIZADO)
        return True

    def require_relocalization(self, timeout_ms=5000):
        ok = self.m.reloc_resultado == ST_RELOC_OK
        if ok:
            self.m.x, self.m.y, self.m.rumo = self.m.reloc_pose
        self.m.reloc_canal = 2 if ok else 3
        self.m.evento(self.m.reloc_resultado)
        if self.m.sobrescreve:
            self.m.evento(6)          # MAP_UPDATED apaga o 13
        return ok

    def get_last_relocalization_status(self, timeout_ms=1000):
        return self.m.reloc_canal


class _Mapas:
    def __init__(self, m):
        self.m = m

    def upload_map(self, caminho, timeout_seconds=180):
        if not self.m.upload_ok:
            return False
        self.m.evento(ST_MAPA_CARREGADO)
        if self.m.sobrescreve:
            self.m.evento(6)          # MAP_UPDATED apaga o 11
        return True


class _Dados:
    def __init__(self, m):
        self.m = m

    def get_current_pose(self, use_se3=False):
        with self.m.lock:
            self.m.pose_ts += 1
            return ((self.m.x, self.m.y, 0.0),
                    (0.0, 0.0, math.radians(self.m.rumo)), self.m.pose_ts)

    def get_last_device_status(self):
        with self.m.lock:
            return self.m.status, self.m.status_ts


class FakeSDK:
    def __init__(self, m):
        self.m = m
        self.controller = _Ctrl(m)
        self.map_manager = _Mapas(m)
        self.data_provider = _Dados(m)

    def connect(self, connection_string=None):
        if self.m.falha_conexao:
            raise ConnectionError("Aurora desligado (de mentira)")
        self.m.conexoes += 1

    def disconnect(self):
        pass

    def release(self):
        pass


def esperar(cond, limite=5.0):
    fim = time.monotonic() + limite
    while time.monotonic() < fim:
        if cond():
            return True
        time.sleep(0.01)
    return False


def fonte(mundo, mapa, sha, **kw):
    v = PoseValidator(
        fita=S.AURORA_FITA, fita_tol_m=S.AURORA_FITA_TOL_M,
        fita_tol_deg=S.AURORA_FITA_TOL_DEG, max_idade_s=S.POSE_MAX_IDADE_S,
        salto_m=S.POSE_SALTO_M, salto_deg=S.POSE_SALTO_DEG,
        estavel_s=0.3, aquecimento_s=0.1)
    cfg = dict(ip="192.168.11.1", mapa=mapa, mapa_sha256=sha, validator=v,
               poll_s=0.01, backoff_s=(0.05,), partida_limite_s=1.0,
               espera_zerar_s=0.05, espera_mapa_s=0.05, mediana_s=0.1,
               status_mapa_s=0.3,
               sdk_factory=lambda: FakeSDK(mundo))
    cfg.update(kw)
    return AuroraPose(**cfg)


def fim_da_partida(a):
    return esperar(lambda: a.partida["passo"] is None
                   and a.partida["resultado"] is not None)


def test_aurora():
    section("2. A thread do Aurora e a PARTIDA (Aurora de mentira)")
    tmp = tempfile.mkdtemp(prefix="fase4_")
    mapa = os.path.join(tmp, "mapa.stcm")
    with open(mapa, "wb") as f:
        f.write(b"mapa de mentira")
    sha = sha256_arquivo(mapa)

    m = Mundo()
    a = fonte(m, mapa, sha)
    a.start()
    parado = {"v": True}
    parado_fn = lambda: parado["v"]      # noqa: E731
    try:
        check("Conecta sozinho", esperar(lambda: a.health()["conectado"]))
        time.sleep(0.2)
        h = a.health()
        check("Um status 13 VELHO, de antes de conectar, não valida a pose",
              not h["valida"] and "fita" in h["motivo"], h["motivo"])

        parado["v"] = False
        ok, msg = a.pedir_partida(parado_fn)
        check("Partida com o robô andando → recusada", not ok, msg)
        parado["v"] = True

        ok, msg = a.pedir_partida(parado_fn)
        ok2, msg2 = a.pedir_partida(parado_fn)
        check("Partida parado → aceita; um 2º pedido junto → recusado",
              ok and not ok2, f"{msg} / {msg2}")
        check("Partida termina VERDE", fim_da_partida(a)
              and a.partida["resultado"].startswith("ok"), a.partida["resultado"])
        check("Depois da partida a pose vale e fica na fita",
              esperar(lambda: a.health()["valida"])
              and abs(a.health()["x_cm"] - (FX + 0.02) * 100) < 1.0,
              f"x={a.health()['x_cm']} cm")
        check("pose_valida() entrega a Pose, e com 0,3 s (missão) também",
              a.pose_valida() is not None
              and a.pose_valida(S.POSE_MAX_IDADE_MISSAO_S) is not None)

        m.evento(ST_TRACKING_PERDIDO)
        check("Status 4 (rastreio perdido) → não vale",
              esperar(lambda: a.motivo() == "rastreio perdido"))
        m.evento(ST_TRACKING_RECUPERADO)
        check("Status 5 (recuperado) → volta a valer depois de estável",
              esperar(lambda: a.health()["valida"], 2.0))

        m.evento(ST_MAPA_ZERADO)
        check("Alguém zerou o mapa do Aurora fora da partida → não vale",
              esperar(lambda: "saiu do mapa" in a.motivo()), a.motivo())

        m.reloc_pose = (FX + 0.40, FY, FR)
        a.pedir_partida(parado_fn)
        check("Relocalizou a 40 cm da fita → partida FALHA e a pose não vale",
              fim_da_partida(a) and "fora da fita" in a.partida["resultado"]
              and not a.health()["valida"], a.partida["resultado"])
        m.reloc_pose = (FX, FY, FR)

        m.reloc_resultado = ST_RELOC_FALHOU
        a.pedir_partida(parado_fn)
        check("Relocalização falha (SDK devolve False, status 14) → partida FALHA",
              fim_da_partida(a) and a.partida["resultado"].startswith("falhou"),
              a.partida["resultado"])
        m.reloc_resultado = ST_RELOC_OK

        m.upload_ok = False
        a.pedir_partida(parado_fn)
        check("Upload do mapa devolve False → partida FALHA",
              fim_da_partida(a) and "recusou" in a.partida["resultado"],
              a.partida["resultado"])
        m.upload_ok = True

        # 29/09 10:29: o 11 e o 13 sobrescritos por um evento seguinte.
        m.sobrescreve = True
        a.pedir_partida(parado_fn)
        check("Status 11 e 13 sobrescritos por outro evento → partida VERDE "
              "(retorno do SDK + canal da relocalização + fita)",
              fim_da_partida(a) and a.partida["resultado"].startswith("ok"),
              a.partida["resultado"])
        m.sobrescreve = False

        # Robô empurrado no meio da sequência.
        chamadas = {"n": 0}

        def anda_no_meio():
            chamadas["n"] += 1
            return chamadas["n"] < 4
        a.pedir_partida(anda_no_meio)
        check("Robô andou no meio da partida → ABORTADA",
              fim_da_partida(a) and "andou" in a.partida["resultado"],
              a.partida["resultado"])

        a.pedir_partida(parado_fn)
        check("Depois de tudo isso, uma partida certa volta a dar VERDE",
              fim_da_partida(a) and a.partida["resultado"].startswith("ok")
              and esperar(lambda: a.health()["valida"]))

        # Cabo puxado.
        m.vivo = False
        check("Cabo puxado → desconecta e a pose não vale",
              esperar(lambda: not a.health()["conectado"])
              and not a.health()["valida"])
        m.vivo = True
        check("Cabo de volta → reconecta sozinho",
              esperar(lambda: a.health()["conectado"], 3.0))
        time.sleep(0.2)
        check("...mas a pose NÃO volta a valer sem a fita",
              not a.health()["valida"] and "fita" in a.motivo(), a.motivo())
        check("A reconexão aparece na telemetria", a.health()["reconexoes"] >= 1)

        h = a.health()
        chaves = {"fonte", "conectado", "valida", "motivo", "x_cm", "y_cm",
                  "rumo_deg", "idade_s", "partida"}
        check("health() tem os campos da decisão 7", chaves <= set(h),
              ", ".join(sorted(chaves - set(h))))
        json.dumps(h)
        check("health() vira JSON (vai para /api/status e para a Torre)", True)
    finally:
        t0 = time.monotonic()
        a.stop()
        check("stop() encerra a thread rápido", time.monotonic() - t0 < 1.0)

    # Mapa com outro sha.
    m2 = Mundo()
    b = fonte(m2, mapa, "0" * 64)
    b.start()
    try:
        esperar(lambda: b.health()["conectado"])
        b.pedir_partida(lambda: True)
        check("Mapa com sha diferente do combinado → partida RECUSADA",
              fim_da_partida(b) and "sha" in b.partida["resultado"],
              b.partida["resultado"])
        check("...e o Aurora nem foi zerado",
              m2.status == ST_RELOC_OK and m2.status_ts == 1)
    finally:
        b.stop()

    # Aurora desligado desde o início.
    m3 = Mundo()
    m3.falha_conexao = True
    c = fonte(m3, mapa, sha)
    c.start()
    try:
        time.sleep(0.3)
        h = c.health()
        check("Aurora desligado: o módulo não trava, só diz 'desconectado'",
              not h["conectado"] and h["motivo"] == "desconectado"
              and h["reconexoes"] >= 2)
        ok, msg = c.pedir_partida(lambda: True)
        check("Aurora desligado: a partida é recusada com o motivo",
              not ok and "desconectado" in msg, msg)
    finally:
        c.stop()


# ─────────────────────────────────────────────
def test_sem_aurora():
    section("3. Robô SEM Aurora (todos, menos o robô 1)")
    n = NullPoseSource()
    h = n.health()
    check("Sem fonte: pose_valida() é None e o motivo é 'sem fonte de pose'",
          n.pose_valida() is None and h["motivo"] == "sem fonte de pose"
          and h["fonte"] is None)
    check("Só o robô 1 tem Aurora (AURORA_ROBOTS)", tuple(S.AURORA_ROBOTS) == (1,))
    src = open(os.path.join(_ROOT, "main.py"), encoding="utf-8").read()
    check("main.py usa NullPoseSource fora de AURORA_ROBOTS (não conecta, não alarma)",
          "args.robot_id in AURORA_ROBOTS" in src and "NullPoseSource()" in src)


# ─────────────────────────────────────────────
def test_gravador():
    section("4. O gravador de varreduras ganha a pose")
    tmp = tempfile.mkdtemp(prefix="fase4_rec_")
    atual = {"p": Pose(1.234, -0.5, 90.0, time.monotonic())}
    rec = ScanRecorder(tmp, period_s=0.0, pose_fn=lambda: atual["p"])
    scan = [(15, 10.0, 1500.0), (15, 20.0, 1600.0)]
    rec.offer(scan)
    atual["p"] = None
    rec.offer(scan)
    reg1 = rec._q.get_nowait()
    reg2 = rec._q.get_nowait()
    check("Pose válida → \"pose\": [x_cm, y_cm, rumo, idade]",
          reg1["pose"][:3] == [123.4, -50.0, 90.0]
          and 0 <= reg1["pose"][3] < 1.0, str(reg1["pose"]))
    check("Pose inválida → \"pose\": null", reg2["pose"] is None)
    check("O resto da linha não mudou (t, yaw, mov, p)",
          {"t", "yaw", "mov", "p"} <= set(reg1) and len(reg1["p"]) == 2)

    def explode():
        raise RuntimeError("fonte quebrada")
    rec2 = ScanRecorder(tmp, period_s=0.0, pose_fn=explode)
    check("Fonte de pose quebrada não derruba o gravador (pose = null)",
          rec2.offer(scan) and rec2._q.get_nowait()["pose"] is None)
    rec3 = ScanRecorder(tmp, period_s=0.0)
    rec3.offer(scan)
    check("Sem pose_fn (robô sem Aurora) → \"pose\": null",
          rec3._q.get_nowait()["pose"] is None)


# ─────────────────────────────────────────────
class _FonteStub:
    fonte = "aurora"

    def __init__(self):
        self.pedidos = 0

    def pedir_partida(self, parado_fn):
        self.pedidos += 1
        return (True, "partida iniciada") if parado_fn() else \
               (False, "o robô precisa estar parado")

    def health(self):
        return {"fonte": "aurora", "valida": False, "motivo": "teste"}


def test_web():
    section("5. Dashboard: a partida exige login; a telemetria leva a pose")
    from core.motor_driver import MotorDriver
    from web.server import create_app
    stub = _FonteStub()
    state = {"robot_id": 1, "mode": "JOYSTICK", "pose": stub.health()}
    app = create_app(motors=MotorDriver(), state=state,
                     pose_source=stub, parado_fn=lambda: True)
    app.config["TESTING"] = True
    c = app.test_client()
    r = c.post("/api/aurora/partida")
    check("POST /api/aurora/partida sem login → 401 (não dispara nada)",
          r.status_code == 401 and stub.pedidos == 0, str(r.status_code))
    c.post("/login", data={"usuario": "operador", "senha": _SENHA})
    r = c.post("/api/aurora/partida")
    check("Com login → 200 e a partida é pedida",
          r.status_code == 200 and stub.pedidos == 1, str(r.status_code))
    t = c.get("/api/status").get_json()
    check("/api/status leva a pose", t.get("pose", {}).get("fonte") == "aurora")

    app2 = create_app(motors=MotorDriver(), state={"robot_id": 2},
                      pose_source=NullPoseSource(), parado_fn=lambda: True)
    c2 = app2.test_client()
    c2.post("/login", data={"usuario": "operador", "senha": _SENHA})
    r = c2.post("/api/aurora/partida")
    check("Robô sem Aurora → 400 'este robô não tem Aurora'",
          r.status_code == 400 and "Aurora" in r.get_json().get("error", ""))
    t = c2.get("/api/status").get_json()
    check("Robô sem Aurora: telemetria diz 'sem fonte de pose'",
          t.get("pose", {}).get("motivo") == "sem fonte de pose")
    rosto = app.test_client().get("/rosto/eventos", buffered=False)
    check("/rosto não recebe a pose (decisão 7)",
          b"pose" not in next(rosto.response, b"")[:2000])


# ─────────────────────────────────────────────
def test_loop():
    section("6. O loop de 50 Hz publica a pose, sem esperar ninguém")
    from core.control_loop import run_control_loop

    class _B:
        blocked_front = False
        def health(self): return {}

    class _H:
        yaw_deg, healthy, resets_total = 0.0, True, 0
        def get_yaw_error(self): return 0.0

    class _Bat:
        def get_status(self): return {}

    class _M:
        def stop(self): pass

    class _Lenta:
        """Uma fonte cuja health() demorasse travaria o loop — a real não
        demora porque só lê o último valor. Aqui ela é instantânea e conta."""
        n = 0
        def health(self):
            self.n += 1
            return {"fonte": "aurora", "valida": True}

    f = _Lenta()
    state = {"running": True, "mode": "JOYSTICK"}
    run_control_loop(state, motors=_M(), bumper=_B(), heading=_H(),
                     battery=_Bat(), pose=f, duration_s=0.3)
    check("state['pose'] é preenchido a cada ciclo",
          state.get("pose", {}).get("fonte") == "aurora" and f.n >= 10, f"{f.n} ciclos")
    src = open(os.path.join(_ROOT, "sensors", "aurora_pose.py"), encoding="utf-8").read()
    corpo_health = src.split("def health(self)")[1].split("def ")[0]
    check("health() do Aurora não chama o SDK (só lê o último valor)",
          "_sdk" not in corpo_health)
    corpo_start = src.split("def start(self)")[1].split("def ")[0]
    check("O SDK é importado em start(), antes do loop (import = 146 ms com o GIL)",
          "import slamtec_aurora_sdk" in corpo_start
          and corpo_start.find("import slamtec_aurora_sdk") < corpo_start.find("Thread("))


# ─────────────────────────────────────────────
def test_bancada():
    section("7. Um cliente só: os scripts de bancada se recusam")
    for nome in ("bancada_aurora.py", "aurora_carregar_mapa.py"):
        src = open(os.path.join(_HERE, nome), encoding="utf-8").read()
        i_guard = src.find("exigir_servico_parado()")
        i_sdk = src.find("AuroraSDK()")
        check(f"{nome} checa o serviço ANTES de abrir o SDK",
              0 < i_guard < i_sdk)
    from sensors import aurora_cliente_unico as acu
    orig = acu.servico_ativo
    acu.servico_ativo = lambda nome: True
    try:
        acu.exigir_servico_parado()
        check("Com o frota-robo ativo, o script sai", False)
    except SystemExit as e:
        check("Com o frota-robo ativo, o script sai com código 2", e.code == 2)
    finally:
        acu.servico_ativo = orig


# ─────────────────────────────────────────────
def test_config():
    section("8. Configuração coerente com as decisões")
    check("Missão exige pose mais fresca que o assistivo (0,3 < 0,5 s)",
          S.POSE_MAX_IDADE_MISSAO_S < S.POSE_MAX_IDADE_S)
    check("Salto de 25 cm está bem acima do que o robô anda por leitura",
          S.POSE_SALTO_M >= 5 * 0.30 * S.AURORA_POLL_S)
    check("Fita: 15 cm / 5°", S.AURORA_FITA_TOL_M == 0.15 and S.AURORA_FITA_TOL_DEG == 5.0)
    if os.path.isfile(S.AURORA_MAPA):
        check("O mapa em disco é o combinado (sha256)",
              sha256_arquivo(S.AURORA_MAPA) == S.AURORA_MAPA_SHA256)
    else:
        print("  (mapa ausente nesta máquina — conferência do sha fica para a Pi)")


# ─────────────────────────────────────────────
def test_nav():
    section("9. Áreas proibidas e POIs — o que o operador desenha")
    from slam.mapa_nav import NavStore, se_cruza, dist_ponto_poligono
    tmp = tempfile.mkdtemp(prefix="fase4_nav_")
    SHA = "a" * 64
    planta = os.path.join(tmp, "m_planta.json")
    with open(planta, "w", encoding="utf-8") as f:
        json.dump({"mapa_sha256": SHA, "res": 0.05, "min_x": -5.0, "max_y": 5.0,
                   "largura_px": 200, "altura_px": 200, "eixo_paredes_deg": 0.0,
                   "paredes": []}, f)
    c = Relogio()
    nav = NavStore(os.path.join(tmp, "nav"), SHA, 0.50, planta_json=planta, clock=c)

    def doc(areas=(), pois=()):
        return {"mapa_sha256": SHA, "areas": list(areas), "pois": list(pois)}
    mesa = {"id": "a1", "nome": "M1", "pontos": [[0, 0], [1.2, 0], [1.2, 0.8], [0, 0.8]]}

    check("Sem nada salvo: versão 0, listas vazias",
          nav.carregar()["versao"] == 0 and nav.carregar()["areas"] == [])
    check("Uma mesa retangular é aceita", nav.validar(doc([mesa])) == [])
    e = nav.validar(doc([{"id": "a2", "nome": "X", "pontos": [[0, 0], [1, 1]]}]))
    check("Área com 2 pontos → recusada (não fecha)", any("não fecha" in t for t in e), str(e))
    laco = {"id": "a3", "nome": "Laço", "pontos": [[0, 0], [1, 1], [1, 0], [0, 1]]}
    check("Área cujos lados se cruzam → recusada",
          any("cruzam" in t for t in nav.validar(doc([laco]))) and se_cruza(laco["pontos"]))
    mini = {"id": "a4", "nome": "Mini", "pontos": [[0, 0], [0.05, 0], [0.05, 0.05]]}
    check("Área menor que 10 × 10 cm → recusada",
          any("pequena" in t for t in nav.validar(doc([mini]))))
    fora = {"id": "a5", "nome": "Fora", "pontos": [[4, 4], [6, 4], [6, 6], [4, 6]]}
    check("Área que sai da planta → recusada",
          any("sai da planta" in t for t in nav.validar(doc([fora]))))
    dup = [mesa, dict(mesa, nome="M2")]
    check("Duas áreas com o mesmo id → recusado",
          any("repetido" in t for t in nav.validar(doc(dup))))
    outro = doc([mesa]); outro["mapa_sha256"] = "b" * 64
    check("Desenho feito para outro mapa → recusado",
          any("outro mapa" in t for t in nav.validar(outro)))
    poi_perto = {"nome": "mesa1", "x": 1.5, "y": 0.4}
    e = nav.validar(doc([mesa], [poi_perto]))
    check("POI a 30 cm da mesa (margem 50 cm) → recusado, com a distância",
          any("margem" in t and "30 cm" in t for t in e), str(e))
    check("POI a 60 cm da mesa → aceito",
          nav.validar(doc([mesa], [{"nome": "mesa1", "x": 1.8, "y": 0.4}])) == [])
    e = nav.validar(doc([], [{"nome": "A", "x": 0, "y": 0}, {"nome": "A", "x": 1, "y": 1}]))
    check("Dois POIs com o mesmo nome → recusado", any("repetido" in t for t in e))
    check("dist_ponto_poligono: dentro = 0, fora = distância à borda",
          dist_ponto_poligono((0.5, 0.4), mesa["pontos"]) == 0
          and abs(dist_ponto_poligono((2.2, 0.4), mesa["pontos"]) - 1.0) < 1e-9)

    ok, r = nav.salvar(doc([mesa], [{"nome": "fita", "x": -2.0, "y": -2.0, "rumo": 125.8}]),
                       "operador", 0)
    check("Salvar cria a versão 1, com quem e quando",
          ok and r["versao"] == 1 and r["quem"] == "operador" and r["quando"])
    ok2, r2 = nav.salvar(doc([mesa]), "operador", 0)
    check("Salvar em cima de uma versão velha → recusado (alguém salvou antes)",
          not ok2 and "recarregue" in r2[0], str(r2))
    ok3, r3 = nav.salvar(doc([mesa]), "operador", 1)
    hist = os.listdir(os.path.join(tmp, "nav", "historico"))
    check("A versão 2 guarda a 1 no histórico", ok3 and r3["versao"] == 2
          and "nav_v0001.json" in hist, str(hist))
    ok4, r4 = nav.salvar(doc([laco]), "operador", 2)
    check("Salvar desenho inválido não muda nada no disco",
          not ok4 and nav.carregar()["versao"] == 2)

    ok, _ = nav.editar("inicio", "operador")
    check("Abrir a edição trava: editando() = True (a missão não começa)",
          ok and nav.editando())
    ok, msg = nav.editar("inicio", "outra pessoa")
    check("Uma 2ª pessoa não abre a edição ao mesmo tempo", not ok, msg)
    c.anda(61)
    check("Editor fechado sem avisar: a trava expira em 60 s", not nav.editando())
    nav.editar("inicio", "operador"); nav.editar("fim", "operador")
    check("Encerrar a edição libera a trava", not nav.editando())

    nav_outro = NavStore(os.path.join(tmp, "nav"), "c" * 64, 0.5, planta_json=planta)
    check("Arquivo de outro mapa é ignorado ao carregar (versão 0)",
          nav_outro.carregar()["versao"] == 0 and nav_outro.planta() is None)

    # Rotas
    from core.motor_driver import MotorDriver
    from web.server import create_app
    app = create_app(motors=MotorDriver(), state={"robot_id": 1}, nav=nav)
    cl = app.test_client()
    check("GET /mapa sem login → vai para o login",
          cl.get("/mapa").status_code in (301, 302))
    check("GET /api/nav sem login → 401", cl.get("/api/nav").status_code == 401)
    r = cl.post("/api/nav", json={"doc": doc([mesa]), "versao_base": 2})
    check("POST /api/nav sem login → 401 (não salva)",
          r.status_code == 401 and nav.carregar()["versao"] == 2)
    cl.post("/login", data={"usuario": "operador", "senha": _SENHA})
    d = cl.get("/api/nav").get_json()
    check("Com login, /api/nav traz desenho, planta, margem e rumo da frente",
          d["ok"] and d["doc"]["versao"] == 2 and d["planta"] and d["margem_m"] == 0.5
          and d["rumo_frente"] == S.AURORA_FITA[2])
    r = cl.post("/api/nav", json={"doc": doc([laco]), "versao_base": 2})
    check("Desenho inválido pelo dashboard → 422 com a lista de erros",
          r.status_code == 422 and r.get_json()["erros"])
    r = cl.post("/api/nav", json={"doc": doc([mesa]), "versao_base": 2})
    check("Desenho válido pelo dashboard → salvo (versão 3)",
          r.status_code == 200 and r.get_json()["doc"]["versao"] == 3)
    r = cl.post("/api/nav/editar", json={"acao": "inicio"})
    check("/api/nav/editar abre a trava", r.status_code == 200 and nav.editando())
    cl.post("/api/nav/editar", json={"acao": "fim"})
    check("GET /mapa com login → 200", cl.get("/mapa").status_code == 200)


def main():
    print(f"{BOLD}GATE DA FASE 4 — pose do Aurora (MOCK){RESET}")
    test_regras()
    test_aurora()
    test_sem_aurora()
    test_gravador()
    test_web()
    test_loop()
    test_bancada()
    test_config()
    test_nav()
    ok = sum(1 for _, r, _ in _results if r)
    total = len(_results)
    print(f"\n{BOLD}RESULTADO: {ok}/{total}{RESET}",
          "VERDE ✅" if ok == total else "com falhas ❌")
    return 0 if ok == total else 1


if __name__ == "__main__":
    sys.exit(main())
