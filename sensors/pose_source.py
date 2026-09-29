"""
sensors/pose_source.py
Fonte de pose genérica e as regras que dizem quando uma pose VALE.

POR QUE GENÉRICA (decisão de 29/09/2026): só o robô 1 tem Aurora; os demais
têm só o C1. Se um dia a opção B (C1 + mapa) ou a C (marcas no teto) vingar,
ela entra como outra fonte de pose, com as MESMAS regras de validade, e a
missão não é reescrita. A missão só conhece esta interface:

    fonte                         → "aurora" | None
    pose_valida(max_idade_s=None) → Pose | None
    motivo()                      → por que a pose não vale ("" se vale)
    health()                      → dict para a telemetria

AS REGRAS (docs/FASE4_ARQUITETURA_FROTA.md, decisões de 29/09). A pose só vale
com todas de pé:
  1. a fonte se localizou DEPOIS de conectar (quem confirma é a partida);
  2. logo após se localizar, a pose bateu com a FITA;
  3. a leitura é fresca (0,5 s no assistivo; 0,3 s em missão);
  4. não houve salto impossível no último segundo;
  5. não estamos no 1º segundo depois de conectar;
  6. o rastreio não está perdido.

O QUE UMA POSE INVÁLIDA FAZ depende de quem pergunta: no assistivo só aparece
no dashboard (fail-soft); na missão, o robô para e a missão não retoma
(fail-closed). Este módulo só responde "vale / não vale e por quê".

CONVENÇÃO: x e y em metros no referencial do MAPA; rumo em graus na convenção
do Aurora (cresce para a ESQUERDA). O BNO085 tem a convenção OPOSTA (a
direita aumenta) — quem cruza os dois passa só DIFERENÇAS, com o sinal
invertido (decisão 5 de 29/09). Nenhuma conversão acontece aqui.
"""

import logging
import math
import threading
import time
from dataclasses import dataclass

log = logging.getLogger(__name__)


def normaliza_graus(a: float) -> float:
    """Traz um ângulo para (-180, +180]."""
    a = math.fmod(a, 360.0)
    if a > 180.0:
        a -= 360.0
    elif a <= -180.0:
        a += 360.0
    return a


@dataclass(frozen=True)
class Pose:
    x_m: float
    y_m: float
    rumo_deg: float     # convenção do Aurora: esquerda aumenta
    t: float            # time.monotonic() de quando a leitura CHEGOU aqui


class PoseValidator:
    """
    As seis regras, sem thread e sem SDK — o relógio é injetável para o harness
    provar cada regra sem esperar o tempo passar. Os métodos on_* são chamados
    pela fonte (a thread do Aurora); avaliar() é chamado por quem consome.
    """

    def __init__(self, *, fita, fita_tol_m, fita_tol_deg, max_idade_s,
                 salto_m, salto_deg, estavel_s, aquecimento_s,
                 clock=time.monotonic):
        self.fita          = tuple(fita)
        self.fita_tol_m    = fita_tol_m
        self.fita_tol_deg  = fita_tol_deg
        self.max_idade_s   = max_idade_s
        self.salto_m       = salto_m
        self.salto_deg     = salto_deg
        self.estavel_s     = estavel_s
        self.aquecimento_s = aquecimento_s
        self._clock        = clock
        self._lock         = threading.Lock()
        self._conectado    = False
        self._conectou_em  = None
        self._localizado   = False
        self._motivo_local = "não localizado na fita"
        self._tracking_ok  = True
        self._instavel_ate = 0.0
        self._ultima       = None
        self.saltos        = 0

    # ─────────────────────────────────────────
    # EVENTOS DA FONTE
    # ─────────────────────────────────────────
    def on_conectou(self):
        """Conectar (ou reconectar) zera tudo: a localização anterior não vale."""
        with self._lock:
            self._conectado    = True
            self._conectou_em  = self._clock()
            self._localizado   = False
            self._motivo_local = "não localizado na fita"
            self._tracking_ok  = True
            self._instavel_ate = 0.0
            self._ultima       = None

    def on_desconectou(self):
        with self._lock:
            self._conectado    = False
            self._localizado   = False
            self._motivo_local = "não localizado na fita"
            self._ultima       = None

    def invalidar_localizacao(self, motivo: str):
        """A fonte perdeu o mapa ou começou uma partida: precisa da fita de novo."""
        with self._lock:
            self._localizado   = False
            self._motivo_local = motivo

    def on_localizou(self, pose: Pose) -> tuple[bool, str]:
        """
        A fonte diz que se localizou (a partida viu o sucesso com carimbo novo).
        Só aceita se a pose bate com a fita — pega a relocalização no lugar
        errado, o pior caso: robô confiante e errado.
        """
        fx, fy, frumo = self.fita
        d   = math.hypot(pose.x_m - fx, pose.y_m - fy)
        da  = abs(normaliza_graus(pose.rumo_deg - frumo))
        with self._lock:
            if d <= self.fita_tol_m and da <= self.fita_tol_deg:
                self._localizado   = True
                self._motivo_local = ""
                self._instavel_ate = 0.0
                # A mediana da fita vira a última pose: a próxima leitura é
                # comparada com ela, e não com uma de antes de zerar o mapa
                # (que daria um "salto" falso).
                self._ultima       = pose
                return True, f"na fita ({d * 100:.1f} cm, {da:.1f}°)"
            self._localizado   = False
            self._motivo_local = (f"relocalizou fora da fita "
                                  f"({d * 100:.0f} cm, {da:.0f}°)")
            return False, self._motivo_local

    def on_tracking(self, ok: bool):
        with self._lock:
            if ok and not self._tracking_ok:
                # Recuperou: 1 s estável antes de voltar a valer, como no salto.
                self._instavel_ate = self._clock() + self.estavel_s
            self._tracking_ok = ok

    def on_pose(self, pose: Pose) -> bool:
        """Registra uma leitura NOVA. Devolve False se ela foi um salto."""
        with self._lock:
            if (self._conectou_em is not None
                    and pose.t - self._conectou_em < self.aquecimento_s):
                return True             # regra 5: descartada, nem entra
            ok = True
            if self._ultima is not None:
                d  = math.hypot(pose.x_m - self._ultima.x_m,
                                pose.y_m - self._ultima.y_m)
                da = abs(normaliza_graus(pose.rumo_deg - self._ultima.rumo_deg))
                if d > self.salto_m or da > self.salto_deg:
                    ok = False
                    self.saltos += 1
                    self._instavel_ate = pose.t + self.estavel_s
                    log.warning(f"[Pose] Salto de {d * 100:.0f} cm / {da:.0f}° — "
                                f"pose inválida até {self.estavel_s:g} s estável.")
            self._ultima = pose
            return ok

    # ─────────────────────────────────────────
    # PERGUNTA DE QUEM CONSOME
    # ─────────────────────────────────────────
    def avaliar(self, max_idade_s: float | None = None):
        """Devolve (pose | None, motivo). motivo == "" quando a pose vale."""
        limite = self.max_idade_s if max_idade_s is None else max_idade_s
        agora = self._clock()
        with self._lock:
            p = self._ultima
            if not self._conectado:
                return None, "desconectado"
            if (self._conectou_em is not None
                    and agora - self._conectou_em < self.aquecimento_s):
                return None, "aquecendo (1º segundo após conectar)"
            if not self._tracking_ok:
                return None, "rastreio perdido"
            if not self._localizado:
                return None, self._motivo_local
            if p is None:
                return None, "sem leitura"
            if agora - p.t > limite:
                return None, f"pose velha ({agora - p.t:.2f} s)"
            if agora < self._instavel_ate:
                return None, "instável (salto recente)"
            return p, ""

    def ultima(self):
        with self._lock:
            return self._ultima


class NullPoseSource:
    """Robô sem fonte de pose (hoje, todos menos o robô 1)."""

    fonte = None

    def start(self):
        pass

    def stop(self):
        pass

    def pose_valida(self, max_idade_s=None):
        return None

    def motivo(self, max_idade_s=None) -> str:
        return "sem fonte de pose"

    def health(self) -> dict:
        return {"fonte": None, "valida": False, "motivo": "sem fonte de pose"}
