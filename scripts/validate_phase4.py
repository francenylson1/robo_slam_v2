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
        # 29/09 10:29 e 11:23: ao zerar vem 1 e 0 juntos, e OUTRO 0 logo
        # depois, que reinicializa o Aurora e apaga o mapa recém-carregado.
        self.init_instavel = False
        self.mapa_carregado = False
        self.reloc_falhas = 0          # quantas relocalizações falham antes de dar certo
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
        m = self.m
        m.mapa_carregado = False
        m.x, m.y, m.rumo = 0.0, 0.0, 0.0
        if m.init_instavel:
            m.evento(1)
            m.evento(ST_INICIALIZADO)

            def reinicializa():
                m.mapa_carregado = False
                m.evento(ST_INICIALIZADO)
            threading.Timer(0.15, reinicializa).start()
        else:
            m.evento(ST_MAPA_ZERADO)
            m.evento(ST_INICIALIZADO)
        return None

    def require_relocalization(self, timeout_ms=5000):
        # Como o SDK real: True = pedido ACEITO; o resultado vem pelo status.
        ok = (self.m.reloc_resultado == ST_RELOC_OK and self.m.mapa_carregado
              and self.m.reloc_falhas == 0)
        if self.m.reloc_falhas > 0:
            self.m.reloc_falhas -= 1
        if ok:
            self.m.x, self.m.y, self.m.rumo = self.m.reloc_pose
        self.m.reloc_canal = 2 if ok else 3
        self.m.evento(ST_RELOC_OK if ok else ST_RELOC_FALHOU)
        if self.m.sobrescreve:
            self.m.evento(6)          # MAP_UPDATED apaga o 13
        return True

    def get_last_relocalization_status(self, timeout_ms=1000):
        return self.m.reloc_canal


class _Mapas:
    def __init__(self, m):
        self.m = m

    def upload_map(self, caminho, timeout_seconds=180):
        if not self.m.upload_ok:
            return False
        self.m.mapa_carregado = True
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
               status_mapa_s=0.3, quieto_s=0.3,
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
        check("Relocalização falha sempre (status 14) → FALHA depois de 2 tentativas",
              fim_da_partida(a) and "14" in a.partida["resultado"],
              a.partida["resultado"])
        m.reloc_resultado = ST_RELOC_OK

        m.upload_ok = False
        a.pedir_partida(parado_fn)
        check("Upload do mapa devolve False → partida FALHA",
              fim_da_partida(a) and "recusou" in a.partida["resultado"],
              a.partida["resultado"])
        m.upload_ok = True

        # 11 nunca visto: não segue às cegas (a 1ª correção de 29/09 seguia).
        m.sobrescreve = True
        a.pedir_partida(parado_fn)
        check("Sem o status 11 ('mapa carregado') → FALHA, não segue às cegas",
              fim_da_partida(a) and "11" in a.partida["resultado"],
              a.partida["resultado"])
        m.sobrescreve = False

        # 29/09 11:23: 1 e 0 juntos ao zerar, e outro 0 depois que apaga o mapa.
        m.init_instavel = True
        a.pedir_partida(parado_fn)
        check("Aurora reinicializa depois de zerar (o caso das 11:23) → espera "
              "sossegar e dá VERDE", fim_da_partida(a)
              and a.partida["resultado"].startswith("ok"), a.partida["resultado"])
        m.init_instavel = False

        m.reloc_falhas = 1
        a.pedir_partida(parado_fn)
        check("Falha do Aurora na 1ª tentativa → repete sozinho e dá VERDE na 2ª",
              fim_da_partida(a) and a.partida["resultado"].startswith("ok")
              and "2ª" in a.partida["resultado"], a.partida["resultado"])

        # Robô empurrado no meio da sequência.
        chamadas = {"n": 0}

        def anda_no_meio():
            chamadas["n"] += 1
            return chamadas["n"] < 4
        a.pedir_partida(anda_no_meio)
        check("Robô andou no meio da partida → ABORTADA, sem repetir sozinho",
              fim_da_partida(a) and "andou" in a.partida["resultado"]
              and "tentativa" not in a.partida["resultado"],
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
    from slam.mapa_nav import limpar_pontos
    check("Pontos colados (clique duplo) são tirados ao salvar",
          limpar_pontos([[0, 0], [1, 0], [1.001, 0.001], [1, 1], [0, 1], [0.001, 0]])
          == [[0, 0], [1, 0], [1, 1], [0, 1]])
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


# ─────────────────────────────────────────────
def test_planejador():
    section("10. Planejador de rota — contorna as áreas, respeita a margem")
    import numpy as np
    from slam.planejador import Planta, Planejador, comprimento
    # Sala de mentira: 8 × 5 m de chão livre, paredes de 1 célula, cinza fora.
    res = 0.05
    W, H = 200, 140
    cinza = np.full((H, W), 128, dtype=np.uint8)
    cinza[20:120, 20:180] = 255
    cinza[20, 20:180] = 0; cinza[119, 20:180] = 0
    cinza[20:120, 20] = 0; cinza[20:120, 179] = 0
    meta = {"res": res, "min_x": 0.0, "max_y": H * res}
    pl = Planta(cinza, meta)
    # Chão livre: x de 1,05 a 8,95; y de 1,05 a 5,95.
    mesa = {"pontos": [[4.0, 2.5], [5.0, 2.5], [5.0, 4.5], [4.0, 4.5]]}
    p = Planejador(pl, [mesa], 0.50)

    pts, mot = p.planejar((2.0, 3.5), (7.0, 3.5))
    check("Há rota contornando a mesa", pts is not None, mot)

    def pior_folga(pontos):
        pior = 9.0
        for a, b in zip(pontos, pontos[1:]):
            n = int(math.hypot(b[0] - a[0], b[1] - a[1]) / 0.02) + 1
            for k in range(n + 1):
                t = k / n
                pior = min(pior, p.folga(a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t))
        return pior
    pf = pior_folga(pts)
    check("Em nenhum ponto da rota o centro chega a menos da margem (±1 célula)",
          pf >= 0.50 - res, f"pior folga {pf * 100:.0f} cm")
    check("A rota vira poucos trechos retos (o robô gira nos pontos)",
          2 < len(pts) <= 6, f"{len(pts)} pontos, {comprimento(pts):.2f} m")
    check("A rota começa na origem e termina no destino",
          pts[0] == (2.0, 3.5) and pts[-1] == (7.0, 3.5))

    pts2, _ = p.planejar((2.0, 1.8), (2.0, 5.0))
    check("Sem nada no caminho: um trecho reto só", pts2 is not None and len(pts2) == 2)

    ok, mot = p.planejar((2.0, 3.5), (4.5, 3.5))
    check("Destino dentro da mesa → recusado", ok is None and "destino" in mot, mot)
    ok, mot = p.planejar((2.0, 3.5), (5.3, 3.5))
    import re
    fol = re.search(r"folga (\d+) cm", mot or "")
    # O contorno rasterizado cresce a área em até 1 célula (5 cm): conservador.
    check("Destino a 30 cm da mesa (margem 50) → recusado; folga lida 25–30 cm",
          ok is None and fol and 25 <= int(fol.group(1)) <= 30, mot)
    ok, mot = p.planejar((1.2, 3.5), (7.0, 3.5))
    check("Robô a 15 cm da parede → recusado (não sai de dentro da margem)",
          ok is None and "robô" in mot, mot)
    ok, mot = p.planejar((2.0, 3.5), (12.0, 3.5))
    check("Destino fora da planta → recusado", ok is None and "fora" in mot, mot)
    check("O cinza (nunca visto) é proibido: fora da sala não é chão",
          not p.livre(0.5, 3.5))

    # Corredor estreito: duas mesas deixando 0,90 m (< 2 × 0,50) entre elas.
    muro1 = {"pontos": [[4.0, 1.0], [5.0, 1.0], [5.0, 3.0], [4.0, 3.0]]}
    muro2 = {"pontos": [[4.0, 3.9], [5.0, 3.9], [5.0, 6.0], [4.0, 6.0]]}
    p2 = Planejador(pl, [muro1, muro2], 0.50)
    ok, mot = p2.planejar((2.0, 3.45), (7.0, 3.45))
    check("Corredor de 0,90 m com margem de 50 cm → sem caminho (não espreme)",
          ok is None and "não há caminho" in mot, mot)
    p3 = Planejador(pl, [muro1, muro2], 0.40)
    ok, _ = p3.planejar((2.0, 3.45), (7.0, 3.45))
    check("O mesmo corredor com margem de 40 cm → passa (a margem decide)", ok is not None)

    # A rota no /mapa: só mostra, exige login e pose válida.
    from PIL import Image
    from slam.mapa_nav import NavStore
    from core.motor_driver import MotorDriver
    from web.server import create_app
    tmp = tempfile.mkdtemp(prefix="fase4_rota_")
    SHA = "d" * 64
    Image.fromarray(cinza, mode="L").save(os.path.join(tmp, "m_planta.png"))
    with open(os.path.join(tmp, "m_planta.json"), "w", encoding="utf-8") as f:
        json.dump(dict(meta, mapa_sha256=SHA, largura_px=W, altura_px=H,
                       eixo_paredes_deg=0.0, paredes=[]), f)
    nav = NavStore(os.path.join(tmp, "nav"), SHA, 0.50,
                   planta_json=os.path.join(tmp, "m_planta.json"))
    ok, _ = nav.salvar({"mapa_sha256": SHA, "areas": [dict(mesa, id="a1", nome="M1")],
                        "pois": [{"nome": "balcao", "x": 7.0, "y": 3.5}]}, "operador", 0)

    class _Fonte:
        fonte = "aurora"
        def __init__(self): self.p = Pose(2.0, 3.5, 0.0, time.monotonic())
        def pose_valida(self, max_idade_s=None): return self.p
        def motivo(self, max_idade_s=None): return "" if self.p else "desconectado"
        def health(self): return {"fonte": "aurora", "valida": self.p is not None}
    fonte_ = _Fonte()
    app = create_app(motors=MotorDriver(), state={"robot_id": 1},
                     pose_source=fonte_, nav=nav)
    cl = app.test_client()
    check("GET /api/nav/rota sem login → 401",
          cl.get("/api/nav/rota?poi=balcao").status_code == 401)
    cl.post("/login", data={"usuario": "operador", "senha": _SENHA})
    d = cl.get("/api/nav/rota?poi=balcao").get_json()
    check("Com login e pose válida → rota até o POI, contornando a mesa",
          d["ok"] and len(d["pontos"]) > 2 and d["comprimento_m"] > 5.0,
          f"{d.get('comprimento_m')} m")
    fonte_.p = None
    r = cl.get("/api/nav/rota?poi=balcao")
    check("Pose inválida → 409, sem rota", r.status_code == 409
          and "pose" in r.get_json()["motivo"])
    check("POI que não existe → 404",
          cl.get("/api/nav/rota?poi=nada").status_code == 404)

    # P1 (29/09): robô parado DENTRO da folga extra (entre 50 e 55 cm da
    # mesa) — a rota não pode começar com um trecho de poucos cm.
    ok_, _ = p.planejar((3.47, 3.5), (2.0, 5.3))
    menor = min(math.hypot(b_[0] - a_[0], b_[1] - a_[1]) for a_, b_ in zip(ok_, ok_[1:]))
    check("Robô parado a 53 cm da mesa: sem trecho minúsculo no começo (P1)",
          ok_ is not None and menor >= 0.15, f"menor trecho {menor * 100:.0f} cm, {len(ok_)} pontos")

    fina = {"pontos": [[3.0, 1.0], [3.02, 1.0], [3.02, 6.0], [3.0, 6.0]]}
    p4 = Planejador(pl, [fina], 0.50)
    ok, mot = p4.planejar((2.0, 3.5), (6.0, 3.5))
    check("Área mais fina que uma célula (2 cm) ainda bloqueia", ok is None, mot)


# ─────────────────────────────────────────────
# P0 — O ROBÔ DE MENTIRA
# ─────────────────────────────────────────────
class RoboSim:
    """Anda conforme o set_speed, como o robô medido em 22/09: abaixo de 8%
    não anda; 8% = 8,8 cm/s; 12% = 21,7 cm/s. O motor esquerdo é 3% mais
    forte (a assimetria que a malha de rumo corrige). Rodas a 37 cm."""
    BITOLA = 0.37

    def __init__(self, x, y, rumo, clock):
        self.x, self.y, self.rumo = x, y, rumo       # rumo: Aurora (esquerda +)
        self.clock = clock
        self.esq = self.dir = 0.0
        self.maior = 0.0
        self._emergency = False
        self.current_left_tps = self.current_right_tps = 0.0   # como no robô: fica 0
        self.left_ticks_odo = self.right_ticks_odo = 0.0     # contadores dos Hall
        self.rodas_no_ar = False
        self.empurrao = None          # (vx, vy) m/s aplicados por fora
        self.pose_ok = True
        self.bno_ok = True
        self.bno_invertido = False
        self.bloqueado = False
        self.v = 0.0                 # velocidade linear atual (m/s)
        self.w = 0.0                 # velocidade de giro atual (rad/s)

    # interface do motor_driver
    def set_speed(self, e, d):
        self.esq, self.dir = float(e), float(d)
        self.maior = max(self.maior, abs(e), abs(d))

    def stop(self):
        self.esq = self.dir = 0.0

    @staticmethod
    def _v(p):
        a = abs(p)
        if a < 8.0:
            return 0.0
        return math.copysign(0.088 + (a - 8.0) * (0.217 - 0.088) / 4.0, p)

    def passo(self, dt):
        vl, vr = self._v(self.esq) * 1.03, self._v(self.dir)
        circ = 0.50 / 45
        # No robô, current_*_tps fica em ZERO com set_speed (o motor_driver só
        # o atualiza com o PID ligado) — o de mentira imita isso, e quem
        # conta de verdade são os contadores dos Hall (achado na P3, 29/09).
        if self.empurrao:
            self.x += self.empurrao[0] * dt
            self.y += self.empurrao[1] * dt
        else:
            self.left_ticks_odo += abs(vl) * dt / circ
            self.right_ticks_odo += abs(vr) * dt / circ
        if self.rodas_no_ar:
            return
        v_cmd, w_cmd = (vl + vr) / 2, (vr - vl) / self.BITOLA
        # INÉRCIA (P2, 29/09): o robô demora a ganhar giro e continua girando
        # depois de parar — a 8% ~30 °/s e ~15° de inércia. Constante de
        # tempo de 0,5 s no giro e 0,3 s na reta.
        self.w += (w_cmd - self.w) * min(1.0, dt / 0.5)
        self.v += (v_cmd - self.v) * min(1.0, dt / 0.3)
        a = math.radians(self.rumo)
        self.x += self.v * math.cos(a) * dt
        self.y += self.v * math.sin(a) * dt
        self.rumo = normaliza_graus(self.rumo + math.degrees(self.w * dt))


class PoseSim:
    fonte = "aurora"

    def __init__(self, r):
        self.r = r

    def pose_valida(self, max_idade_s=None):
        return Pose(self.r.x, self.r.y, self.r.rumo, self.r.clock()) if self.r.pose_ok else None

    def motivo(self, max_idade_s=None):
        return "" if self.r.pose_ok else "rastreio perdido"


class BnoSim:
    """O BNO085: a DIREITA aumenta (o contrário do Aurora), com zero próprio."""
    def __init__(self, r):
        self.r = r

    @property
    def healthy(self):
        return self.r.bno_ok

    @property
    def yaw_deg(self):
        s = 1 if self.r.bno_invertido else -1
        return normaliza_graus(s * self.r.rumo + 37.0)


class BumperSim:
    def __init__(self, r):
        self.r = r

    @property
    def blocked_front(self):
        return self.r.bloqueado


def montar_missao(x0=2.0, y0=3.5, rumo0=0.0, areas=(), pois=(), base=(2.0, 3.5, 0.0)):
    import numpy as np
    from PIL import Image
    from slam.mapa_nav import NavStore
    from slam.missao import Missao
    from core.heading_assist import HeadingAssist
    res, W, H = 0.05, 200, 140
    cinza = np.full((H, W), 128, dtype=np.uint8)
    cinza[20:120, 20:180] = 255
    cinza[20, 20:180] = 0; cinza[119, 20:180] = 0
    cinza[20:120, 20] = 0; cinza[20:120, 179] = 0
    tmp = tempfile.mkdtemp(prefix="fase4_missao_")
    SHA = "e" * 64
    Image.fromarray(cinza, mode="L").save(os.path.join(tmp, "m_planta.png"))
    with open(os.path.join(tmp, "m_planta.json"), "w", encoding="utf-8") as f:
        json.dump({"mapa_sha256": SHA, "res": res, "min_x": 0.0, "max_y": H * res,
                   "largura_px": W, "altura_px": H, "eixo_paredes_deg": 0.0,
                   "paredes": []}, f)
    nav = NavStore(os.path.join(tmp, "nav"), SHA, 0.50,
                   planta_json=os.path.join(tmp, "m_planta.json"))
    ok, r = nav.salvar({"mapa_sha256": SHA, "areas": list(areas), "pois": list(pois)},
                       "operador", 0)
    assert ok, r
    c = Relogio()
    robo = RoboSim(x0, y0, rumo0, c)
    state = {"mode": "JOYSTICK", "battery": {"missao_permitida": True, "nivel": "ok"}}
    assist = HeadingAssist(kp_pct=S.HEADING_KP_PCT, ki_pct=S.HEADING_KI_PCT,
                           max_corr_pct=S.HEADING_MAX_CORR_PCT, invert=S.HEADING_INVERT,
                           tol_pct=S.HEADING_STRAIGHT_TOL_PCT, teto_pct=S.MOTOR_MAX_POWER_PCT,
                           limite_integral=S.HEADING_INTEGRAL_MAX,
                           trim_pct=S.HEADING_TRIM_PCT, enabled=True)
    mis = Missao(motors=robo, pose_source=PoseSim(robo), heading=BnoSim(robo),
                 bumper=BumperSim(robo), nav=nav, assist=assist, state=state, cfg=S,
                 base_poi={"nome": "base", "x": base[0], "y": base[1], "rumo": base[2]},
                 historico=os.path.join(tmp, "missoes.jsonl"), clock=c)
    return mis, robo, c, state, nav, tmp


def rodar(mis, robo, c, segundos, durante=None):
    for k in range(int(segundos / 0.02)):
        robo.passo(0.02)
        c.anda(0.02)
        mis.tick(0.02)
        if durante:
            durante(k * 0.02)
        if not mis.ativa and k > 2:
            return k * 0.02
    return segundos


def ir(mis, nome):
    pts, _, motivo = mis.planejar(nome)
    if pts is None:
        return False, motivo
    return mis.iniciar(nome, "operador", [list(p) for p in pts])


def test_missao():
    section("11. MISSÃO — P0: o robô de mentira vai até o POI")
    mesa = {"id": "a1", "nome": "M1", "pontos": [[4.0, 2.5], [5.0, 2.5], [5.0, 4.5], [4.0, 4.5]]}
    pois = [{"nome": "frente", "x": 3.5, "y": 3.5, "rumo": None},
            {"nome": "lado", "x": 2.0, "y": 5.3, "rumo": None},
            {"nome": "atras_mesa", "x": 7.0, "y": 3.5, "rumo": 180.0}]

    mis, robo, c, st, nav, tmp = montar_missao(areas=[mesa], pois=pois)
    ok, msg = ir(mis, "frente")
    t = rodar(mis, robo, c, 60)
    d = math.hypot(robo.x - 3.5, robo.y - 3.5)
    check("Reto 1,5 m à frente: chega a menos de 15 cm e para",
          mis.resultado and mis.resultado["ok"] and d < 0.15,
          f"{d * 100:.1f} cm em {t:.1f} s — {mis.resultado and mis.resultado['texto']}")
    check("Nunca passou de 12% em nenhuma roda", robo.maior <= S.MISSAO_TETO_PCT + 1e-9,
          f"máx {robo.maior:.1f}%")
    check("Ao terminar: motores parados e modo de volta a Joystick",
          robo.esq == 0 and robo.dir == 0 and st["mode"] == "JOYSTICK")
    check("A fala de começo e a de chegada foram pedidas",
          mis.fala and mis.fala["grupo"] == "missao_chegou" and mis.fala["id"] == 2)

    ok, msg = ir(mis, "lado")
    rodar(mis, robo, c, 60)
    d = math.hypot(robo.x - 2.0, robo.y - 5.3)
    check("Com giro grande: gira, anda e chega a menos de 15 cm",
          mis.resultado["ok"] and d < 0.15, f"{d * 100:.1f} cm — {mis.resultado['texto']}")

    mis, robo, c, st, nav, tmp = montar_missao(areas=[mesa], pois=pois)
    plan = nav.planejador()
    fora = []
    ok, msg = ir(mis, "atras_mesa")
    rodar(mis, robo, c, 120, lambda t: fora.append(1) if not plan.livre(robo.x, robo.y) else None)
    d = math.hypot(robo.x - 7.0, robo.y - 3.5)
    check("Contornando a mesa (vários trechos): chega a menos de 15 cm",
          mis.resultado["ok"] and d < 0.15, f"{d * 100:.1f} cm — {mis.resultado['texto']}")
    check("Em nenhum instante o centro entrou na margem", not fora, f"{len(fora)} ciclos fora")
    check("POI com rumo: termina virado para ele (±5°)",
          abs(normaliza_graus(robo.rumo - 180.0)) <= 5.0, f"rumo {robo.rumo:.1f}°")
    linhas = open(os.path.join(tmp, "missoes.jsonl"), encoding="utf-8").read().splitlines()
    check("A missão foi para o histórico", len(linhas) == 1 and json.loads(linhas[0])["ok"])

    ok, _ = ir(mis, "base")
    rodar(mis, robo, c, 120)
    d = math.hypot(robo.x - 2.0, robo.y - 3.5)
    check("Voltar para a base: chega a menos de 10 cm e virado para o rumo da fita",
          mis.resultado["ok"] and d < 0.10 and abs(normaliza_graus(robo.rumo)) <= 5.0,
          f"{d * 100:.1f} cm, rumo {robo.rumo:.1f}° — {mis.resultado['texto']}")
    check("Na base, a fala é a de chegada na base",
          mis.fala["grupo"] == "missao_chegou_base")

    section("12. MISSÃO — o que faz parar (e não retoma)")

    def cenario(nome_poi, acao, quando=1.5, depois=4.0):
        m_, r_, c_, st_, n_, t_ = montar_missao(areas=[mesa], pois=pois)
        ir(m_, nome_poi)
        feito = {"v": False}

        def gatilho(t):
            if t >= quando and not feito["v"]:
                feito["v"] = True
                acao(m_, r_, st_)
        rodar(m_, r_, c_, 30, gatilho)
        for _ in range(75):          # 1,5 s: a inércia do robô acaba
            r_.passo(0.02); c_.anda(0.02); m_.tick(0.02)
        pos = (r_.x, r_.y)
        for _ in range(int(depois / 0.02)):
            r_.passo(0.02); c_.anda(0.02); m_.tick(0.02)
        parado = math.hypot(r_.x - pos[0], r_.y - pos[1]) < 0.005
        return m_, r_, parado

    m_, r_, parado = cenario("frente", lambda m, r, s: setattr(r, "bloqueado", True))
    check("Bumper no meio do caminho → cancela", m_.resultado and not m_.resultado["ok"]
          and "bumper" in m_.resultado["texto"], m_.resultado and m_.resultado["texto"])
    r_.bloqueado = False
    pos = (r_.x, r_.y)
    for _ in range(200):
        r_.passo(0.02); m_.tick(0.02)
    check("...e NÃO retoma quando o caminho libera",
          math.hypot(r_.x - pos[0], r_.y - pos[1]) < 0.005 and not m_.ativa)

    m_, r_, parado = cenario("frente", lambda m, r, s: setattr(r, "pose_ok", False))
    check("Pose do Aurora inválida → cancela, com a fala 'perdi a localização'",
          not m_.resultado["ok"] and "localização" in m_.resultado["texto"]
          and m_.fala["grupo"] == "missao_perdido" and parado)
    m_, r_, parado = cenario("frente", lambda m, r, s: setattr(r, "bno_ok", False))
    check("BNO sem sinal → cancela", not m_.resultado["ok"] and "BNO" in m_.resultado["texto"])
    m_, r_, parado = cenario("frente", lambda m, r, s: s.update(
        battery={"missao_permitida": False, "nivel": "critica"}))
    check("Bateria sem permissão no meio → cancela",
          not m_.resultado["ok"] and "bateria" in m_.resultado["texto"])
    m_, r_, parado = cenario("frente", lambda m, r, s: m.cancelar("PARAR", operador=True))
    check("PARAR → cancela, calado (quem parou sabe)", not m_.resultado["ok"]
          and "PARAR" in m_.resultado["texto"] and m_.fala["grupo"] == "missao_inicio" and parado)
    m_, r_, parado = cenario("frente", lambda m, r, s: m.cancelar("joystick", operador=True))
    check("Joystick → cancela e devolve o modo Joystick",
          not m_.resultado["ok"] and m_.state["mode"] == "JOYSTICK" and parado)
    m_, r_, parado = cenario("frente", lambda m, r, s: s.update(fleet_estop=True))
    check("E-Stop geral da Torre → cancela",
          not m_.resultado["ok"] and "E-Stop" in m_.resultado["texto"])

    m_, r_, parado = cenario("lado", lambda m, r, s: setattr(r, "bno_invertido", True), quando=0.3)
    check("BNO com o SINAL trocado → cancela no giro ('discordam'), sem espiralar",
          not m_.resultado["ok"] and "discordam" in m_.resultado["texto"],
          m_.resultado["texto"])

    m_, r_, parado = cenario("frente", lambda m, r, s: setattr(r, "rodas_no_ar", True), quando=0.5)
    check("Rodas no ar (P1) → cancela em poucos segundos",
          not m_.resultado["ok"] and m_.resultado["duracao_s"] < 6.0,
          f"{m_.resultado['texto']} ({m_.resultado['duracao_s']} s)")

    def empurra(m, r, s):
        r.empurrao = (0.0, 0.25)
        r.rodas_no_ar = True
    m_, r_, parado = cenario("frente", empurra, quando=0.5)
    check("Empurrado de lado (pose anda, rodas não) → cancela",
          not m_.resultado["ok"], m_.resultado["texto"])

    section("13. MISSÃO — largada: o que impede de começar")
    mis, robo, c, st, nav, tmp = montar_missao(areas=[mesa], pois=pois)
    nav.editar("inicio", "operador")
    ok, msg = ir(mis, "frente")
    check("Editor aberto → não começa", not ok and "editado" in msg, msg)
    nav.editar("fim", "operador")
    robo.bloqueado = True
    ok, msg = ir(mis, "frente")
    check("Algo na frente (bumper) → não começa", not ok and "bumper" in msg, msg)
    robo.bloqueado = False
    pts, _, _ = mis.planejar("frente")
    torta = [list(p) for p in pts]
    torta[-1] = [torta[-1][0] + 0.5, torta[-1][1]]
    ok, msg = mis.iniciar("frente", "operador", torta)
    check("Rota diferente da que foi mostrada → recusa ('veja de novo')",
          not ok and "de novo" in msg, msg)
    ok, msg = ir(mis, "nao_existe")
    check("POI que não existe → recusa", not ok and "não encontrado" in msg, msg)
    ok1, _ = ir(mis, "frente")
    rodar(mis, robo, c, 1.0)
    ok2, _ = ir(mis, "lado")
    rodar(mis, robo, c, 60)
    check("Dois pedidos: vale o último", ok1 and ok2 and mis.resultado["ok"]
          and mis.resultado["destino"] == "lado", mis.resultado["texto"])
    ok, msg = ir(mis, "lado")
    check("Já no destino → recusa ('já está')", not ok and "já está" in msg, msg)

    from slam.missao import Missao
    sem = Missao(motors=RoboSim(0, 0, 0, c), pose_source=NullPoseSource(), heading=BnoSim(robo),
                 bumper=BumperSim(robo), nav=nav, assist=None, state={}, cfg=S,
                 base_poi={"nome": "base", "x": 0, "y": 0, "rumo": 0})
    ok, msg = sem.iniciar("frente", "operador", [])
    check("Robô sem Aurora: missão indisponível", not ok and "localização" in msg
          and sem.estado()["disponivel"] is False)

    # P3 (29/09): current_*_tps fica em zero com set_speed. Nem a missão nem
    # a checagem de "robô parado" podem depender dele.
    import ast as _ast
    usos = []
    for arq in (os.path.join(_ROOT, "slam", "missao.py"), os.path.join(_ROOT, "main.py")):
        arv = _ast.parse(open(arq, encoding="utf-8").read())
        usos += [os.path.basename(arq) for n in _ast.walk(arv)
                 if isinstance(n, _ast.Attribute) and n.attr in ("current_left_tps", "current_right_tps")]
    check("Missão e 'robô parado' não usam current_*_tps (zero sem o PID)", not usos,
          ", ".join(usos))


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
    test_planejador()
    test_missao()
    ok = sum(1 for _, r, _ in _results if r)
    total = len(_results)
    print(f"\n{BOLD}RESULTADO: {ok}/{total}{RESET}",
          "VERDE ✅" if ok == total else "com falhas ❌")
    return 0 if ok == total else 1


if __name__ == "__main__":
    sys.exit(main())
