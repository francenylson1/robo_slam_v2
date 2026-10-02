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
        # Diagnóstico da "pose velha" (01/10/2026): carimbo em ns de um Aurora
        # que gera pose a cada 20 ms; "congelada" = o Aurora para de gerar;
        # "atraso_status" = a próxima consulta do serviço demora (Pi ocupada).
        self.ts_ns = False
        self.congelada = False
        self.atraso_status = 0.0
        # Mapear pelo painel (02/10/2026): o mapa que o Aurora entrega no
        # download e uma pose que escorrega a cada leitura (medida que discorda).
        self.download_ok = True
        self.mapa_novo = b"MAPA-NOVO"
        self.deriva = 0.0

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

    def download_map(self, caminho, timeout_seconds=None, progress_callback=None):
        if not self.m.download_ok:
            return False
        with open(caminho, "wb") as f:
            f.write(self.m.mapa_novo)
        return True


class _Dados:
    def __init__(self, m):
        self.m = m

    def get_current_pose(self, use_se3=False):
        with self.m.lock:
            if self.m.ts_ns:
                if not self.m.congelada:
                    self.m.pose_ts = int(time.monotonic() / 0.02) * 20_000_000
            else:
                self.m.pose_ts += 1
            self.m.x += self.m.deriva
            return ((self.m.x, self.m.y, 0.0),
                    (0.0, 0.0, math.radians(self.m.rumo)), self.m.pose_ts)

    def get_last_device_status(self):
        atraso, self.m.atraso_status = self.m.atraso_status, 0.0
        if atraso:
            time.sleep(atraso)
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


def fonte(mundo, mapa, sha, fita=None, **kw):
    v = PoseValidator(
        fita=fita or S.AURORA_FITA, fita_tol_m=S.AURORA_FITA_TOL_M,
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

    # 01/10/2026: a volta do LASER do Aurora (1,45 m) entra como "a145".
    laser = {"v": {"t": time.monotonic(), "ts": 111, "dyaw": 0.01, "kf": 7,
                   "pose": [1.0, 2.0, 1.45, 30.0], "p": [[9000, 2500, 40]]}}
    rec4 = ScanRecorder(tmp, period_s=0.0, laser_fn=lambda: laser["v"])
    rec4.offer(scan)
    r1 = rec4._q.get_nowait()
    rec4.offer(scan)
    r2 = rec4._q.get_nowait()
    laser["v"] = dict(laser["v"], ts=112, t=time.monotonic() - 5.0)
    rec4.offer(scan)
    r3 = rec4._q.get_nowait()
    check("Laser do Aurora novo e fresco → \"a145\" com ts, pose, pontos e idade",
          "a145" in r1 and r1["a145"]["ts"] == 111 and r1["a145"]["p"] == [[9000, 2500, 40]]
          and r1["a145"]["pose"] == [1.0, 2.0, 1.45, 30.0] and 0 <= r1["a145"]["idade_s"] < 1,
          str(r1.get("a145")))
    check("A mesma volta não é gravada duas vezes; volta velha (> 2 s) não entra",
          "a145" not in r2 and "a145" not in r3)

    def laser_quebrado():
        raise RuntimeError("SDK quebrado")
    rec5 = ScanRecorder(tmp, period_s=0.0, laser_fn=laser_quebrado)
    ok5 = rec5.offer(scan)
    r5 = rec5._q.get_nowait()
    check("Laser quebrado não derruba o gravador (linha do C1 sai, sem \"a145\")",
          ok5 and "a145" not in r5 and len(r5["p"]) == 2)
    check("Sem laser_fn (robô sem Aurora) → linha sem \"a145\"", "a145" not in reg1)


def test_laser_aurora():
    section("4b. O laser do Aurora (1,45 m) é lido sem afetar a pose")
    from types import SimpleNamespace as NS
    tmp = tempfile.mkdtemp(prefix="fase4_laser_")
    mapa = os.path.join(tmp, "mapa.stcm")
    with open(mapa, "wb") as f:
        f.write(b"mapa de mentira")
    sha = sha256_arquivo(mapa)

    chamadas = {"n": 0}
    yaw = math.radians(90.0)
    def laser_ok(sdk, max_pontos):
        chamadas["n"] += 1
        info = NS(timestamp_ns=1000 + chamadas["n"], dyaw=0.002, binded_kf_id=5)
        pontos = [NS(dist=2.5, angle=math.radians(45.0), quality=50),
                  NS(dist=1.0, angle=math.radians(-90.0), quality=0),   # inválido
                  NS(dist=0.0, angle=0.0, quality=30)]                   # sem retorno
        pose = NS(translation=NS(x=1.5, y=-0.5, z=1.45),
                  quaternion=NS(x=0.0, y=0.0, z=math.sin(yaw / 2), w=math.cos(yaw / 2)))
        return info, pontos, pose

    m = Mundo()
    a = fonte(m, mapa, sha, laser_periodo_s=0.05, laser_fn=laser_ok)
    a.start()
    try:
        esperar(lambda: a.ultimo_laser() is not None)
        lz = a.ultimo_laser()
        check("Laser lido: ângulo em centigraus, distância em mm, só pontos válidos",
              lz is not None and lz["p"] == [[4500, 2500, 50]], str(lz and lz["p"]))
        check("Pose da varredura: x, y, z do Aurora e rumo do quaternion (90°)",
              lz is not None and lz["pose"] == [1.5, -0.5, 1.45, 90.0], str(lz and lz["pose"]))
        n1 = chamadas["n"]
        time.sleep(0.3)
        n2 = chamadas["n"]
        check("Respeita o período (0,05 s → ~6 leituras em 0,3 s, não 30)",
              1 <= n2 - n1 <= 12, f"{n2 - n1} leituras")
    finally:
        a.stop()

    def laser_explode(sdk, max_pontos):
        raise RuntimeError("peek falhou")
    m2 = Mundo()
    b = fonte(m2, mapa, sha, laser_periodo_s=0.01, laser_fn=laser_explode)
    b.start()
    try:
        esperar(lambda: b.laser_erros >= 3)
        ts0 = m2.pose_ts
        time.sleep(0.1)
        check("Laser quebrado: conexão segue, poses continuam chegando, erro contado",
              b.health()["conectado"] and m2.pose_ts > ts0 and b.laser_erros >= 3
              and b.ultimo_laser() is None and b.reconexoes == 0,
              f"erros {b.laser_erros}, reconexões {b.reconexoes}")
    finally:
        b.stop()

    m3 = Mundo()
    c = fonte(m3, mapa, sha, laser_fn=laser_ok)     # período padrão = 0 (desligado)
    antes = chamadas["n"]
    c.start()
    try:
        esperar(lambda: c.health()["conectado"])
        time.sleep(0.1)
        check("Período 0 (robôs sem a gravação): o laser nunca é pedido",
              chamadas["n"] == antes)
    finally:
        c.stop()
    src = open(os.path.join(_ROOT, "main.py"), encoding="utf-8").read()
    check("main.py liga o laser pelo settings e o entrega ao gravador",
          "laser_periodo_s=AURORA_LASER_GRAVAR_S" in src
          and 'laser_fn=getattr(pose_source, "ultimo_laser", None)' in src
          # 0 ou 1 s: desligado nas missões (01/10 à tarde) e ligado só no
          # corredor (01/10 à noite). Qualquer outro valor é engano.
          and S.AURORA_LASER_GRAVAR_S in (0, 1.0))


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


def test_silencio_da_pose():
    section("4c. Silêncio da pose: de quem é o atraso (diagnóstico de 01/10)")
    import logging
    tmp = tempfile.mkdtemp(prefix="fase4_silencio_")
    mapa = os.path.join(tmp, "mapa.stcm")
    with open(mapa, "wb") as f:
        f.write(b"mapa de mentira")
    sha = sha256_arquivo(mapa)
    msgs = []

    class _H(logging.Handler):
        def emit(self, r):
            msgs.append(r.getMessage())
    h = _H()
    lg = logging.getLogger("sensors.aurora_pose")
    nivel = lg.level
    lg.setLevel(logging.INFO)          # o resumo é INFO
    lg.addHandler(h)
    m = Mundo()
    m.ts_ns = True
    a = None
    try:
        a = fonte(m, mapa, sha, diag_aviso_s=0.2, diag_periodo_s=0.5)
        a.start()
        esperar(lambda: a.health()["conectado"])
        time.sleep(0.3)
        check("Sem silêncio, nada é apontado", a.health().get("silencio") is None,
              str(a.health().get("silencio")))
        mz = Mundo()
        mz.ts_ns = True
        mz.congelada = True        # 18:49 de 01/10: ao conectar veio carimbo 0
        b0 = fonte(mz, mapa, sha, diag_aviso_s=5.0, diag_periodo_s=0.4)
        b0.start()
        try:
            esperar(lambda: b0.health()["conectado"])
            time.sleep(0.1)
            mz.congelada = False
            time.sleep(0.6)
        finally:
            b0.stop()
        import re
        resumos = [x for x in msgs if "poses novas" in x]
        aparelho = [int(v) for x in resumos for v in re.findall(r"relógio do Aurora (\d+) ms", x)]
        check("Carimbo 0 logo ao conectar não vira intervalo absurdo no relógio do Aurora",
              bool(aparelho) and max(aparelho) < 1000, str(resumos[-1:]))
        msgs.clear()
        m.congelada = True
        time.sleep(0.4)
        m.congelada = False
        esperar(lambda: a.health().get("silencio") is not None, 1.0)
        s1 = a.health().get("silencio") or {}
        check("Aurora parado 0,4 s com consultas em dia → culpa do AURORA",
              s1.get("lado", "").startswith("Aurora") and s1.get("silencio_ms", 0) >= 350
              and s1.get("maior_consulta_ms", 999) < 100 and (s1.get("aparelho_ms") or 0) >= 350,
              str(s1))
        time.sleep(0.1)
        m.atraso_status = 0.4
        esperar(lambda: (a.health().get("silencio") or {}).get("lado", "").startswith("serviço"), 1.5)
        s2 = a.health().get("silencio") or {}
        check("Consulta presa 0,4 s → culpa do SERVIÇO",
              s2.get("lado", "").startswith("serviço") and s2.get("maior_consulta_ms", 0) >= 350,
              str(s2))
        check("O silêncio vira aviso no log, com os dois relógios",
              any("sem pose nova" in x and "relógio do Aurora" in x for x in msgs), str(msgs[-3:]))
        time.sleep(0.6)
        check("Resumo periódico no log: consultas, poses novas e silêncios",
              any("consultas" in x and "poses novas" in x and "silêncios" in x for x in msgs),
              str([x for x in msgs if "consultas" in x][-1:]))
        check("Só observa: a conexão segue e nenhuma reconexão foi feita",
              a.health()["conectado"] and a.reconexoes == 0, str(a.health()))
    except Exception as e:
        check("Diagnóstico do silêncio existe (fonte aceita diag_*, health tem 'silencio')",
              False, repr(e))
    finally:
        if a is not None:
            a.stop()
        lg.removeHandler(h)
        lg.setLevel(nivel)


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
        vl, vr = self._v(self.esq) * getattr(self, "assimetria", 1.03), self._v(self.dir)
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
        w_cmd *= getattr(self, "fator_giro", 1.0)     # atrito alto: o giro rende menos
        # PISO PESADO (30/09/2026): num ponto da sala, pulsos de giro a 8% não
        # renderam nada (rodízio/piso segurando). Girando no lugar abaixo desta
        # força, o robô não sai do lugar.
        lim = getattr(self, "giro_min_pct", 0.0)
        if lim and self.esq * self.dir < 0 and max(abs(self.esq), abs(self.dir)) < lim:
            w_cmd = 0.0
        # INÉRCIA (P2, 29/09): o robô demora a ganhar giro e continua girando
        # depois de parar — a 8% ~30 °/s e ~15° de inércia. Constante de
        # tempo de 0,5 s no giro e 0,3 s na reta.
        self.w += (w_cmd - self.w) * min(1.0, dt / getattr(self, "tau_giro", 0.5))
        self.v += (v_cmd - self.v) * min(1.0, dt / 0.6)   # P3: desliza ~7 cm
        a = math.radians(self.rumo)
        self.x += self.v * math.cos(a) * dt
        self.y += self.v * math.sin(a) * dt
        dgiro = math.degrees(self.w * dt)
        self.rumo = normaliza_graus(self.rumo + dgiro)
        # ESCORREGA NO GIRO (30/09/2026): um giro final de 174° levou o centro
        # 11 cm para o lado (trena e Aurora concordando). k em m por grau.
        k = getattr(self, "escorrega_giro", 0.0)
        if k:
            a = math.radians(self.rumo)
            self.x += k * abs(dgiro) * math.sin(a)      # para a DIREITA do robô
            self.y -= k * abs(dgiro) * math.cos(a)


class PoseSim:
    """A pose do Aurora como ela chega de verdade: 10 leituras/s, com ~0,1 s
    de ATRASO e um pouco de RUÍDO (±5 mm, ±0,5°). Sem isso, a P0 não via a
    oscilação que apareceu na 2ª P3 (29/09)."""
    fonte = "aurora"

    def __init__(self, r):
        import random
        self.r = r
        self._rnd = random.Random(29)
        self._hist = []
        self._ult = None
        self._t_leitura = -1.0

    def pose_valida(self, max_idade_s=None):
        if not self.r.pose_ok:
            return None
        agora = self.r.clock()
        self._hist.append((agora, self.r.x, self.r.y, self.r.rumo))
        # ~0,3 s de atraso: foi o que a P4 (29/09) mostrou girando a 30°/s.
        while len(self._hist) > 2 and self._hist[1][0] <= agora - 0.3:
            self._hist.pop(0)
        if self._ult is None or agora - self._t_leitura >= 0.1:
            t, x, y, rumo = self._hist[0]
            g = self._rnd.gauss
            self._ult = Pose(x + g(0, 0.005), y + g(0, 0.005), rumo + g(0, 0.5), agora)
            self._t_leitura = agora
        return self._ult

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
    """O C1: bloqueado = algo a menos de 50 cm; perto_m = o ponto mais perto
    no arco da frente; lidar_ok = dado fresco (fail-closed)."""
    def __init__(self, r):
        self.r = r

    @property
    def healthy(self):
        return getattr(self.r, "lidar_ok", True)

    @property
    def blocked_front(self):
        if not self.healthy:
            return True
        p = getattr(self.r, "perto_m", None)
        return self.r.bloqueado or (p is not None and p < 0.50)

    def health(self):
        p = getattr(self.r, "perto_m", None)
        if self.r.bloqueado and p is None:
            p = 0.10
        return {"healthy": self.healthy, "nearest_m": p}


def montar_missao(x0=2.0, y0=3.5, rumo0=0.0, areas=(), pois=(), base=(2.0, 3.5, 0.0)):
    import numpy as np
    from PIL import Image
    from slam.mapa_nav import NavStore
    from slam.missao import Missao, malha_da_missao
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
    assist = malha_da_missao(S)          # a MESMA fábrica do main.py
    mis = Missao(motors=robo, pose_source=PoseSim(robo), heading=BnoSim(robo),
                 bumper=BumperSim(robo), nav=nav, assist=assist, state=state, cfg=S,
                 base_poi={"nome": "base", "x": base[0], "y": base[1], "rumo": base[2]},
                 historico=os.path.join(tmp, "missoes.jsonl"),
                 traco_dir=os.path.join(tmp, "tracos"), clock=c)
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
    esperar(lambda: os.path.isfile(getattr(mis, "traco_ultimo", "") or ""), 2.0)
    time.sleep(0.2)
    tr = open(mis.traco_ultimo, encoding="utf-8").read().splitlines() \
        if os.path.isfile(getattr(mis, "traco_ultimo", "") or "") else []
    check("Traço de diagnóstico do reto gravado (50 Hz, BNO, referência, comando, pose, mira)",
          len(tr) > 100 and tr[1].startswith("t_s,trecho,bno_graus,ref_graus")
          and any(l.split(",")[-2] for l in tr[2:]),        # a mira conferiu
          f"{len(tr)} linhas")

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
        for _ in range(150):         # 3 s: a inércia do robô acaba
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

    # P6 (29/09): bumper de 20 cm no giro, 50 cm no reto (decisão do professor).
    def giro_com_obstaculo(dist, lidar_ok=True, quando=0.3):
        m6, r6, c6, s6, n6, t6 = montar_missao(areas=[mesa], pois=pois)
        ir(m6, "lado")                     # começa com um giro grande
        def acao(t):
            if t >= quando:
                r6.perto_m = dist
                r6.lidar_ok = lidar_ok
        for k in range(int(3.0 / 0.02)):   # 3 s: ainda girando
            r6.passo(0.02); c6.anda(0.02); m6.tick(0.02); acao(k * 0.02)
        return m6
    m6 = giro_com_obstaculo(0.35)
    check("Girando, algo a 35 cm do C1 NÃO cancela (bumper de 20 cm no giro)",
          m6.ativa, m6.resultado and m6.resultado["texto"])
    m6 = giro_com_obstaculo(0.15)
    check("Girando, algo a 15 cm do C1 cancela", not m6.ativa
          and "bumper" in (m6.resultado or {}).get("texto", ""))
    m6 = giro_com_obstaculo(None, lidar_ok=False)
    check("Girando, LIDAR sem dado cancela (fail-closed mantido)", not m6.ativa)
    m7, r7, c7, s7, n7, t7 = montar_missao(areas=[mesa], pois=pois)
    ir(m7, "frente")                       # reto, sem giro
    rodar(m7, r7, c7, 1.0)
    r7.perto_m = 0.35
    rodar(m7, r7, c7, 1.0)
    check("Andando reto, algo a 35 cm cancela (bumper de 50 cm no reto)",
          not m7.ativa and "bumper" in m7.resultado["texto"], m7.resultado and m7.resultado["texto"])

    # Volta do P-quina (29/09 18:24): chegando a um ponto de curva de frente
    # para uma mesa, o C1 a vê a ~40 cm. Na aproximação lenta, 30 cm.
    def reto_com_obstaculo(dist, zona_lenta):
        m9, r9, c9, s9, n9, t9 = montar_missao(areas=[mesa], pois=pois)
        ir(m9, "frente")                   # 1,5 m reto, sem giro
        def acao(t):
            falta = m9.m.get("falta", 9.0) if m9.m else 9.0
            if (falta < 0.55) == zona_lenta:
                r9.perto_m = dist
        for k in range(int(20 / 0.02)):
            r9.passo(0.02); c9.anda(0.02); m9.tick(0.02)
            if m9.ativa:
                acao(k * 0.02)
            elif k > 2:
                break
        return m9
    m9 = reto_com_obstaculo(0.40, zona_lenta=True)
    check("Aproximação lenta, algo a 40 cm do C1: NÃO cancela (bumper de 30 cm)",
          m9.resultado and m9.resultado["ok"], m9.resultado and m9.resultado["texto"])
    m9 = reto_com_obstaculo(0.25, zona_lenta=True)
    check("Aproximação lenta, algo a 25 cm do C1: cancela",
          m9.resultado and "bumper" in m9.resultado["texto"], m9.resultado and m9.resultado["texto"])
    m9 = reto_com_obstaculo(0.40, zona_lenta=False)
    check("Reto a 12%, algo a 40 cm do C1: cancela (bumper de 50 cm)",
          m9.resultado and "bumper" in m9.resultado["texto"], m9.resultado and m9.resultado["texto"])

    # 29/09 18:42: no ponto de curva, a reta até o próximo cruzava a margem.
    # Agora replaneja de onde está (decisão do professor) e chega.
    m11, r11, c11, s11, n11, t11 = montar_missao(areas=[mesa], pois=pois)
    replanos = []
    original = m11._replanejar
    m11._replanejar = lambda p, motivo: (replanos.append(motivo), original(p, motivo))
    ir(m11, "atras_mesa")                  # vários trechos, contornando a mesa
    empurrado = {"v": False}
    for k in range(int(150 / 0.02)):
        r11.passo(0.02); c11.anda(0.02); m11.tick(0.02)
        if (not empurrado["v"] and m11.m and m11.m["fase"] == "assentando"
                and m11.m["trecho"] == 0):
            # No 1º ponto de curva o robô "aparece" de frente para a mesa
            # (x 3,2; fora da margem): a reta até o próximo ponto a cruza.
            r11.x, r11.y, r11.v, r11.w = 3.2, 3.5, 0.0, 0.0
            empurrado["v"] = True
        if not m11.ativa and k > 2:
            break
    check("Reta até o próximo ponto cruzando a margem: replaneja de onde está e chega",
          empurrado["v"] and replanos and m11.resultado and m11.resultado["ok"],
          f"{len(replanos)} replanejamento(s) — " + (m11.resultado and m11.resultado["texto"] or ""))

    m12, r12, c12, s12, n12, t12 = montar_missao(areas=[mesa], pois=pois)
    ir(m12, "frente")
    rodar(m12, r12, c12, 1.0)
    r12.x, r12.y = 3.7, 3.5                # dentro da margem da mesa
    rodar(m12, r12, c12, 2.0)
    check("Centro dentro da margem: para com a fala de caminho apertado (não 'perdido')",
          m12.resultado and not m12.resultado["ok"] and m12.fala["grupo"] == "missao_apertado",
          m12.resultado and m12.resultado["texto"])

    # Volta do P-quina (29/09 18:31): giro contínuo caindo a ~2 °/s no canto.
    # Com atrito muito alto (rende 10%), a força sobe e ele chega.
    m10, r10, c10, s10, n10, t10 = montar_missao(areas=[mesa], pois=pois)
    r10.fator_giro = 0.10
    ok, _ = ir(m10, "lado")
    rodar(m10, r10, c10, 120)
    check("Atrito muito alto no giro contínuo: a força sobe (até 12%) e ele chega",
          m10.resultado and m10.resultado["ok"] and r10.maior <= 12.0 + 1e-9,
          (m10.resultado and m10.resultado["texto"]) + f" · máx {r10.maior:.0f}%")

    # Volta do P-quina (29/09 18:16): pulsos rendendo ~1°. Com atrito alto
    # (giro rende 35%), os pulsos se ajustam e ele aponta.
    m8, r8, c8, s8, n8, t8 = montar_missao(areas=[mesa], pois=pois)
    r8.fator_giro = 0.35
    ok, _ = ir(m8, "lado")
    rodar(m8, r8, c8, 90)
    check("Atrito alto no giro (pulsos rendendo pouco): os pulsos se ajustam e ele chega",
          m8.resultado and m8.resultado["ok"], m8.resultado and m8.resultado["texto"])

    # P5 (29/09): a 20 cm do ponto (entre "perto" e a tolerância) ele tem de
    # ANDAR o resto, e não declarar chegada nem falha.
    m5, r5, c5, st5, n5, t5 = montar_missao(x0=2.0, y0=3.5, rumo0=10.0,
                                            pois=[{"nome": "vinte", "x": 2.2, "y": 3.5, "rumo": None}])
    ok, msg = ir(m5, "vinte")
    rodar(m5, r5, c5, 30)
    d5 = math.hypot(r5.x - 2.2, r5.y - 3.5)
    check("A 20 cm do ponto: gira, anda o resto e chega (P5)",
          ok and m5.resultado and m5.resultado["ok"] and d5 < 0.15,
          f"{d5 * 100:.0f} cm — {m5.resultado and m5.resultado['texto']}")

    from slam.missao import Missao, malha_da_missao
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


def test_chegada_base():
    section("15. MISSÃO — chegar à base alinhado e conferir depois do giro final (30/09)")
    ESC = 0.11 / 174.0                     # o escorregar medido: 11 cm em 174°
    BASE = (3.0, 3.5, 0.0)

    # B: o robô está À FRENTE da base, virado para ela — direto, chegaria de
    # costas para o rumo da fita (giro final de ~180°).
    mis, robo, c, st, nav, tmp = montar_missao(x0=5.0, y0=3.5, rumo0=180.0, base=BASE)
    pts, _, _ = mis.planejar("base")
    aprox = (BASE[0] - S.MISSAO_APROX_BASE_M, BASE[1])
    check("Chegando torto: a rota passa pelo ponto de aproximação atrás da base",
          pts is not None and len(pts) >= 3
          and math.hypot(pts[-2][0] - aprox[0], pts[-2][1] - aprox[1]) < 0.01
          and tuple(pts[-1]) == (BASE[0], BASE[1]), f"{pts}")
    robo.escorrega_giro = ESC
    giros = []
    ult = {"rumo": robo.rumo, "fase": None}

    def mede_giro_final(t):
        m = mis.m
        if m and m.get("giro_rumo_final") is not None and ult["fase"] is None:
            ult["fase"] = robo.rumo
        if m is None and ult["fase"] is not None and not giros:
            giros.append(abs(normaliza_graus(robo.rumo - ult["fase"])))
    ir(mis, "base")
    rodar(mis, robo, c, 180, mede_giro_final)
    d = math.hypot(robo.x - BASE[0], robo.y - BASE[1])
    check("...e com o escorregar medido, chega a menos de 10 cm e alinhada (±5°)",
          mis.resultado["ok"] and d < 0.10 and abs(normaliza_graus(robo.rumo)) <= 5.0,
          f"{d * 100:.1f} cm, rumo {robo.rumo:.1f}° — {mis.resultado['texto']}")
    check("...e o giro final fica pequeno (< 30°)",
          giros and giros[0] < 30.0, f"giro final {giros[0] if giros else '?':.0f}°"
          if giros else "sem giro final medido")

    # Já alinhado atrás da base: vai direto, sem ponto extra.
    mis, robo, c, st, nav, tmp = montar_missao(x0=1.8, y0=3.5, rumo0=0.0, base=BASE)
    pts, _, _ = mis.planejar("base")
    check("Já vindo na direção da fita: rota direta (sem aproximação)",
          pts is not None and len(pts) == 2, f"{pts}")

    # Sem espaço para a aproximação (uma área em cima dela): vai direto.
    caixa = {"id": "cx", "nome": "caixa",
             "pontos": [[2.2, 3.2], [2.5, 3.2], [2.5, 3.8], [2.2, 3.8]]}
    mis, robo, c, st, nav, tmp = montar_missao(x0=5.0, y0=3.5, rumo0=180.0, base=BASE,
                                               areas=[caixa])
    pts, _, _ = mis.planejar("base")
    check("Aproximação bloqueada por área proibida → rota direta, sem atravessar a área",
          pts is not None and len(pts) == 2, f"{pts}")

    # O ponto a 60 cm na beira de uma margem (1ª prova, 30/09 12:30): usa um
    # mais perto da base, com folga.
    parede = {"id": "pw", "nome": "M4", "pontos": [[1.5, 2.8], [1.85, 2.8], [1.85, 4.2], [1.5, 4.2]]}
    mis, robo, c, st, nav, tmp = montar_missao(x0=5.0, y0=3.5, rumo0=180.0, base=BASE,
                                               areas=[parede])
    pts, _, _ = mis.planejar("base")
    check("Ponto a 60 cm sem folga da margem → usa o de 45 cm",
          pts is not None and len(pts) >= 3
          and math.hypot(pts[-2][0] - (BASE[0] - 0.45), pts[-2][1] - BASE[1]) < 0.01, f"{pts}")

    # A: sem a aproximação e escorregando MUITO no giro. Nunca pode dizer
    # "chegou" com o robô fora da tolerância.
    antigo = S.MISSAO_APROX_ALINHADO_DEG
    S.MISSAO_APROX_ALINHADO_DEG = 360.0          # desliga a B só neste teste
    try:
        for esc, rot in ((ESC, "o escorregar medido"), (ESC * 3, "3× o escorregar")):
            mis, robo, c, st, nav, tmp = montar_missao(x0=5.0, y0=3.5, rumo0=180.0, base=BASE)
            robo.escorrega_giro = esc
            ir(mis, "base")
            rodar(mis, robo, c, 240)
            d = math.hypot(robo.x - BASE[0], robo.y - BASE[1])
            honesto = (mis.resultado["ok"] and d <= S.MISSAO_CHEGADA_BASE_M + 0.02) or \
                      (not mis.resultado["ok"] and "perto" in mis.resultado["texto"])
            check(f"Sem a B, com {rot}: confere depois do giro final e diz a verdade",
                  honesto, f"{d * 100:.1f} cm — {mis.resultado['texto']}")
        # Escorregar absurdo: a correção também escorrega. Tem que encerrar
        # dizendo a distância, e não "chegou".
        mis, robo, c, st, nav, tmp = montar_missao(x0=5.0, y0=3.5, rumo0=180.0, base=BASE)
        robo.escorrega_giro = ESC * 20
        ir(mis, "base")
        rodar(mis, robo, c, 240)
        d = math.hypot(robo.x - BASE[0], robo.y - BASE[1])
        check("Escorregando 20× o medido: a correção também escorrega → encerra 'parou perto', sem fingir",
              not mis.resultado["ok"] and "perto" in mis.resultado["texto"]
              and d > S.MISSAO_CHEGADA_BASE_M and mis.fala["grupo"] == "missao_perto",
              f"{d * 100:.1f} cm — {mis.resultado['texto']}")
    finally:
        S.MISSAO_APROX_ALINHADO_DEG = antigo


def test_malha_da_missao():
    section("16. A malha de rumo DA MISSÃO — a costura (30/09/2026)")
    from slam.missao import malha_da_missao
    from core.heading_assist import HeadingAssist
    antiga = dict(kp_pct=S.HEADING_KP_PCT, ki_pct=S.HEADING_KI_PCT,
                  max_corr_pct=S.HEADING_MAX_CORR_PCT, invert=S.HEADING_INVERT,
                  tol_pct=S.HEADING_STRAIGHT_TOL_PCT, teto_pct=S.MOTOR_MAX_POWER_PCT,
                  limite_integral=S.HEADING_INTEGRAL_MAX, trim_pct=S.HEADING_TRIM_PCT,
                  enabled=True)

    def reta(malha, erros, dt=0.02, base=12.0):
        """Roda a malha com uma sequência de erros de rumo (graus, BNO)."""
        malha.soltar()
        malha.corrigir(base, base, 0.0, True, dt)             # trava a referência em 0
        saidas = []
        for e in erros:
            saidas.append(malha.corrigir(base, base, e, True, dt))
        return saidas

    # O que o traço de 30/09 mostrou: erro subindo a 17° e ficando lá 2 s.
    subida = [17.0 * min(1.0, k / 100) for k in range(250)]
    nova = malha_da_missao(S)
    out = reta(nova, subida)
    lenta = min(min(e, d) for e, d in out)
    rapida = max(max(e, d) for e, d in out)
    check("Missão: com erro grande, a roda lenta NUNCA desce de 8% e a rápida não passa de 12%",
          lenta >= S.MISSAO_RODA_MIN_PCT - 1e-9 and rapida <= S.MISSAO_TETO_PCT + 1e-9,
          f"roda lenta {lenta:.1f}%, rápida {rapida:.1f}%")
    velha = HeadingAssist(**antiga)
    out_v = [(min(e, S.MISSAO_TETO_PCT), min(d, S.MISSAO_TETO_PCT)) for e, d in reta(velha, subida)]
    check("...e o jeito antigo (teto 15% e corte em 12% depois) levava a roda lenta a 3%",
          min(min(e, d) for e, d in out_v) <= 3.5,
          f"{min(min(e, d) for e, d in out_v):.1f}%")

    # Integração condicional: saturada por 3 s, o integral não enche.
    nova2 = malha_da_missao(S)
    reta(nova2, [17.0] * 150)
    check("Missão: saturada na direção do erro, o integral NÃO carrega",
          abs(nova2._integral) < 1.0, f"integral {nova2._integral:.1f} graus·s")
    velha2 = HeadingAssist(**antiga)
    reta(velha2, [17.0] * 150)
    check("...o jeito antigo enchia até o limite (24 graus·s = 6% sozinho)",
          abs(velha2._integral) >= S.HEADING_INTEGRAL_MAX - 1e-6, f"{velha2._integral:.1f}")

    # Depois do pico, o erro vira: quanto tempo a correção segue empurrando
    # para o lado antigo? (é o que leva o robô ao outro lado)
    def empurra_errado(malha):
        seq = [17.0] * 150 + [-3.0] * 150
        out = reta(malha, seq)
        return sum(1 for e, d in out[150:] if (d - e) > 0) * 0.02
    t_nova = empurra_errado(malha_da_missao(S))
    t_velha = empurra_errado(HeadingAssist(**antiga))
    check("Erro invertido: a correção da missão acompanha na hora; a antiga seguia empurrando",
          t_nova <= 0.1 and t_velha >= 1.0, f"missão {t_nova:.2f} s × antiga {t_velha:.2f} s")

    # A malha do JOYSTICK (Fase 3) não mudou: sem as opções novas, a saída é
    # a mesma fórmula de sempre.
    j = HeadingAssist(**antiga)
    out_j = reta(j, [5.0] * 50, base=15.0)
    integ = 5.0 * 0.02 * 50
    corr = min(S.HEADING_MAX_CORR_PCT, S.HEADING_TRIM_PCT + S.HEADING_KP_PCT * 5.0
               + S.HEADING_KI_PCT * min(integ, S.HEADING_INTEGRAL_MAX))
    esp = (15.0 - corr, 15.0 + corr)
    pico = max(esp)
    if pico > S.MOTOR_MAX_POWER_PCT:
        esp = (esp[0] - (pico - S.MOTOR_MAX_POWER_PCT), S.MOTOR_MAX_POWER_PCT)
    check("A malha do joystick (Fase 3) segue idêntica",
          abs(out_j[-1][0] - esp[0]) < 1e-6 and abs(out_j[-1][1] - esp[1]) < 1e-6,
          f"{out_j[-1]} × {esp}")


def test_pulsos_regulados():
    section("17. MISSÃO — pulsos de giro que sobem de força quando não rendem (30/09)")
    pois = [{"nome": "lado", "x": 2.0, "y": 5.3, "rumo": None}]    # 90° à esquerda

    # Piso normal: os pulsos ficam em 8%.
    mis, robo, c, st, nav, tmp = montar_missao(pois=pois)
    ir(mis, "lado")
    rodar(mis, robo, c, 60)
    h = json.loads(open(os.path.join(tmp, "missoes.jsonl"), encoding="utf-8").read().splitlines()[-1])
    check("Piso normal: chega e os pulsos NÃO sobem de força",
          mis.resultado["ok"] and h.get("giro_pct_max") is None,
          f"{mis.resultado['texto']} · giro_pct_max={h.get('giro_pct_max')}")

    # Piso pesado: abaixo de 9,5% o robô não gira no lugar.
    mis, robo, c, st, nav, tmp = montar_missao(pois=pois)
    robo.giro_min_pct = 9.5
    ir(mis, "lado")
    rodar(mis, robo, c, 90)
    d = math.hypot(robo.x - 2.0, robo.y - 5.3)
    h = json.loads(open(os.path.join(tmp, "missoes.jsonl"), encoding="utf-8").read().splitlines()[-1])
    check("Piso pesado: os pulsos sobem até vencer, e a missão chega",
          mis.resultado["ok"] and d < 0.15 and (h.get("giro_pct_max") or 0) >= 10.0,
          f"{d * 100:.0f} cm — {mis.resultado['texto']} · giro_pct_max={h.get('giro_pct_max')}")
    check("...nunca acima do teto da missão (12%)", robo.maior <= S.MISSAO_TETO_PCT + 1e-9,
          f"máx {robo.maior:.1f}%")
    check("...e o histórico registra a força que o giro precisou (o sintoma não some)",
          h.get("giro_pct_max") is not None)

    # Mais pesado que o teto, num giro pequeno (vai direto aos pulsos, como o
    # acerto final de 30/09): desiste do jeito certo, dizendo até onde subiu.
    mis, robo, c, st, nav, tmp = montar_missao(
        rumo0=15.0, pois=[{"nome": "reto", "x": 4.0, "y": 3.5, "rumo": None}])
    robo.giro_min_pct = 13.0
    ir(mis, "reto")
    rodar(mis, robo, c, 120)
    check("Nem 12% vence: cancela (não retoma) e diz a força usada",
          not mis.resultado["ok"] and "força até 12%" in mis.resultado["texto"]
          and robo.maior <= S.MISSAO_TETO_PCT + 1e-9, mis.resultado["texto"])


def test_vigia_do_giro():
    section("18. MISSÃO — a vigia BNO × Aurora no giro, sem alarme falso (30/09)")
    from slam.missao import GIRAR

    def preparar():
        mis, robo, c, st, nav, tmp = montar_missao(
            pois=[{"nome": "frente", "x": 4.0, "y": 3.5, "rumo": None}])
        ir(mis, "frente")
        mis.tick(0.02)                                   # a missão começa
        m = mis.m
        p0 = Pose(robo.x, robo.y, 10.0, c())
        mis._marcar_fase(GIRAR, p0, 50.0)                # BNO 50°, Aurora 10°
        m["giro_modo"] = "continuo"
        return mis, robo, c, m

    def alimentar(mis, c, seq):
        """seq = [(bno, rumo_aurora)], um por ciclo de 20 ms."""
        for bno, rumo in seq:
            c.anda(0.02)
            v = mis._vigias(Pose(2.0, 3.5, rumo, c()), bno)
            if v:
                return v[0]
        return None

    # 1) Giro de 185° à esquerda (Aurora +, BNO −), o Aurora 0,3 s atrasado.
    mis, robo, c, m = preparar()
    seq = []
    for k in range(1, 186):
        seq.append((50.0 - k, 10.0 + max(0, k - 15)))
    for _ in range(15):
        seq.append((50.0 - 185, 10.0 + 185))
    r = alimentar(mis, c, [(normaliza_graus(b), normaliza_graus(a)) for b, a in seq])
    check("Giro de 185°: passar por ±180° NÃO vira 'sentidos opostos'", r is None, str(r))

    # 2) "Espera" logo depois do giro contínuo, robô ainda girando por inércia
    #    e o Aurora atrasado 15°: não é hora de comparar.
    mis, robo, c, m = preparar()
    m["giro_modo"] = "espera"
    seq = [(50.0 - k, 10.0 + max(0, k - 15)) for k in range(1, 60)]
    r = alimentar(mis, c, [(normaliza_graus(b), normaliza_graus(a)) for b, a in seq])
    check("Ainda girando por inércia (Aurora 15° atrás): NÃO compara, não acusa", r is None, str(r))
    #    Parou de verdade e o Aurora alcançou: compara, e bate.
    seq = [(50.0 - 59, 10.0 + 59)] * 50
    r = alimentar(mis, c, [(normaliza_graus(b), normaliza_graus(a)) for b, a in seq])
    check("...parado e o Aurora alcançou: compara e bate (sem alarme)", r is None, str(r))

    # 3) A vigia continua pegando o que deve: parado, discordando 15°.
    mis, robo, c, m = preparar()
    m["giro_modo"] = "espera"
    seq = [(50.0 - k, 10.0 + k) for k in range(1, 41)] + [(50.0 - 40, 10.0 + 55)] * 50
    r = alimentar(mis, c, [(normaliza_graus(b), normaliza_graus(a)) for b, a in seq])
    check("Parado e discordando 15° → cancela ('discordam')", r and "discordam" in r, str(r))

    # 4) ...e o sinal trocado de verdade (espiral): cancela girando.
    mis, robo, c, m = preparar()
    seq = [(50.0 - k, 10.0 - k) for k in range(1, 40)]
    r = alimentar(mis, c, [(normaliza_graus(b), normaliza_graus(a)) for b, a in seq])
    check("BNO e Aurora girando para lados opostos → cancela na hora", r and "opostos" in r, str(r))

    # 5) Giro de 180° de ponta a ponta no robô de mentira com a inércia da
    #    sala (antes: "discordam (+165° × +155°)").
    mis, robo, c, st, nav, tmp = montar_missao(
        x0=5.0, y0=3.5, rumo0=0.0, pois=[{"nome": "atras", "x": 3.0, "y": 3.5, "rumo": None}])
    robo.tau_giro = 1.0
    ir(mis, "atras")
    rodar(mis, robo, c, 90)
    check("Meia-volta com inércia: chega, sem alarme falso",
          mis.resultado["ok"], mis.resultado["texto"])

    # 6) Robô que só começa a girar depois de a força subir: não é "travado".
    mis, robo, c, st, nav, tmp = montar_missao(
        pois=[{"nome": "lado", "x": 2.0, "y": 5.3, "rumo": None}])
    robo.giro_min_pct = 11.5              # só gira a partir de ~12%
    ir(mis, "lado")
    rodar(mis, robo, c, 90)
    check("Começo pesado (gira só perto de 12%): não cancela 'sem avanço' enquanto a força sobe",
          mis.resultado["ok"], mis.resultado["texto"])


def test_braco():
    section("14. O braço do Aurora — a pose é do CENTRO de giro (30/09/2026)")
    from sensors.pose_source import centro_do_robo, fita_do_centro
    B = S.AURORA_BRACO_M
    check("Braço medido no settings: 5,3 cm atrás e 7,2 cm à esquerda",
          B == (-0.053, 0.072), f"{B}")

    def sensor_de(cx, cy, rumo):
        """Onde o Aurora de verdade diria que está, com o centro em (cx, cy)."""
        a = math.radians(rumo)
        f, l = B
        return cx + f * math.cos(a) - l * math.sin(a), cy + f * math.sin(a) + l * math.cos(a)

    com, sem = [], []
    for g in range(0, 360, 10):
        sx, sy = sensor_de(1.0, 2.0, g)
        x, y = centro_do_robo(sx, sy, g, B)
        com.append(math.hypot(x - 1.0, y - 2.0))
        sem.append(math.hypot(sx - 1.0, sy - 2.0))
    check("Girando no lugar, o centro convertido NÃO anda (< 1 mm)",
          max(com) < 0.001, f"máx {max(com) * 1000:.2f} mm")
    check("Sem a conversão, o 'centro' anda ~9 cm num giro (o erro de antes)",
          0.08 < max(sem) < 0.10, f"{max(sem) * 100:.1f} cm")

    fc = fita_do_centro(S.AURORA_FITA, B)
    check("Fita convertida: mesmo rumo, deslocada exatamente |braço|",
          fc[2] == FR and abs(math.hypot(fc[0] - FX, fc[1] - FY) - math.hypot(*B)) < 1e-9,
          f"({fc[0]:.4f}, {fc[1]:.4f}, {fc[2]})")

    # De ponta a ponta: AuroraPose com o Aurora de mentira reportando o PONTO
    # DO SENSOR, como o de verdade. A partida confere com a fita do centro.
    tmp = tempfile.mkdtemp(prefix="fase4_braco_")
    mapa = os.path.join(tmp, "mapa.stcm")
    with open(mapa, "wb") as f:
        f.write(b"mapa de mentira")
    sha = sha256_arquivo(mapa)
    m = Mundo()
    sx, sy = sensor_de(fc[0], fc[1], FR)
    m.reloc_pose = (sx, sy, FR)                 # robô exatamente na fita
    a = fonte(m, mapa, sha, fita=fc, braco_m=B)
    a.start()
    try:
        esperar(lambda: a.health()["conectado"])
        time.sleep(0.2)
        a.pedir_partida(lambda: True)
        h = a.health() if fim_da_partida(a) else {}
        check("Partida na fita com o braço → VERDE e a pose sai no CENTRO",
              str(a.partida["resultado"]).startswith("ok")
              and esperar(lambda: a.health()["valida"])
              and abs(a.health()["x_cm"] - fc[0] * 100) < 0.5
              and abs(a.health()["y_cm"] - fc[1] * 100) < 0.5,
              f"{a.partida['resultado']} · x={a.health()['x_cm']} y={a.health()['y_cm']}")

        desvios = []
        for g in range(5, 365, 5):                 # uma volta, 5° por leitura
            rumo = FR + g
            px, py = sensor_de(fc[0], fc[1], rumo)
            with m.lock:
                m.x, m.y, m.rumo = px, py, rumo
            esperar(lambda: abs(normaliza_graus(a.health()["rumo_deg"] - rumo)) < 0.2, 1.0)
            p = a.pose_valida()
            if p is None:
                desvios.append(None)
                continue
            desvios.append(math.hypot(p.x_m - fc[0], p.y_m - fc[1]))
        ok = all(d is not None for d in desvios)
        check("Uma volta no lugar: a pose do centro fica parada (< 1 cm) e sempre válida",
              ok and max(desvios) < 0.01,
              f"máx {max(d for d in desvios if d is not None) * 100:.2f} cm, "
              f"{sum(d is None for d in desvios)} inválidas")
    finally:
        a.stop()


# ─────────────────────────────────────────────
# 19. AMBIENTES (pacote de ambiente, Etapa A — decidido em 02/10/2026)
# docs/PRD.md §0 e §7; página https://claude.ai/artifact/3cqZvZGfP4wXKzLiudAaUJ
# ─────────────────────────────────────────────
def _pacote(raiz, pid, *, nome=None, mapa=b"MAPA-A", sha_ficha=None, planta=True,
            sha_planta=None, fita=(1.0, 2.0, 90.0), arquivado=False, desenho=True):
    """Escreve um pacote de ambiente de mentira em raiz/pid."""
    import hashlib
    p = os.path.join(raiz, pid)
    os.makedirs(os.path.join(p, "nav"), exist_ok=True)
    sha = hashlib.sha256(mapa).hexdigest() if mapa is not None else "f" * 64
    if mapa is not None:
        with open(os.path.join(p, "mapa.stcm"), "wb") as f:
            f.write(mapa)
    if planta:
        with open(os.path.join(p, "planta.json"), "w", encoding="utf-8") as f:
            json.dump({"mapa_sha256": sha_planta or sha, "res": 0.05, "min_x": -5.0,
                       "max_y": 5.0, "largura_px": 200, "altura_px": 200,
                       "eixo_paredes_deg": 0.0, "paredes": []}, f)
    if desenho:                       # B5: o desenho já foi salvo uma vez
        with open(os.path.join(p, "nav", "nav.json"), "w", encoding="utf-8") as f:
            json.dump({"versao": 1, "quando": "2026-10-02 10:00:00", "quem": "harness",
                       "mapa_sha256": sha, "areas": [], "pois": []}, f)
    with open(os.path.join(p, "ficha.json"), "w", encoding="utf-8") as f:
        json.dump({"id": pid, "nome": nome or pid, "criado": "2026-10-02 10:00:00",
                   "quem": "harness", "mapa_sha256": sha_ficha or sha,
                   "fita": list(fita) if fita else None, "arquivado": arquivado}, f)
    return sha


def test_ambientes():
    section("19. AMBIENTES — escolher e trocar o pacote de ambiente (Etapa A, 02/10)")
    try:
        from slam.ambientes import Ambientes, resolver, migrar
    except ImportError as e:
        check("slam/ambientes.py existe", False, str(e))
        return
    raiz = os.path.join(tempfile.mkdtemp(prefix="fase4_amb_"), "ambientes")
    amb = Ambientes(raiz)
    check("Sem a pasta de ambientes: existe() = False e nenhum ativo",
          not amb.existe() and amb.ativo() is None)

    sha_sala = _pacote(raiz, "sala", nome="Sala do lab", mapa=b"SALA")
    _pacote(raiz, "corredor", mapa=b"CORREDOR", fita=None)
    _pacote(raiz, "semplanta", mapa=b"SP", planta=False)
    _pacote(raiz, "plantaerrada", mapa=b"PE", sha_planta="b" * 64)
    _pacote(raiz, "trocado", mapa=b"OUTRO", sha_ficha="c" * 64)
    _pacote(raiz, "semmapa", mapa=None)
    _pacote(raiz, "velho", mapa=b"VELHO", arquivado=True)
    os.makedirs(os.path.join(raiz, "lixo"), exist_ok=True)   # pasta sem ficha

    def est(pid):
        return amb.avaliar(pid)
    check("Pacote completo (sha, planta do mesmo sha, fita) → PRONTO",
          est("sala")["estado"] == "pronto" and est("sala")["motivos"] == [], str(est("sala")))
    e = est("corredor")
    check("Sem fita medida → RASCUNHO, dizendo 'fita'",
          e["estado"] == "rascunho" and any("fita" in m for m in e["motivos"]), str(e))
    e = est("semplanta")
    check("Sem planta → RASCUNHO, dizendo 'planta'",
          e["estado"] == "rascunho" and any("planta" in m for m in e["motivos"]), str(e))
    e = est("plantaerrada")
    check("Planta de outro mapa (sha) → RASCUNHO",
          e["estado"] == "rascunho" and any("planta" in m for m in e["motivos"]), str(e))
    e = est("trocado")
    check("Mapa que não confere com a ficha (sha) → INVÁLIDO",
          e["estado"] == "invalido" and any("sha" in m for m in e["motivos"]), str(e))
    check("Mapa ausente → INVÁLIDO", est("semmapa")["estado"] == "invalido")
    check("Pasta sem ficha → INVÁLIDO, sem exceção", est("lixo")["estado"] == "invalido")
    check("Pacote arquivado aparece como arquivado", est("velho")["arquivado"] is True)
    check("Nome com '..' ou barra é recusado (não sai da pasta)",
          est("../fora")["estado"] == "invalido" and est("a/b")["estado"] == "invalido")

    contas = {"n": 0}

    def sha_contado(c):
        contas["n"] += 1
        return sha256_arquivo(c)
    amb2 = Ambientes(raiz, sha_fn=sha_contado)
    amb2.listar(); n1 = contas["n"]; amb2.listar()
    check("O sha de cada mapa é calculado uma vez (o .stcm tem até 60 MB)",
          n1 > 0 and contas["n"] == n1, f"{n1} → {contas['n']}")

    # ─── o ambiente ativo ───
    check("Pasta existe mas sem ativo.json → nenhum ativo", amb.ativo() is None)
    livre = dict(missao_ativa=False, editando=False, andando=False)
    ok, msg = amb.pedir_troca("sala", "operador", **livre)
    a = amb.ativo()
    check("Trocar para um pacote pronto → aceito e ativo.json aponta para ele",
          ok and a and a["id"] == "sala" and a["estado"] == "pronto", msg)
    with open(os.path.join(raiz, "ativo.json"), encoding="utf-8") as f:
        reg = json.load(f)
    check("ativo.json guarda quem e quando", reg.get("quem") == "operador" and reg.get("quando"))
    check("ativo() traz os caminhos do pacote (mapa, sha, fita, planta, áreas)",
          a["mapa"].endswith(os.path.join("sala", "mapa.stcm")) and a["mapa_sha256"] == sha_sala
          and tuple(a["fita"]) == (1.0, 2.0, 90.0)
          and a["planta_json"].endswith(os.path.join("sala", "planta.json"))
          and a["nav_dir"].endswith(os.path.join("sala", "nav")), str(a))
    lst = amb.listar()
    check("listar() traz todos os pacotes e marca o ativo",
          len(lst) == 8 and [p["id"] for p in lst if p["ativo"]] == ["sala"])

    antes = open(os.path.join(raiz, "ativo.json"), "rb").read()
    casos = [
        ("missão em curso", dict(livre, missao_ativa=True), "corredor", "missão"),
        ("editor de áreas aberto", dict(livre, editando=True), "corredor", "edi"),
        ("robô andando", dict(livre, andando=True), "corredor", "parado"),
        ("modo mapeamento", dict(livre, mapeando=True), "corredor", "mapeamento"),
        ("pacote inválido", livre, "trocado", "inválido"),
        ("pacote arquivado", livre, "velho", "arquivado"),
        ("pacote que não existe", livre, "nada", "não existe"),
        ("o mesmo que já está ativo", livre, "sala", "já"),
    ]
    for nome, kw, alvo, palavra in casos:
        ok, msg = amb.pedir_troca(alvo, "operador", **kw)
        check(f"Troca recusada: {nome} (diz o motivo)",
              not ok and palavra in msg.lower(), msg)
    check("Nenhuma troca recusada mexeu no ativo.json",
          open(os.path.join(raiz, "ativo.json"), "rb").read() == antes)
    ok, msg = amb.pedir_troca("corredor", "operador", **livre)
    check("Trocar para um RASCUNHO é permitido (para desenhar e medir a fita)",
          ok and amb.ativo()["id"] == "corredor", msg)

    with open(os.path.join(raiz, "ativo.json"), "w", encoding="utf-8") as f:
        f.write("{estragado")
    check("ativo.json estragado → nenhum ativo, sem exceção", amb.ativo() is None)
    with open(os.path.join(raiz, "ativo.json"), "w", encoding="utf-8") as f:
        json.dump({"id": "sumiu"}, f)
    check("ativo.json apontando para pacote que sumiu → nenhum ativo", amb.ativo() is None)
    amb.pedir_troca("sala", "operador", **livre)

    ok, msg = amb.arquivar("sala", "operador")
    check("Arquivar o pacote ATIVO → recusado", not ok and "ativo" in msg.lower(), msg)
    ok, msg = amb.arquivar("semplanta", "operador")
    check("Arquivar outro pacote → aceito, e ele continua no disco",
          ok and est("semplanta")["arquivado"]
          and os.path.isfile(os.path.join(raiz, "semplanta", "mapa.stcm")), msg)
    check("Não existe 'apagar' no painel (decisão 6)", not hasattr(amb, "apagar"))

    # ─── o que o serviço usa: resolver() ───
    LEG = {"mapa": "/legado/m.stcm", "mapa_sha256": "d" * 64, "fita": (0.1, 0.2, 30.0),
           "planta_json": "/legado/m_planta.json", "nav_dir": "/legado/nav"}
    r = resolver(Ambientes(os.path.join(raiz, "nao_existe")), LEG)
    check("Sem pasta de ambientes (antes da migração) → configuração antiga, missão permitida",
          r["mapa"] == LEG["mapa"] and r["missao_motivo"] is None
          and r["ambiente"]["estado"] == "legado")
    r = resolver(amb, LEG)
    check("Ambiente PRONTO ativo → caminhos do pacote, missão permitida",
          r["mapa_sha256"] == sha_sala and r["missao_motivo"] is None
          and r["ambiente"]["id"] == "sala" and r["ambiente"]["nome"] == "Sala do lab")
    amb.pedir_troca("corredor", "operador", **livre)
    r = resolver(amb, LEG)
    check("Ambiente RASCUNHO ativo → missão indisponível, dizendo por quê",
          bool(r["missao_motivo"]) and "rascunho" in r["missao_motivo"] and r["fita"] is None,
          str(r["missao_motivo"]))
    os.remove(os.path.join(raiz, "ativo.json"))
    r = resolver(amb, LEG)
    check("Pasta existe mas nenhum ativo → missão indisponível, sem mapa (não cai no legado)",
          r["mapa"] is None and bool(r["missao_motivo"]) and r["ambiente"]["estado"] == "nenhum")

    # ─── as peças aceitam um ambiente sem fita ───
    v = PoseValidator(fita=None, fita_tol_m=0.15, fita_tol_deg=5.0, max_idade_s=0.5,
                      salto_m=0.25, salto_deg=15.0, estavel_s=1.0, aquecimento_s=1.0)
    ok, msg = v.on_localizou(Pose(0.0, 0.0, 0.0, time.monotonic()))
    check("Validador sem fita: nunca aceita a localização ('fita não medida')",
          not ok and "fita" in msg, msg)
    from sensors.pose_source import fita_do_centro
    check("fita_do_centro(None) → None", fita_do_centro(None, (-0.05, 0.07)) is None)
    ap = AuroraPose(ip="0.0.0.0", mapa=None, mapa_sha256=None, validator=v)
    ap._conectado = True
    ok, msg = ap.pedir_partida(lambda: True)
    check("'Localizar na fita' recusado sem mapa válido / sem fita",
          not ok and ("fita" in msg or "ambiente" in msg), msg)

    mis, _r, _c, _st, nav_m, _t = montar_missao(pois=[{"nome": "mesa9", "x": 3.0, "y": 3.5}])
    mis.indisponivel = "ambiente Corredor é rascunho: fita não medida"
    ok, msg = mis.iniciar("base", "operador", None)
    check("Missão indisponível no rascunho: recusa com o motivo do ambiente",
          not ok and "rascunho" in msg, msg)
    # Achado na bancada de 02/10 (12:16): no Corredor, "ver rota" de um POI
    # salvo dizia "POI não encontrado no desenho salvo" em vez do motivo.
    from core.motor_driver import MotorDriver
    from web.server import create_app
    cr = create_app(motors=MotorDriver(), state={"robot_id": 1}, nav=nav_m,
                    missao=mis).test_client()
    cr.post("/login", data={"usuario": "operador", "senha": _SENHA})
    r = cr.get("/api/nav/rota?poi=mesa9")
    j = r.get_json() or {}
    check("Ver rota no rascunho: diz o motivo do ambiente, não 'POI não encontrado'",
          r.status_code == 409 and "rascunho" in j.get("motivo", ""), f"{r.status_code} {j}")

    # ─── áreas e POIs são de cada pacote ───
    from slam.mapa_nav import NavStore
    _pacote(raiz, "sala2", mapa=b"SALA2")
    s1 = amb.avaliar("sala"); s2 = amb.avaliar("sala2")
    n1 = NavStore(os.path.join(raiz, "sala", "nav"), s1["mapa_sha256"], 0.5,
                  planta_json=os.path.join(raiz, "sala", "planta.json"))
    ok, _ = n1.salvar({"mapa_sha256": s1["mapa_sha256"], "areas": [],
                       "pois": [{"nome": "mesa1", "x": 0.0, "y": 0.0}]}, "operador",
                      n1.carregar()["versao"])
    n2 = NavStore(os.path.join(raiz, "sala2", "nav"), s2["mapa_sha256"], 0.5,
                  planta_json=os.path.join(raiz, "sala2", "planta.json"))
    check("POIs salvos num ambiente não aparecem no outro",
          ok and n1.poi("mesa1") and n2.poi("mesa1") is None)

    # ─── dashboard ───
    from core.motor_driver import MotorDriver
    from web.server import create_app
    amb.pedir_troca("sala", "operador", **livre)
    reinicios = []

    class _Mis:
        ativa = False

    class _Nav:
        def editando(self):
            return False
    mis_web = _Mis()
    app = create_app(motors=MotorDriver(), state={"robot_id": 1}, nav=_Nav(), missao=mis_web,
                     parado_fn=lambda: True, ambientes=amb,
                     reiniciar_fn=lambda: reinicios.append(1))
    cl = app.test_client()
    check("GET /ambientes sem login → vai para o login",
          cl.get("/ambientes").status_code in (301, 302))
    check("GET /api/ambientes sem login → 401", cl.get("/api/ambientes").status_code == 401)
    r = cl.post("/api/ambientes/usar", json={"id": "corredor"})
    check("POST /api/ambientes/usar sem login → 401, nada muda, não reinicia",
          r.status_code == 401 and amb.ativo()["id"] == "sala" and not reinicios)
    cl.post("/login", data={"usuario": "operador", "senha": _SENHA})
    check("GET /ambientes com login → 200", cl.get("/ambientes").status_code == 200)
    d = cl.get("/api/ambientes").get_json()
    check("/api/ambientes lista os pacotes com estado e o ativo (sem caminhos do disco)",
          d["ok"] and d["ativo"] == "sala"
          and {p["id"]: p["estado"] for p in d["pacotes"]}.get("corredor") == "rascunho"
          and all("mapa" not in p for p in d["pacotes"]))
    mis_web.ativa = True
    r = cl.post("/api/ambientes/usar", json={"id": "corredor"})
    check("Com missão em curso → 409 e não reinicia",
          r.status_code == 409 and not reinicios and amb.ativo()["id"] == "sala")
    mis_web.ativa = False
    r = cl.post("/api/ambientes/usar", json={"id": "corredor"})
    check("Troca aceita → 200, ativo.json muda e o serviço é reiniciado (decisão 7)",
          r.status_code == 200 and amb.ativo()["id"] == "corredor" and reinicios == [1])
    r = cl.post("/api/ambientes/arquivar", json={"id": "plantaerrada"})
    check("Arquivar pelo painel → 200", r.status_code == 200 and est("plantaerrada")["arquivado"])
    st = create_app(motors=MotorDriver(), state={
        "robot_id": 1, "ambiente": {"id": "sala", "nome": "Sala", "estado": "pronto"}}
    ).test_client()
    st.post("/login", data={"usuario": "operador", "senha": _SENHA})
    check("/api/status leva o ambiente ativo",
          (st.get("/api/status").get_json().get("ambiente") or {}).get("id") == "sala")

    # ─── a migração (uma vez, na Pi) ───
    import hashlib
    base = tempfile.mkdtemp(prefix="fase4_mig_")
    os.makedirs(os.path.join(base, "mapas"))
    leg_mapa = os.path.join(base, "mapas", "lab.stcm")
    with open(leg_mapa, "wb") as f:
        f.write(b"LAB")
    sha_lab = hashlib.sha256(b"LAB").hexdigest()
    with open(os.path.join(base, "mapas", "lab_planta.json"), "w", encoding="utf-8") as f:
        json.dump({"mapa_sha256": sha_lab, "res": 0.05, "min_x": -5, "max_y": 5,
                   "largura_px": 200, "altura_px": 200}, f)
    with open(os.path.join(base, "mapas", "lab_planta.png"), "wb") as f:
        f.write(b"PNG")
    leg_nav = os.path.join(base, "navegacao")
    os.makedirs(os.path.join(leg_nav, "historico"))
    with open(os.path.join(leg_nav, "nav.json"), "w", encoding="utf-8") as f:
        json.dump({"versao": 7, "mapa_sha256": sha_lab, "areas": [], "pois": []}, f)
    with open(os.path.join(leg_nav, "historico", "nav_v0006.json"), "w") as f:
        f.write("{}")
    with open(os.path.join(leg_nav, "missoes.jsonl"), "w") as f:     # é do robô
        f.write("{}")
    os.makedirs(os.path.join(leg_nav, "tracos"))
    cor_mapa = os.path.join(base, "mapas", "cor.stcm")
    with open(cor_mapa, "wb") as f:
        f.write(b"COR")
    legado = {"id": "sala_lab", "nome": "Sala do lab", "mapa": leg_mapa,
              "mapa_sha256": sha_lab,
              "planta_json": os.path.join(base, "mapas", "lab_planta.json"),
              "nav_dir": leg_nav, "fita": (-0.343, 0.1277, 126.8)}
    extras = [{"id": "corredor", "nome": "Corredor", "mapa": cor_mapa,
               "mapa_sha256": hashlib.sha256(b"COR").hexdigest(), "planta_json": None,
               "nav_dir": None, "fita": None}]
    raiz_m = os.path.join(base, "ambientes")
    mtime = os.path.getmtime(leg_mapa)
    migrar(raiz_m, legado, extras)
    am = Ambientes(raiz_m)
    check("Migração: a sala vira pacote PRONTO e fica ativa",
          am.avaliar("sala_lab")["estado"] == "pronto" and (am.ativo() or {}).get("id") == "sala_lab")
    nv = json.load(open(os.path.join(raiz_m, "sala_lab", "nav", "nav.json"), encoding="utf-8"))
    check("Migração: áreas/POIs (versão 7) e histórico vêm junto",
          nv["versao"] == 7 and os.path.isfile(
              os.path.join(raiz_m, "sala_lab", "nav", "historico", "nav_v0006.json")))
    check("Migração: o registro de missões e os traços NÃO vão (são do robô)",
          not os.path.exists(os.path.join(raiz_m, "sala_lab", "nav", "missoes.jsonl"))
          and not os.path.exists(os.path.join(raiz_m, "sala_lab", "nav", "tracos")))
    check("Migração: a planta vai junto (png também)",
          os.path.isfile(os.path.join(raiz_m, "sala_lab", "planta.png")))
    check("Migração: o corredor vira RASCUNHO (sem fita, sem planta)",
          am.avaliar("corredor")["estado"] == "rascunho")
    check("Migração COPIA: os arquivos antigos ficam onde estavam",
          os.path.isfile(leg_mapa) and os.path.getmtime(leg_mapa) == mtime
          and os.path.isfile(os.path.join(leg_nav, "nav.json")))
    ficha1 = open(os.path.join(raiz_m, "sala_lab", "ficha.json"), "rb").read()
    am.pedir_troca("corredor", "operador", **livre)
    migrar(raiz_m, legado, extras)
    check("Rodar a migração de novo não muda nada (nem o ativo)",
          open(os.path.join(raiz_m, "sala_lab", "ficha.json"), "rb").read() == ficha1
          and Ambientes(raiz_m).ativo()["id"] == "corredor")
    try:
        migrar(raiz_m, dict(legado, mapa_sha256="e" * 64, id="outra"), [])
        check("Migração recusa mapa cujo sha não confere", False)
    except ValueError:
        check("Migração recusa mapa cujo sha não confere", True)

    # ─── fiação e Regra Nº 0 ───
    src_amb = open(os.path.join(_ROOT, "slam", "ambientes.py"), encoding="utf-8").read()
    check("slam/ambientes.py não move o robô (sem set_speed/GPIO)",
          "set_speed" not in src_amb and "GPIO" not in src_amb)
    src_main = open(os.path.join(_ROOT, "main.py"), encoding="utf-8").read()
    check("main.py monta mapa, fita, planta e áreas a partir do ambiente ativo",
          "resolver(" in src_main and "ambientes=" in src_main and "reiniciar_fn=" in src_main)
    corpo_tel = src_main.split("def _fleet_telemetry_loop")[1].split("\ndef ")[0]
    check("A telemetria da frota leva o ambiente (a Torre mostra)", '"ambiente"' in corpo_tel)
    src_pl = open(os.path.join(_HERE, "aurora_planta.py"), encoding="utf-8").read()
    check("aurora_planta.py grava dentro do pacote (--pacote), nunca ao lado do mapa antigo",
          "--pacote" in src_pl and "AURORA_MAPA" not in src_pl)


# ─────────────────────────────────────────────
# 20. MAPEAR PELO PAINEL (pacote de ambiente, Etapa B.1 — 02/10/2026)
# Plano: https://claude.ai/artifact/8mDpKzRHV1WqzmXmnJATYj
# ─────────────────────────────────────────────
def test_mapeamento():
    section("20. MAPEAR PELO PAINEL — os passos e o Aurora (Etapa B.1, 02/10)")
    try:
        from slam.mapeamento import Mapeamento
        from slam.ambientes import Ambientes
    except ImportError as e:
        check("slam/mapeamento.py existe", False, str(e))
        return
    import hashlib
    from sensors.pose_source import fita_do_centro

    raiz = os.path.join(tempfile.mkdtemp(prefix="fase4_map_"), "ambientes")
    sha_sala = _pacote(raiz, "sala", nome="Sala", mapa=b"SALA", fita=(FX, FY, FR))
    amb = Ambientes(raiz)
    livre = dict(missao_ativa=False, editando=False, andando=False)
    amb.pedir_troca("sala", "operador", **livre)
    vd = os.path.join(os.path.dirname(raiz), "varreduras")

    BR = (-0.053, 0.072)
    m = Mundo()
    m.reloc_pose = (1.20, -0.40, 35.0)          # onde a fita do lugar novo fica no mapa novo
    m.mapa_novo = b"MAPA-NOVO-DO-CORREDOR"
    plantas = []

    def planta_fake(sdk, destino_base, mapa_sha, nome):
        plantas.append(destino_base)
        with open(destino_base + ".json", "w", encoding="utf-8") as f:
            json.dump({"mapa_sha256": mapa_sha, "res": 0.05, "min_x": -5, "max_y": 5,
                       "largura_px": 200, "altura_px": 200}, f)
        with open(destino_base + ".png", "wb") as f:
            f.write(b"PNG")
        return {"mapa_sha256": mapa_sha}
    a = fonte(m, os.path.join(raiz, "sala", "mapa.stcm"), sha_sala,
              fita=fita_do_centro((FX, FY, FR), BR), braco_m=BR)
    a.start()
    esperar(lambda: a._conectado)

    imp = {"msg": None}
    parado = {"v": True}
    disco = {"mb": 50_000}
    c = Relogio()
    def gerador_fake(pasta):               # o slam/mapa_c1 de mentira: planta + resumo
        sha_f = json.load(open(os.path.join(pasta, "ficha.json"), encoding="utf-8"))["mapa_sha256"]
        planta_fake(None, os.path.join(pasta, "planta"), sha_f, "x")
        return {"planta": True}
    mp = Mapeamento(raiz, a, impedimentos_fn=lambda: imp["msg"],
                    parado_fn=lambda: parado["v"], varreduras_dir=vd, clock=c,
                    livre_mb_fn=lambda: disco["mb"], fita_tol=(0.02, 1.0),
                    aviso_m=0.05, min_coletas=2, laser_coleta_s=1.0,
                    gerar_mapas_fn=gerador_fake)

    def ate(fases, limite=5.0):
        ok = esperar(lambda: (mp.tick() or True) and mp.estado()["fase"] in fases, limite)
        return ok

    # ─── antes de começar ───
    check("Sem mapeamento: nenhum passo anda (concluir passada 1 recusado)",
          not mp.concluir_mapa("operador")[0] and not mp.medir_fita("operador")[0]
          and not mp.iniciar_coleta("operador")[0] and not mp.concluir("operador")[0])
    check("Sem mapeamento: ativo = False", mp.ativo is False)

    for nome, prep, palavra in [
            ("missão em curso", lambda: imp.update(msg="há uma missão em curso"), "missão"),
            ("partida em andamento", lambda: imp.update(msg="a partida já está em andamento"), "partida"),
            ("robô andando", lambda: parado.update(v=False), "parado"),
            ("menos de 1 GB livre", lambda: disco.update(mb=500), "espaço")]:
        prep()
        ok, msg = mp.iniciar("Corredor 2", "operador")
        check(f"Começar recusado: {nome} (diz o motivo)", not ok and palavra in msg.lower(), msg)
        imp["msg"] = None; parado["v"] = True; disco["mb"] = 50_000
    ok, msg = mp.iniciar("", "operador")
    check("Começar sem nome → recusado", not ok, msg)
    ok, msg = mp.iniciar("Sala", "operador")
    check("Nome de um ambiente que já existe → recusado", not ok and "existe" in msg, msg)
    mp_sem = Mapeamento(raiz, None, impedimentos_fn=lambda: None, parado_fn=lambda: True,
                        varreduras_dir=vd, clock=c, livre_mb_fn=lambda: 50_000)
    ok, msg = mp_sem.iniciar("X", "operador")
    check("Robô sem Aurora → recusado", not ok and "aurora" in msg.lower(), msg)

    # ─── passada 1 ───
    ok, msg = mp.iniciar("Corredor 2", "operador")
    e = mp.estado()
    check("Começar: aceito, com id do nome + data", ok and e["id"].startswith("corredor_2_"), f"{msg} {e.get('id')}")
    pid = e["id"]
    check("A pasta parcial existe e NÃO aparece na lista de ambientes",
          os.path.isdir(os.path.join(raiz, pid + ".parcial")) and pid not in amb.ids())
    check("Zerou o Aurora para mapear → fase 'mapeando'",
          ate({"mapeando"}) and not m.mapa_carregado and a.modo_mapeamento, str(mp.estado()))
    check("Durante o mapeamento: mp.ativo = True", mp.ativo)
    ok, msg = a.pedir_partida(lambda: True)
    check("Durante o mapeamento: 'Localizar na fita' recusado (apagaria o mapa novo)",
          not ok and "mapeamento" in msg, msg)
    check("Ordem: medir a fita antes de salvar o mapa → recusado",
          not mp.medir_fita("operador")[0])
    check("Ordem: coletar antes de medir a fita → recusado",
          not mp.iniciar_coleta("operador")[0])
    ok, msg = mp.iniciar("Outro", "operador")
    check("Um mapeamento por vez", not ok, msg)

    parado["v"] = False
    ok, msg = mp.concluir_mapa("operador")
    check("Concluir passada 1 com o robô andando → recusado", not ok and "parado" in msg, msg)
    parado["v"] = True
    m.download_ok = False
    ok, msg = mp.concluir_mapa("operador")
    check("Download que falha: o passo volta para 'mapeando' e diz o erro",
          ok and ate({"mapeando"}) and "falh" in (mp.estado().get("erro") or ""),
          str(mp.estado()))
    m.download_ok = True
    ok, msg = mp.concluir_mapa("operador")
    check("Concluir passada 1 → 'mapa_salvo'", ok and ate({"mapa_salvo"}), str(mp.estado()))
    parcial = os.path.join(raiz, pid + ".parcial")
    sha_novo = hashlib.sha256(m.mapa_novo).hexdigest()
    check("O .stcm baixado foi gravado no pacote",
          open(os.path.join(parcial, "mapa.stcm"), "rb").read() == m.mapa_novo)
    # 02/10 17:00: gerar a planta pelo SDK DENTRO do serviço derrubou o
    # processo (SIGSEGV). Salvar agora é só o download; a planta vem da coleta.
    check("Salvar o mapa NÃO chama o SDK para a planta (SIGSEGV de 02/10)",
          not plantas and not os.path.exists(os.path.join(parcial, "planta.json")))

    # ─── medir a fita ───
    m.deriva = 0.01                                  # 1 cm por leitura: medidas discordam
    ok, msg = mp.medir_fita("operador")
    check("Medidas da fita que discordam → recusado, volta a 'mapa_salvo'",
          ok and ate({"mapa_salvo"}) and "discord" in (mp.estado().get("erro") or ""),
          str(mp.estado().get("erro")))
    m.deriva = 0.0
    ok, msg = mp.medir_fita("operador")
    check("Medir a fita → 'fita_medida'", ok and ate({"fita_medida"}), str(mp.estado()))
    ficha = json.load(open(os.path.join(parcial, "ficha.json"), encoding="utf-8"))
    f = ficha.get("fita") or [0, 0, 0]
    check("A fita gravada é o PONTO DO AURORA (convenção de sempre), não o centro",
          abs(f[0] - 1.20) < 0.002 and abs(f[1] + 0.40) < 0.002 and abs(f[2] - 35.0) < 0.2, str(f))
    check("Depois de medir, o robô está localizado no mapa novo (a coleta grava a pose)",
          a.pose_valida() is not None, a.motivo())

    # ─── coleta ───
    ok, msg = mp.concluir("operador")
    check("Concluir sem as 2 passadas de coleta → recusado", not ok and "2" in msg, msg)
    os.makedirs(vd, exist_ok=True)

    def grava(t, rotulo):
        ch = time.strftime("%Y-%m-%d/%H", time.localtime(t))
        p = os.path.join(vd, ch + ".jsonl")
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "a", encoding="utf-8") as fh:
            fh.write(json.dumps({"t": t, "rotulo": rotulo}) + "\n")
    grava(c() - 5, "antes")
    ok, _ = mp.iniciar_coleta("operador")
    check("Começar passada de coleta → 'coletando' e o laser do Aurora liga (1 s)",
          ok and mp.estado()["fase"] == "coletando" and a.laser_periodo_s == 1.0)
    c.anda(1); grava(c(), "p2"); c.anda(60); grava(c(), "p2"); c.anda(1)
    ok, _ = mp.terminar_coleta("operador")
    check("Terminar passada → laser desliga, 1 passada contada",
          ok and a.laser_periodo_s == 0 and len(mp.estado()["coletas"]) == 1)
    c.anda(10); grava(c(), "entre"); c.anda(1)
    mp.iniciar_coleta("operador"); c.anda(1); grava(c(), "p3"); c.anda(1)
    mp.terminar_coleta("operador")
    c.anda(5); grava(c(), "depois")

    # ─── concluir (com a pose escorregada 7 cm: B6 avisa, não bloqueia) ───
    with m.lock:
        m.x += 0.07
    ok, msg = mp.concluir("operador")
    check("Concluir → aceito", ok, msg)
    check("Concluir termina com o pacote criado", ate({None}, 8.0), str(mp.estado()))
    r = mp.estado().get("ultimo") or {}
    check("Conferência na fita: escorregou 7 cm → AVISO com o número (B6), sem bloquear",
          r.get("aviso") and "7" in r["aviso"] and r.get("ok"), str(r))
    check("O pacote novo aparece na lista e a pasta parcial sumiu",
          pid in amb.ids() and not os.path.exists(parcial))
    plf = json.load(open(os.path.join(raiz, pid, "planta.json"), encoding="utf-8"))
    check("A planta (feita no fim, pelo gerador) leva o sha do mapa BAIXADO",
          plf.get("mapa_sha256") == sha_novo)
    e = amb.avaliar(pid)
    check("Recém-mapeado fica RASCUNHO até alguém salvar o desenho (B5)",
          e["estado"] == "rascunho" and any("desenho" in t for t in e["motivos"]), str(e))
    linhas = []
    for n in sorted(os.listdir(os.path.join(raiz, pid, "coleta"))):
        linhas += [json.loads(x)["rotulo"] for x in open(os.path.join(raiz, pid, "coleta", n), encoding="utf-8")]
    check("A coleta copiou SÓ as varreduras das 2 passadas",
          sorted(linhas) == ["p2", "p2", "p3"], str(linhas))
    fi = json.load(open(os.path.join(raiz, pid, "ficha.json"), encoding="utf-8"))
    check("A ficha guarda as passadas e a conferência",
          len(fi.get("coletas", [])) == 2 and "conferencia" in fi)
    check("O ambiente novo NÃO fica ativo sozinho (B3)", amb.id_ativo() == "sala")
    check("Fim do mapeamento: Aurora sai do modo mapeamento e o laser desliga",
          not a.modo_mapeamento and a.laser_periodo_s == 0)
    check("Fim do mapeamento: a fita volta a ser a do ambiente ativo e a pose não vale "
          "até 'Localizar na fita'",
          a.v.fita == fita_do_centro((FX, FY, FR), BR) and a.pose_valida() is None
          and "fita" in a.motivo().lower(), a.motivo())

    from slam.mapa_nav import NavStore
    ns = NavStore(os.path.join(raiz, pid, "nav"), sha_novo, 0.5,
                  planta_json=os.path.join(raiz, pid, "planta.json"))
    ns.salvar({"mapa_sha256": sha_novo, "areas": [], "pois": []}, "operador", 0)
    check("Depois de salvar o desenho uma vez (mesmo vazio) → PRONTO (B5)",
          amb.avaliar(pid)["estado"] == "pronto", str(amb.avaliar(pid)))

    # ─── cancelar ───
    ok, _ = mp.iniciar("Quadra", "operador")
    ate({"mapeando"})
    pid2 = mp.estado()["id"]
    ok, msg = mp.cancelar("operador")
    check("Cancelar: a pasta parcial é apagada e nada muda nos ambientes",
          ok and not os.path.exists(os.path.join(raiz, pid2 + ".parcial"))
          and amb.id_ativo() == "sala" and pid2 not in amb.ids(), msg)
    check("Cancelar: Aurora sai do modo mapeamento", not a.modo_mapeamento and not mp.ativo)

    # ─── reinício no meio ───
    mp.iniciar("Patio", "operador"); ate({"mapeando"})
    pid3 = mp.estado()["id"]
    mp_r = Mapeamento(raiz, a, impedimentos_fn=lambda: None, parado_fn=lambda: True,
                      varreduras_dir=vd, clock=c, livre_mb_fn=lambda: 50_000)
    check("Reinício durante a passada 1 → 'interrompido' (o mapa sem salvar se perdeu)",
          mp_r.estado()["fase"] == "interrompido" and mp_r.ativo)
    check("Interrompido: só dá para cancelar (salvar recusado)",
          not mp_r.concluir_mapa("operador")[0])
    mp.concluir_mapa("operador"); ate({"mapa_salvo"})
    mp_r2 = Mapeamento(raiz, a, impedimentos_fn=lambda: None, parado_fn=lambda: True,
                       varreduras_dir=vd, clock=c, livre_mb_fn=lambda: 50_000)
    check("Reinício depois do mapa salvo → continua em 'mapa_salvo' (medir a fita)",
          mp_r2.estado()["fase"] == "mapa_salvo" and mp_r2.estado()["id"] == pid3)
    mp_r2.cancelar("operador")
    a.stop()

    src = open(os.path.join(_ROOT, "slam", "mapeamento.py"), encoding="utf-8").read()
    check("slam/mapeamento.py não move o robô (sem set_speed/GPIO)",
          "set_speed" not in src and "GPIO" not in src)


# ─────────────────────────────────────────────
# 21. OS MAPAS DOS C1 E A NOTA (Etapa B.2 — 02/10/2026)
# Sala de mentira: paredes 6 × 4 m (vistas a 1,45 m e a 22 cm), quatro pés de
# mesa (só a 22 cm) e uma pessoa que aparece em UMA volta só.
# ─────────────────────────────────────────────
def _raios(ox, oy, dirs_rad, segs):
    """Distância até o 1º segmento em cada direção (inf se nenhum)."""
    import numpy as np
    dx, dy = np.cos(dirs_rad), np.sin(dirs_rad)
    melhor = np.full(len(dirs_rad), np.inf)
    for (x1, y1, x2, y2) in segs:
        ex, ey = x2 - x1, y2 - y1
        den = dx * ey - dy * ex
        with np.errstate(divide="ignore", invalid="ignore"):
            t = ((x1 - ox) * ey - (y1 - oy) * ex) / den
            u = ((x1 - ox) * dy - (y1 - oy) * dx) / den
        ok = (np.abs(den) > 1e-12) & (t > 0) & (u >= 0) & (u <= 1)
        melhor = np.where(ok & (t < melhor), t, melhor)
    return melhor


def _quadrado(cx, cy, lado):
    h = lado / 2
    p = [(cx - h, cy - h), (cx + h, cy - h), (cx + h, cy + h), (cx - h, cy + h)]
    return [(p[i][0], p[i][1], p[(i + 1) % 4][0], p[(i + 1) % 4][1]) for i in range(4)]


def _coleta_de_mentira(pasta, *, com_laser=True, pessoa_em=None):
    import numpy as np
    from slam.mapa_c1 import LASER_NO_PONTO, C1_NO_CENTRO
    BR = (-0.053, 0.072)
    paredes = [(0, 0, 6, 0), (6, 0, 6, 4), (6, 4, 0, 4), (0, 4, 0, 0)]
    pes = sum([_quadrado(x, y, 0.04) for x, y in ((2.0, 2.0), (2.6, 2.0),
                                                  (2.0, 2.6), (2.6, 2.6))], [])
    pessoa = _quadrado(4.0, 1.0, 0.30)
    os.makedirs(pasta, exist_ok=True)
    k, t = 0, 1000.0
    for n in (2, 3):
        with open(os.path.join(pasta, f"passada_{n}.jsonl"), "w", encoding="utf-8") as f:
            for i in range(40):
                ang_v = 2 * math.pi * i / 40 + (0.07 if n == 3 else 0.0)
                cx, cy = 3.0 + 1.6 * math.cos(ang_v), 2.0 + 1.1 * math.sin(ang_v)
                rumo = math.degrees(ang_v) + 90.0
                k += 1; t += 1.0
                tem_pessoa = pessoa_em == k
                # C1 a 22 cm: paredes + pés (+ pessoa)
                c1x, c1y = cx + 0.30 * math.cos(math.radians(rumo)), cy + 0.30 * math.sin(math.radians(rumo))
                ang = np.arange(0, 360, 360 / 400)
                ang = ang[~((ang > 140) & (ang < 210))]
                d = _raios(c1x, c1y, np.radians(rumo - ang),
                           paredes + pes + (pessoa if tem_pessoa else []))
                p = [[int(a * 100), int(dd * 1000)] for a, dd in zip(ang, d) if np.isfinite(dd)]
                reg = {"t": t, "pose": [cx * 100, cy * 100, rumo, 0.05], "p": p}
                if com_laser:
                    # o PONTO do Aurora e a origem do laser
                    bx, by = BR
                    px = cx + bx * math.cos(math.radians(rumo)) - by * math.sin(math.radians(rumo))
                    py = cy + bx * math.sin(math.radians(rumo)) + by * math.cos(math.radians(rumo))
                    lx0, ly0, lth, _s = LASER_NO_PONTO
                    ox = px + lx0 * math.cos(math.radians(rumo)) - ly0 * math.sin(math.radians(rumo))
                    oy = py + lx0 * math.sin(math.radians(rumo)) + ly0 * math.cos(math.radians(rumo))
                    la = np.arange(0, 360, 360 / 1800)
                    ld = _raios(ox, oy, np.radians(rumo + la + lth),
                                paredes + (pessoa if tem_pessoa else []))
                    reg["a145"] = {"ts": k, "pose": [px, py, 1.45, rumo],
                                   "p": [[int(a * 100), int(dd * 1000), 47]
                                         for a, dd in zip(la, ld) if np.isfinite(dd)]}
                f.write(json.dumps(reg) + "\n")
    _ = C1_NO_CENTRO


def test_mapa_c1():
    section("21. OS MAPAS DOS C1 E A NOTA DE QUALIDADE (Etapa B.2, 02/10)")
    try:
        from slam.mapa_c1 import gerar_mapas
    except ImportError as e:
        check("slam/mapa_c1.py existe", False, str(e))
        return
    import numpy as np
    from PIL import Image
    pac = tempfile.mkdtemp(prefix="fase4_c1_")
    with open(os.path.join(pac, "ficha.json"), "w", encoding="utf-8") as f:
        json.dump({"mapa_sha256": "e" * 64}, f)
    _coleta_de_mentira(os.path.join(pac, "coleta"), pessoa_em=7)
    t0 = time.monotonic()
    r = gerar_mapas(pac, n_nota=12)
    dur = time.monotonic() - t0
    ok_arq = all(os.path.isfile(os.path.join(pac, n)) for n in
                 ("c1_145.png", "c1_145.json", "c1_22.png", "c1_22.json"))
    check("Grava os dois mapas no pacote (png + json)", ok_arq, str(os.listdir(pac)))
    if not ok_arq:
        return
    m145 = json.load(open(os.path.join(pac, "c1_145.json"), encoding="utf-8"))
    m22 = json.load(open(os.path.join(pac, "c1_22.json"), encoding="utf-8"))
    check("Os mapas levam o sha do mapa do Aurora e a grade de 2 cm",
          m145["mapa_sha256"] == "e" * 64 and m22["res"] == 0.02 and m145["res"] == 0.02)

    def paredes_em(meta, png, x, y, raio):
        img = np.array(Image.open(os.path.join(pac, png)))
        c = int((x - meta["min_x"]) / meta["res"]); l = int((meta["max_y"] - y) / meta["res"])
        k = max(1, int(raio / meta["res"]))
        return int((img[max(0, l - k):l + k + 1, max(0, c - k):c + k + 1] == 0).sum())

    check("1,45 m: a parede leste (x = 6 m) está no lugar (≤ 2 cm)",
          paredes_em(m145, "c1_145.png", 6.0, 2.0, 0.02) > 0
          and paredes_em(m145, "c1_145.png", 5.92, 2.0, 0.02) == 0)
    check("1,45 m: os pés de mesa NÃO aparecem (o laser passa por cima)",
          paredes_em(m145, "c1_145.png", 2.0, 2.0, 0.04) == 0)
    check("22 cm: os pés de mesa aparecem (≤ 3 cm)",
          paredes_em(m22, "c1_22.png", 2.0, 2.0, 0.03) > 0
          and paredes_em(m22, "c1_22.png", 2.6, 2.6, 0.03) > 0)
    check("Quem passou uma vez só (a pessoa) não vira parede, em nenhum dos dois",
          paredes_em(m145, "c1_145.png", 4.0, 1.0, 0.18) == 0
          and paredes_em(m22, "c1_22.png", 4.0, 1.0, 0.18) == 0)
    nt = r.get("nota") or {}
    n145, n2 = nt.get("1,45 m") or {}, nt.get("os dois") or {}
    check("A nota existe para o 1,45 m e para os dois juntos",
          n145.get("n", 0) > 0 and n2.get("n", 0) > 0, str(nt))
    check("Na sala de mentira, a nota é boa (mediana < 3 cm, nenhum erro > 30 cm)",
          n145.get("mediana_cm", 99) < 3 and n2.get("mediana_cm", 99) < 3
          and n145.get("acima_30cm", 1) == 0, str(nt))
    check("Gera em tempo razoável (< 2 min; a Pi é mais lenta que o PC)", dur < 120,
          f"{dur:.1f} s")
    from slam.mapa_c1 import _distancia_truncada
    pa = np.zeros((30, 30), bool); pa[10, 10] = True
    dt = _distancia_truncada(pa, 0.02, 0.2)
    check("Distância à parede sem scipy: exata (3-4-5) e truncada no raio",
          abs(dt[13, 14] - 0.10) < 1e-9 and dt[10, 10] == 0 and np.isinf(dt[25, 25]))

    pac2 = tempfile.mkdtemp(prefix="fase4_c1b_")
    with open(os.path.join(pac2, "ficha.json"), "w", encoding="utf-8") as f:
        json.dump({"mapa_sha256": "e" * 64}, f)
    _coleta_de_mentira(os.path.join(pac2, "coleta"), com_laser=False)
    r2 = gerar_mapas(pac2, n_nota=5)
    check("Coleta sem o laser do Aurora: não quebra, diz o motivo e ainda faz o de 22 cm",
          r2["1,45 m"] is None and "laser" in r2.get("motivo_145", "")
          and r2["22 cm"] is not None, str(r2))

    # No pacote e na lista de ambientes
    from slam.ambientes import Ambientes
    raiz = os.path.join(tempfile.mkdtemp(prefix="fase4_c1c_"), "ambientes")
    _pacote(raiz, "lugar", mapa=b"LUGAR")
    fi = os.path.join(raiz, "lugar", "ficha.json")
    d = json.load(open(fi, encoding="utf-8")); d["c1"] = r
    json.dump(d, open(fi, "w", encoding="utf-8"))
    p = Ambientes(raiz).avaliar("lugar")
    check("A lista de ambientes mostra os mapas dos C1 e a nota",
          (p.get("c1") or {}).get("nota_145_cm") == n145.get("mediana_cm")
          and (p.get("c1") or {}).get("nota_juntos_cm") == n2.get("mediana_cm"), str(p.get("c1")))
    # A PLANTA feita da coleta (02/10, depois do SIGSEGV do SDK)
    pj = os.path.join(pac, "planta.json")
    check("O gerador também faz a PLANTA (png + json), com o sha do mapa",
          os.path.isfile(pj) and os.path.isfile(os.path.join(pac, "planta.png"))
          and json.load(open(pj, encoding="utf-8")).get("mapa_sha256") == "e" * 64)
    if os.path.isfile(pj):
        from slam.planejador import Planta, Planejador, LIVRE, OCUPADO, DESCONHECIDO
        mp_ = json.load(open(pj, encoding="utf-8"))
        pt = Planta.de_arquivos(os.path.join(pac, "planta.png"), mp_)

        def cel(x, y):
            return pt.grade[int((mp_["max_y"] - y) / mp_["res"]), int((x - mp_["min_x"]) / mp_["res"])]
        perto_parede = {cel(6.0 + dx, 2.0) for dx in (-0.05, 0.0, 0.05)}
        check("Planta: meio da sala LIVRE, parede OCUPADA (±5 cm), fora da sala DESCONHECIDO",
              cel(3.0, 2.0) == LIVRE and OCUPADO in perto_parede and cel(6.4, 2.0) == DESCONHECIDO,
              f"{cel(3.0, 2.0)} {perto_parede} {cel(6.4, 2.0)}")
        check("Planta: os pés de mesa (só a 22 cm) não entram — como a do Aurora",
              cel(2.0, 2.0) != OCUPADO)
        ex = mp_.get("eixo_paredes_deg", -1) % 90
        check("Planta: o eixo das paredes (0° ou 90°: sala alinhada) e as posições delas (o /mapa usa)",
              min(ex, 90 - ex) < 1.0 and len(mp_.get("paredes", [])) == 2,
              f"eixo {mp_.get('eixo_paredes_deg')}, paredes {mp_.get('paredes')}")
        pts, motivo = Planejador(pt, [], 0.5).planejar((3.0, 2.0), (4.4, 2.6))
        check("O planejador traça rota sobre a planta feita da coleta", pts is not None, str(motivo))

    from slam.mapeamento import gerar_c1_seguro

    def _quebra(pasta):
        raise RuntimeError("numpy de mentira quebrou")
    g = gerar_c1_seguro(_quebra, pac)
    check("Se gerar os mapas dos C1 falhar, o pacote segue (só sem eles) e o erro fica registrado",
          isinstance(g, dict) and "quebrou" in g.get("erro", ""), str(g))
    src_main = open(os.path.join(_ROOT, "main.py"), encoding="utf-8").read()
    check("main.py entrega o gerador ao mapeamento, num PROCESSO à parte (não segura o loop)",
          "gerar_mapas_fn=lambda pasta: gerar_mapas_em_processo(" in src_main)
    from slam.mapa_c1 import gerar_mapas_em_processo
    for n in os.listdir(pac):
        if n.startswith("c1_"):
            os.remove(os.path.join(pac, n))
    rp = gerar_mapas_em_processo(pac)
    check("O gerador em processo à parte grava os mapas e devolve a nota",
          rp.get("1,45 m") == r.get("1,45 m") and rp.get("22 cm") == r.get("22 cm")
          and (rp.get("nota") or {}).get("os dois", {}).get("mediana_cm", 99) < 3
          and os.path.isfile(os.path.join(pac, "c1_145.png")), str(rp.get("nota")))
    src = open(os.path.join(_ROOT, "slam", "mapa_c1.py"), encoding="utf-8").read()
    check("slam/mapa_c1.py não move o robô (sem set_speed/GPIO)",
          "set_speed" not in src and "GPIO" not in src)


# ─────────────────────────────────────────────
# 22. O PASSO A PASSO NO PAINEL (Etapa B.3 — 02/10/2026)
# ─────────────────────────────────────────────
def test_painel_mapeamento():
    section("22. MAPEAR PELO PAINEL — rotas e página (Etapa B.3, 02/10)")
    from core.motor_driver import MotorDriver
    from web.server import create_app

    class _MapFake:
        def __init__(self):
            self.chamadas, self.ativo, self.recusar = [], False, None

        def estado(self):
            return {"fase": "mapeando" if self.ativo else None, "ultimo": None}

        def _faz(self, nome, *a):
            self.chamadas.append((nome,) + a)
            if self.recusar:
                return False, self.recusar
            return True, f"{nome} ok"

        def iniciar(self, nome, quem): return self._faz("iniciar", nome, quem)
        def concluir_mapa(self, quem): return self._faz("concluir_mapa", quem)
        def medir_fita(self, quem): return self._faz("medir_fita", quem)
        def iniciar_coleta(self, quem): return self._faz("iniciar_coleta", quem)
        def terminar_coleta(self, quem): return self._faz("terminar_coleta", quem)
        def concluir(self, quem): return self._faz("concluir", quem)
        def cancelar(self, quem): return self._faz("cancelar", quem)

    mf = _MapFake()

    class _Mot(MotorDriver):
        paradas = 0

        def stop(self):
            _Mot.paradas += 1
            return super().stop()
    try:
        app = create_app(motors=_Mot(), state={"robot_id": 1}, mapeamento=mf)
    except TypeError as e:
        check("create_app aceita o mapeamento", False, str(e))
        return
    cl = app.test_client()
    check("GET /api/mapeamento sem login → 401", cl.get("/api/mapeamento").status_code == 401)
    r = cl.post("/api/mapeamento/iniciar", json={"nome": "Quadra"})
    check("POST /api/mapeamento/iniciar sem login → 401 e nada é chamado",
          r.status_code == 401 and not mf.chamadas)
    cl.post("/login", data={"usuario": "operador", "senha": _SENHA})
    d = cl.get("/api/mapeamento").get_json()
    check("GET /api/mapeamento com login → estado", d.get("ok") and "estado" in d, str(d))
    r = cl.post("/api/mapeamento/iniciar", json={"nome": "Quadra"})
    check("Iniciar passa o nome e quem pediu",
          r.status_code == 200 and mf.chamadas[-1] == ("iniciar", "Quadra", "operador"))
    for acao in ("concluir_mapa", "medir_fita", "iniciar_coleta", "terminar_coleta",
                 "concluir", "cancelar"):
        r = cl.post(f"/api/mapeamento/{acao}")
        check(f"POST /api/mapeamento/{acao} chama o passo", r.status_code == 200
              and mf.chamadas[-1][0] == acao, str(r.status_code))
    mf.recusar = "agora não: o passo atual é 'mapeando'"
    r = cl.post("/api/mapeamento/medir_fita")
    check("Passo recusado → 409 com o motivo",
          r.status_code == 409 and "agora não" in r.get_json().get("msg", ""))
    mf.recusar = None
    check("Ação desconhecida → 404", cl.post("/api/mapeamento/apagar_tudo").status_code == 404)
    mf.ativo = True
    n0 = len(mf.chamadas)
    r = cl.post("/api/stop")
    check("PARAR durante o mapeamento para os motores e NÃO cancela o mapeamento",
          r.status_code == 200 and _Mot.paradas >= 1 and len(mf.chamadas) == n0 and mf.ativo)
    html = cl.get("/ambientes").get_data(as_text=True)
    check("A página Ambientes tem o passo a passo do mapeamento",
          "Novo ambiente" in html and "/api/mapeamento" in html)
    app2 = create_app(motors=MotorDriver(), state={"robot_id": 2})
    c2 = app2.test_client()
    c2.post("/login", data={"usuario": "operador", "senha": _SENHA})
    r = c2.post("/api/mapeamento/iniciar", json={"nome": "X"})
    check("Robô sem mapeamento (sem Aurora) → 404, sem quebrar",
          r.status_code == 404 and c2.get("/api/mapeamento").status_code == 404)

    # ─── rascunho → pronto sem reiniciar, quando só faltava o desenho ───
    from slam.ambientes import Ambientes, resolver, promover_se_pronto
    raiz = os.path.join(tempfile.mkdtemp(prefix="fase4_b3_"), "ambientes")
    sha = _pacote(raiz, "novo", mapa=b"NOVO", desenho=False)
    amb = Ambientes(raiz)
    amb.pedir_troca("novo", "operador", missao_ativa=False, editando=False, andando=False)
    LEG = {"mapa": None, "mapa_sha256": None, "fita": None, "planta_json": None, "nav_dir": None}
    AMB = resolver(amb, LEG)
    check("Antes do desenho: rascunho e missão indisponível",
          AMB["ambiente"]["estado"] == "rascunho" and AMB["missao_motivo"])
    check("Sem salvar nada: continua rascunho", promover_se_pronto(amb, AMB) is False
          and AMB["missao_motivo"])
    from slam.mapa_nav import NavStore
    NavStore(AMB["nav_dir"], sha, 0.5, planta_json=AMB["planta_json"]).salvar(
        {"mapa_sha256": sha, "areas": [], "pois": []}, "operador", 0)
    check("Desenho salvo → vira pronto e a missão libera, SEM reiniciar",
          promover_se_pronto(amb, AMB) is True and AMB["missao_motivo"] is None
          and AMB["ambiente"]["estado"] == "pronto")
    sha2 = _pacote(raiz, "semfita", mapa=b"SF", fita=None, desenho=False)
    amb.pedir_troca("semfita", "operador", missao_ativa=False, editando=False, andando=False)
    AMB2 = resolver(amb, LEG)
    fi = os.path.join(raiz, "semfita", "ficha.json")
    d = json.load(open(fi, encoding="utf-8")); d["fita"] = [1.0, 2.0, 3.0]
    json.dump(d, open(fi, "w", encoding="utf-8"))
    NavStore(AMB2["nav_dir"], sha2, 0.5, planta_json=AMB2["planta_json"]).salvar(
        {"mapa_sha256": sha2, "areas": [], "pois": []}, "operador", 0)
    check("Se a FITA mudou depois da partida do serviço → NÃO promove (precisa reiniciar)",
          promover_se_pronto(amb, AMB2) is False and AMB2["missao_motivo"])
    src = open(os.path.join(_ROOT, "main.py"), encoding="utf-8").read()
    check("main.py confere a promoção no laço do mapeamento e passa o mapeamento ao painel",
          "promover_se_pronto(" in src and "mapeamento=mapeamento" in src)



# ─────────────────────────────────────────────
# 23. "RODAS PARADAS" AMOSTRADAS SEMPRE (achado na bancada de 02/10)
# O teste só contava quando alguém perguntava: depois de andar, o 1º clique
# ("Começar a mapear", "Medir a fita", "Concluir", "Usar este ambiente") era
# SEMPRE recusado com o robô parado; o 2º passava.
# ─────────────────────────────────────────────
def test_rodas_paradas():
    section("23. RODAS PARADAS — amostradas sempre, não só quando perguntam (02/10)")
    try:
        from core.rodas_paradas import RodasParadas
    except ImportError as e:
        check("core/rodas_paradas.py existe", False, str(e))
        return
    cont = [100, 200]
    c = Relogio()
    rp = RodasParadas(lambda: tuple(cont), janela_s=0.5, clock=c)
    for _ in range(5):
        rp.amostrar(); c.anda(0.1)
    cont[0] += 40                                  # andou um pouco…
    for _ in range(30):                            # …e parou há 3 s, com o laço amostrando
        rp.amostrar(); c.anda(0.1)
    check("Parado há 3 s (amostrado sempre): a 1ª pergunta já diz PARADO", rp() is True)
    cont[1] += 3; rp.amostrar(); c.anda(0.2); rp.amostrar()
    check("Roda girou há 0,2 s → NÃO parado", rp() is False)
    for _ in range(4):
        c.anda(0.1); rp.amostrar()
    check("0,6 s sem pulso → parado de novo", rp() is True)
    cont[0] += 1
    check("Pulso entre amostras é visto na pergunta (nunca diz parado com a roda girando)",
          rp() is False)
    src = open(os.path.join(_ROOT, "main.py"), encoding="utf-8").read()
    check("main.py amostra as rodas continuamente (no laço de 10 Hz)",
          "_rodas_paradas.amostrar()" in src)


def main():
    print(f"{BOLD}GATE DA FASE 4 — pose do Aurora (MOCK){RESET}")
    test_regras()
    test_aurora()
    test_sem_aurora()
    test_gravador()
    test_laser_aurora()
    test_silencio_da_pose()
    test_web()
    test_loop()
    test_bancada()
    test_config()
    test_nav()
    test_planejador()
    test_missao()
    test_chegada_base()
    test_malha_da_missao()
    test_pulsos_regulados()
    test_vigia_do_giro()
    test_braco()
    test_ambientes()
    test_mapeamento()
    test_mapa_c1()
    test_painel_mapeamento()
    test_rodas_paradas()
    ok = sum(1 for _, r, _ in _results if r)
    total = len(_results)
    print(f"\n{BOLD}RESULTADO: {ok}/{total}{RESET}",
          "VERDE ✅" if ok == total else "com falhas ❌")
    return 0 if ok == total else 1


if __name__ == "__main__":
    sys.exit(main())
