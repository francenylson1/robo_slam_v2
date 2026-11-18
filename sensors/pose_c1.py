"""
sensors/pose_c1.py
A POSE DA MISSÃO NO ROBÔ SEM AURORA: o localizador C1 (slam/sombra_proc.py)
como fonte de pose, com as MESMAS regras do Aurora (PoseValidator) e dois
vigias que só o C1 precisa. Decidido com o professor em 18/11/2026 (página
"Missão pelos C1 — robô 2", D1–D8):

  D1  liga só com FROTA_POSE_FONTE=c1 no /etc/frota.conf do robô; sem isso o
      localizador continua só como fantasma. O robô com Aurora nem olha.
  D2  PoseValidator do Aurora: velha > 0,3 s na missão, salto > 25 cm / 15°,
      1 s estável depois. O carimbo é a hora da VOLTA do C1, não a do cálculo.
  D3  partida só na fita: depois de "Localizar na fita", vale só com
      C1_PARTIDA_VOLTAS voltas seguidas de bom encaixe a até 15 cm / 5° da fita.
  D4  perdido (fantasma vermelho) → a localização deixa de valer até a fita de
      novo; a missão vê "perdeu a localização", para e cancela (vigias).
  D5  vigia das rodas (os Hall contam, mas não dão o sentido):
        a pose andou > C1_VIGIA_POSE_SEM_RODAS_M com as rodas paradas, ou
        as rodas andaram C1_VIGIA_RODAS_JANELA_M e a pose andou menos que
        C1_VIGIA_RODAS_SEM_POSE_M  → não vale (como D4).
      No giro no lugar as rodas também contam; a parte do giro (BNO × meia
      bitola) sai da conta antes. Bitola folgada = menos alarme falso.
  D6  vigia do giro: em C1_VIGIA_GIRO_JANELA_S, o rumo do C1 e o do BNO não
      podem divergir mais que C1_VIGIA_GIRO_DEG → não vale (como D4).
  D8  o encaixe de cada volta só é anotado (health), não muda a velocidade.

Nada aqui move o robô: só diz se a pose vale e por quê.
"""

import collections
import logging
import math
import threading
import time

from sensors.pose_source import Pose, normaliza_graus

log = logging.getLogger(__name__)

BNO_SENTIDO = -1.0      # Δrumo do mapa = −Δyaw do BNO (o mesmo de slam/sombra.py)


class C1PoseSource:

    fonte = "c1"

    def __init__(self, sombra, validator, *, ticks_fn=None, yaw_fn=None, cfg=None,
                 clock=time.monotonic):
        from config import settings
        c = cfg or settings
        self.sombra = sombra
        self.v = validator
        self._ticks_fn = ticks_fn            # () → (ticks esq., ticks dir.), só crescem
        self._yaw_fn = yaw_fn                # () → yaw do BNO em graus, ou None
        self._clock = clock
        self.m_por_tick = c.ROBOT_WHEEL_CIRCUMFERENCE_M / c.TICKS_PER_REVOLUTION
        self.partida_voltas = c.C1_PARTIDA_VOLTAS
        self.partida_encaixe = c.C1_PARTIDA_ENCAIXE
        self.pose_sem_rodas_m = c.C1_VIGIA_POSE_SEM_RODAS_M
        self.rodas_paradas_m = c.C1_VIGIA_RODAS_PARADAS_M
        self.rodas_janela_m = c.C1_VIGIA_RODAS_JANELA_M
        self.rodas_sem_pose_m = c.C1_VIGIA_RODAS_SEM_POSE_M
        self.meia_bitola_m = c.C1_VIGIA_BITOLA_M / 2.0
        self.giro_deg = c.C1_VIGIA_GIRO_DEG
        self.giro_janela_s = c.C1_VIGIA_GIRO_JANELA_S
        self._lock = threading.Lock()
        self._boas = None                    # None = não está partindo; n = voltas boas seguidas
        self._ancora_parado = None           # (x, y, ticks) desde que as rodas pararam
        self._rodas_trans = 0.0              # metros de translação pelas rodas (acumulado)
        self._hist_rodas = collections.deque()   # (acumulado, x, y) — janela deslizante
        self._ult = None                     # (ticks, yaw) da volta anterior
        self._giros = collections.deque()    # (t, rumo, yaw)
        self.partida = {"passo": None, "resultado": None, "quando": None}
        self.vigias = {"rodas_paradas": 0, "rodas_sem_pose": 0, "giro": 0, "perdido": 0}
        self.encaixe = None
        self.ocupado = False
        sombra.on_pose = self._on_pose
        sombra.on_semeou = self._on_semeou

    # ─── ciclo de vida (o serviço liga a sombra; aqui só o validador) ───
    def start(self):
        self.v.on_conectou()

    def stop(self):
        self.v.on_desconectou()

    # ─── a interface da missão ──────────────────────
    def pose_valida(self, max_idade_s=None):
        return self.v.avaliar(max_idade_s)[0]

    def motivo(self, max_idade_s=None) -> str:
        return self.v.avaliar(max_idade_s)[1]

    def pedir_partida(self, parado_fn) -> tuple[bool, str]:
        """O botão "Localizar na fita" do painel: semeia o localizador na fita."""
        if not parado_fn():
            return False, "o robô precisa estar parado sobre a fita"
        if self.v.fita is None:
            return False, "fita não medida neste ambiente"
        return self.sombra.semear_fita()

    def health(self) -> dict:
        p, motivo = self.v.avaliar()
        ult = p or self.v.ultima()
        return {
            "fonte": "c1",
            "conectado": bool(self.sombra.health().get("ligado")),
            "valida": p is not None,
            "motivo": motivo,
            "x_cm": None if ult is None else round(ult.x_m * 100, 1),
            "y_cm": None if ult is None else round(ult.y_m * 100, 1),
            "rumo_deg": None if ult is None else round(ult.rumo_deg, 1),
            "idade_s": None if ult is None else round(self._clock() - ult.t, 2),
            "partida": dict(self.partida),
            "saltos": self.v.saltos,
            "encaixe": self.encaixe,
            "vigias": dict(self.vigias),
        }

    # ─── eventos do localizador (thread leitora da sombra) ──
    def _on_semeou(self):
        with self._lock:
            self._boas = 0
            self._zerar_vigias()
            self.partida = {"passo": f"localizando na fita (0/{self.partida_voltas})",
                            "resultado": None, "quando": time.time()}
        self.v.invalidar_localizacao("localizando na fita")

    def _zerar_vigias(self):
        self._ancora_parado = self._ult = None
        self._rodas_trans = 0.0
        self._hist_rodas.clear()
        self._giros.clear()

    def _invalidar(self, chave, motivo):
        self.vigias[chave] += 1
        self._boas = None
        self._zerar_vigias()
        self.partida = {"passo": None, "resultado": f"perdeu: {motivo}", "quando": time.time()}
        log.warning(f"[PoseC1] {motivo} — a pose não vale até localizar na fita de novo.")
        self.v.invalidar_localizacao(f"{motivo} — volte à fita e localize")

    def _on_pose(self, t, x, y, rumo, encaixe, perdido):
        pose = Pose(x, y, normaliza_graus(rumo), t)
        with self._lock:
            self.encaixe = encaixe
            self.v.on_pose(pose)
            if perdido:
                if self._boas is not None or self.v.localizado:
                    self._invalidar("perdido", f"o localizador C1 se perdeu (encaixe {encaixe})")
                return
            if self._boas is not None:
                self._partida(pose, encaixe)
                return
            if not self.v.localizado:
                return                       # não localizado: os vigias só vigiam pose que vale
            try:
                ticks = self._ticks_fn() if self._ticks_fn else None
            except Exception:
                ticks = None
            try:
                yaw = self._yaw_fn() if self._yaw_fn else None
            except Exception:
                yaw = None
            m = self._vigia_rodas(pose, ticks, yaw) or self._vigia_giro(pose, yaw)
            if m:
                self._invalidar(*m)

    def _partida(self, pose, encaixe):
        fx, fy, fr = self.v.fita
        perto = (math.hypot(pose.x_m - fx, pose.y_m - fy) <= self.v.fita_tol_m and
                 abs(normaliza_graus(pose.rumo_deg - fr)) <= self.v.fita_tol_deg)
        if encaixe is not None and encaixe >= self.partida_encaixe and perto:
            self._boas += 1
        else:
            self._boas = 0
        self.partida["passo"] = f"localizando na fita ({self._boas}/{self.partida_voltas})"
        if self._boas >= self.partida_voltas:
            ok, msg = self.v.on_localizou(pose)
            self._boas = None
            self.partida = {"passo": None, "resultado": ("ok: " if ok else "falhou: ") + msg,
                            "quando": time.time()}
            log.info(f"[PoseC1] Partida na fita: {self.partida['resultado']}.")

    # ─── D5 e D6 ────────────────────────────────────
    def _vigia_rodas(self, pose, ticks, yaw):
        if ticks is None:
            return None
        tot = (ticks[0] + ticks[1]) / 2.0          # média das duas rodas, em ticks
        if self._ult is None:
            self._ult = (tot, yaw)
            self._ancora_parado = (pose.x_m, pose.y_m, tot)
            self._rodas_trans = 0.0
            self._hist_rodas.clear()
            self._hist_rodas.append((0.0, pose.x_m, pose.y_m))
            return None
        tot0, yaw0 = self._ult
        self._ult = (tot, yaw)
        # rodas paradas: a pose não pode andar sozinha
        ax, ay, at = self._ancora_parado
        if (tot - at) * self.m_por_tick > self.rodas_paradas_m:
            self._ancora_parado = (pose.x_m, pose.y_m, tot)
        elif math.hypot(pose.x_m - ax, pose.y_m - ay) > self.pose_sem_rodas_m:
            d = math.hypot(pose.x_m - ax, pose.y_m - ay)
            return "rodas_paradas", f"a pose andou {d * 100:.0f} cm com as rodas paradas"
        # rodas andando: a pose tem que sair do lugar
        rodas = max(0.0, tot - tot0) * self.m_por_tick
        giro = 0.0
        if yaw is not None and yaw0 is not None:
            giro = abs(math.radians(normaliza_graus(yaw - yaw0))) * self.meia_bitola_m
        # Janela DESLIZANTE: a cada volta, onde a pose estava quando as rodas
        # tinham andado 50 cm a menos (fixa, o travamento no meio de uma janela
        # só aparecia depois de até 1 m — pego pelo harness em 18/11).
        self._rodas_trans += max(0.0, rodas - giro)
        h = self._hist_rodas
        h.append((self._rodas_trans, pose.x_m, pose.y_m))
        limite = self._rodas_trans - self.rodas_janela_m
        while len(h) > 1 and h[1][0] <= limite:
            h.popleft()
        if h[0][0] <= limite:
            d = math.hypot(pose.x_m - h[0][1], pose.y_m - h[0][2])
            if d < self.rodas_sem_pose_m:
                return "rodas_sem_pose", (f"as rodas andaram {self.rodas_janela_m * 100:.0f} cm "
                                          f"e a pose só {d * 100:.0f} cm")
        return None

    def _vigia_giro(self, pose, yaw):
        if yaw is None:
            self._giros.clear()
            return None
        g = self._giros
        g.append((pose.t, pose.rumo_deg, yaw))
        while len(g) > 1 and pose.t - g[1][0] >= self.giro_janela_s:
            g.popleft()
        t0, r0, y0 = g[0]
        if pose.t - t0 < self.giro_janela_s * 0.5:
            return None
        div = normaliza_graus((pose.rumo_deg - r0) - BNO_SENTIDO * normaliza_graus(yaw - y0))
        if abs(div) > self.giro_deg:
            return "giro", f"o rumo do C1 e o do BNO divergiram {abs(div):.0f}°"
        return None
