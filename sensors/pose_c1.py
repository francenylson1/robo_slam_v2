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

FUSÃO (18/11/2026, depois das missões do dia): a missão foi afinada na pose
LISA do Aurora; a do C1 crua pula 10–13 cm de lado andando. Agora a pose que a
missão recebe anda pelas RODAS + BNO (o sentido de cada roda vem do último
comando — os Hall não dão sentido) e cada volta do C1 corrige só
C1_FUSAO_GANHO do erro. Volta longe demais da fusão (portão) é rejeitada; se a
discordância dura C1_FUSAO_DISCORDA_S, a pose deixa de valer (como D4). O
VALIDADOR e os vigias D2–D6 continuam olhando o C1 CRU: a fusão só alisa o que
já vale — menos o SALTO do D2: com fusão ele só é anotado, porque o portão já
rejeita o pulo e a volta do C1 para o lugar certo não pode cancelar a missão. Cada volta vai para um CSV (fusao_*.csv) — C1 cru × fusão — para a
próxima análise.

Nada aqui move o robô: só diz se a pose vale e por quê.
"""

import collections
import logging
import math
import os
import threading
import time

from sensors.pose_source import Pose, normaliza_graus

log = logging.getLogger(__name__)

BNO_SENTIDO = -1.0      # Δrumo do mapa = −Δyaw do BNO (o mesmo de slam/sombra.py)


class C1PoseSource:

    fonte = "c1"

    def __init__(self, sombra, validator, *, ticks_fn=None, yaw_fn=None, sentido_fn=None,
                 cfg=None, clock=time.monotonic, traco_dir=None, relogio=time.time):
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
        self.parado_s = c.C1_VIGIA_PARADO_S
        self._buf_parado = collections.deque(maxlen=c.C1_VIGIA_MEDIANA)
        self.rodas_janela_m = c.C1_VIGIA_RODAS_JANELA_M
        self.rodas_sem_pose_m = c.C1_VIGIA_RODAS_SEM_POSE_M
        self.meia_bitola_m = c.C1_VIGIA_BITOLA_M / 2.0
        self.giro_deg = c.C1_VIGIA_GIRO_DEG
        self.giro_janela_s = c.C1_VIGIA_GIRO_JANELA_S
        self._sentido_fn = sentido_fn        # () → (±1, ±1): sentido do último comando de cada roda
        self.fusao = bool(c.C1_FUSAO)
        # Com fusão, o salto do C1 cru não invalida: o portão da fusão o rejeita
        # e a discordância de C1_FUSAO_DISCORDA_S invalida (18/11, missão 18:25).
        validator.salto_invalida = not self.fusao
        self.f_ganho, self.f_ganho_rumo = c.C1_FUSAO_GANHO, c.C1_FUSAO_GANHO_RUMO
        self.f_portao_m, self.f_portao_cresce = c.C1_FUSAO_PORTAO_M, c.C1_FUSAO_PORTAO_CRESCE
        self.f_atraso_s, self.f_discorda_s = c.C1_FUSAO_ATRASO_S, c.C1_FUSAO_DISCORDA_S
        self._fus = None                     # [x, y] da fusão; None = sem fusão (não localizado)
        self._f_off = 0.0                    # rumo do mapa = BNO_SENTIDO × yaw + _f_off
        self._f_base = None                  # (ticks esq., ticks dir., yaw) da última integração
        self._f_hist = collections.deque(maxlen=200)   # (t, x, y): comparar com a volta atrasada
        self._f_desde = 0.0                  # metros de roda desde a última volta aceita
        self._f_rej_t0 = None
        self.f_conta = {"aceitas": 0, "rejeitadas": 0}
        self.f_dif_m = None                  # |C1 − fusão| na última volta
        self._traco_dir, self._relogio = traco_dir, relogio
        self._traco = None
        self._traco_linhas = 0
        self._lock = threading.Lock()
        self._boas = None                    # None = não está partindo; n = voltas boas seguidas
        self._ancora_parado = None           # (x, y, ticks) desde que as rodas pararam
        self._rodas_trans = 0.0              # metros de translação pelas rodas (acumulado)
        self._hist_rodas = collections.deque()   # (acumulado, x, y) — janela deslizante
        self._ult = None                     # (ticks, yaw) da volta anterior
        self._giros = collections.deque()    # (t, rumo, yaw)
        self.partida = {"passo": None, "resultado": None, "quando": None}
        self.vigias = {"rodas_paradas": 0, "rodas_sem_pose": 0, "giro": 0, "perdido": 0,
                       "fusao": 0}
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
        """Vale pelo validador (C1 cru: idade, saltos, partida, vigias); o
        lugar é o da FUSÃO, integrada até agora."""
        p = self.v.avaliar(max_idade_s)[0]
        if p is None or not self.fusao:
            return p
        with self._lock:
            if self._fus is None:
                return p
            self._integrar(self._clock())
            r = self._f_rumo(self._f_base[2] if self._f_base else None)
            return Pose(self._fus[0], self._fus[1], p.rumo_deg if r is None else r, p.t)

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
            "fusao": {"ligada": self.fusao and self._fus is not None, **self.f_conta,
                      "dif_cm": None if self.f_dif_m is None else round(self.f_dif_m * 100, 1)},
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
        self._fus = self._f_base = self._f_rej_t0 = None
        self._f_hist.clear()
        self._ancora_parado = self._ult = None
        self._buf_parado.clear()
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

    def _on_pose(self, t, x, y, rumo, encaixe, perdido, yaw_meio=None):
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
            # O BNO do MEIO da volta que gerou esta pose (18/11: o de agora fica
            # 0,12–0,15 s adiante e, girando, o vigia D6 disparava à toa).
            yaw = yaw_meio
            if yaw is None:
                try:
                    yaw = self._yaw_fn() if self._yaw_fn else None
                except Exception:
                    yaw = None
            m = self._vigia_rodas(pose, ticks, yaw) or self._vigia_giro(pose, yaw)
            if not m and self.fusao:
                m = self._corrigir(pose, yaw)
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
            if ok and self.fusao:
                self._fus_iniciar(pose)
            self.partida = {"passo": None, "resultado": ("ok: " if ok else "falhou: ") + msg,
                            "quando": time.time()}
            log.info(f"[PoseC1] Partida na fita: {self.partida['resultado']}.")

    # ─── FUSÃO: rodas + BNO entre as voltas, o C1 corrige devagar ───
    def _leituras(self):
        try:
            tk = self._ticks_fn() if self._ticks_fn else None
        except Exception:
            tk = None
        try:
            yaw = self._yaw_fn() if self._yaw_fn else None
        except Exception:
            yaw = None
        try:
            sen = self._sentido_fn() if self._sentido_fn else (1, 1)
        except Exception:
            sen = (1, 1)
        return tk, yaw, sen

    def _f_rumo(self, yaw):
        return None if yaw is None else normaliza_graus(BNO_SENTIDO * yaw + self._f_off)

    def _fus_iniciar(self, pose):
        tk, yaw, _ = self._leituras()
        self._fus = [pose.x_m, pose.y_m]
        if yaw is not None:
            self._f_off = normaliza_graus(pose.rumo_deg - BNO_SENTIDO * yaw)
        self._f_base = None if tk is None else (tk[0], tk[1], yaw)
        self._f_hist.clear()
        self._f_hist.append((pose.t, pose.x_m, pose.y_m))
        self._f_desde, self._f_rej_t0 = 0.0, None
        self.f_dif_m = 0.0

    def _integrar(self, agora):
        """Anda a fusão pelas rodas desde a última integração (sob o lock)."""
        tk, yaw, sen = self._leituras()
        if tk is None:
            return
        if self._f_base is None or yaw is None or self._f_base[2] is None:
            self._f_base = (tk[0], tk[1], yaw)
            return
        te, td, yaw0 = self._f_base
        self._f_base = (tk[0], tk[1], yaw)
        de = max(0.0, tk[0] - te) * self.m_por_tick * (1 if sen[0] >= 0 else -1)
        dd = max(0.0, tk[1] - td) * self.m_por_tick * (1 if sen[1] >= 0 else -1)
        ds = (de + dd) / 2.0
        if ds:
            meio = yaw0 + normaliza_graus(yaw - yaw0) / 2.0
            th = math.radians(BNO_SENTIDO * meio + self._f_off)
            self._fus[0] += ds * math.cos(th)
            self._fus[1] += ds * math.sin(th)
            self._f_desde += abs(ds)
        self._f_hist.append((agora, self._fus[0], self._fus[1]))

    def _corrigir(self, pose, yaw_meio):
        """Uma volta do C1 que já passou nos vigias: corrige a fusão, ou é
        rejeitada. Devolve (chave, motivo) se a discordância passou do tempo."""
        if self._fus is None:
            return None
        self._integrar(self._clock())
        # A volta é a foto de ~f_atraso_s antes da entrega: compara com a fusão
        # daquele instante e aplica a correção na de agora.
        # Interpola entre as duas integrações em volta do instante (fora da
        # missão a pose é lida só a ~10 Hz: o ponto anterior ficaria velho e a
        # fusão iria adiante — pego pelo harness em 18/11).
        tv = pose.t - self.f_atraso_s
        hx, hy = self._fus
        depois = None
        for ht, x, y in reversed(self._f_hist):
            if ht <= tv:
                hx, hy = x, y
                if depois is not None and depois[0] > ht:
                    a = (tv - ht) / (depois[0] - ht)
                    hx, hy = x + a * (depois[1] - x), y + a * (depois[2] - y)
                break
            depois = (ht, x, y)
        ex, ey = pose.x_m - hx, pose.y_m - hy
        self.f_dif_m = math.hypot(ex, ey)
        portao = self.f_portao_m + self.f_portao_cresce * self._f_desde
        aceita = self.f_dif_m <= portao
        if aceita:
            k = self.f_ganho
            self._fus[0] += k * ex
            self._fus[1] += k * ey
            if yaw_meio is not None:
                er = normaliza_graus(pose.rumo_deg - (BNO_SENTIDO * yaw_meio + self._f_off))
                self._f_off = normaliza_graus(self._f_off + self.f_ganho_rumo * er)
            self._f_desde, self._f_rej_t0 = 0.0, None
            self.f_conta["aceitas"] += 1
        else:
            self.f_conta["rejeitadas"] += 1
            if self._f_rej_t0 is None:
                self._f_rej_t0 = pose.t
        self._anotar_traco(pose, aceita)
        if not aceita and pose.t - self._f_rej_t0 >= self.f_discorda_s:
            return "fusao", (f"a pose do C1 e a das rodas discordam há "
                             f"{self.f_discorda_s:.0f} s ({self.f_dif_m * 100:.0f} cm)")
        return None

    def _anotar_traco(self, pose, aceita):
        """Uma linha por volta: C1 cru × fusão (gravar não pode parar nada)."""
        if not self._traco_dir:
            return
        try:
            if self._traco is None or self._traco_linhas >= 500_000:
                if self._traco is not None:
                    self._traco.close()
                os.makedirs(self._traco_dir, exist_ok=True)
                nome = time.strftime("fusao_%Y%m%d_%H%M%S.csv", time.localtime(self._relogio()))
                self._traco = open(os.path.join(self._traco_dir, nome), "w",
                                   encoding="utf-8", buffering=1)
                self._traco.write("hora,t,c1_x_cm,c1_y_cm,c1_rumo,fus_x_cm,fus_y_cm,fus_rumo,"
                                  "aceita,dif_cm,ticks_esq,ticks_dir,yaw,sent_esq,sent_dir\n")
                self._traco_linhas = 0
            h = self._relogio()
            b = self._f_base or (None, None, None)
            sen = self._leituras()[2]
            fr = self._f_rumo(b[2])
            self._traco.write(
                f"{time.strftime('%H:%M:%S', time.localtime(h))}.{int(h * 1000) % 1000:03d},"
                f"{pose.t:.3f},{pose.x_m * 100:.1f},{pose.y_m * 100:.1f},{pose.rumo_deg:.2f},"
                f"{self._fus[0] * 100:.1f},{self._fus[1] * 100:.1f},"
                f"{'' if fr is None else round(fr, 2)},"
                f"{int(aceita)},{self.f_dif_m * 100:.1f},{b[0]},{b[1]},"
                f"{'' if b[2] is None else round(b[2], 2)},{sen[0]},{sen[1]}\n")
            self._traco_linhas += 1
        except Exception as e:
            log.error(f"[PoseC1] traço da fusão: {e}")
            self._traco = None

    # ─── D5 e D6 ────────────────────────────────────
    def _vigia_rodas(self, pose, ticks, yaw):
        if ticks is None:
            return None
        tot = (ticks[0] + ticks[1]) / 2.0          # média das duas rodas, em ticks
        if self._ult is None:
            self._ult = (tot, yaw)
            self._ancora_parado = (pose.t, None, tot)
            self._buf_parado.clear()
            self._rodas_trans = 0.0
            self._hist_rodas.clear()
            self._hist_rodas.append((0.0, pose.x_m, pose.y_m))
            return None
        tot0, yaw0 = self._ult
        self._ult = (tot, yaw)
        # RODAS PARADAS: a pose não pode andar sozinha. 18/11/2026 (3 missões
        # canceladas no 1º giro): "parada" era "menos de 3 cm de roda desde a
        # âncora", e no giro lento (pulsos, inércia) a âncora ficava curta e o
        # balanço da pose girando (~10 cm) disparava. Agora: parada DE VERDADE
        # (nenhum tick há C1_VIGIA_PARADO_S) e a MEDIANA de C1_VIGIA_MEDIANA
        # poses contra a mediana do começo da parada (tremor de ±2,5 cm parado).
        if self._ancora_parado is None or tot != self._ancora_parado[2]:
            self._ancora_parado = (pose.t, None, tot)
            self._buf_parado.clear()
        elif pose.t - self._ancora_parado[0] >= self.parado_s:
            b = self._buf_parado
            b.append((pose.x_m, pose.y_m))
            if len(b) == b.maxlen:
                mx = sorted(p[0] for p in b)[len(b) // 2]
                my = sorted(p[1] for p in b)[len(b) // 2]
                if self._ancora_parado[1] is None:
                    self._ancora_parado = (self._ancora_parado[0], (mx, my), tot)
                else:
                    ax, ay = self._ancora_parado[1]
                    d = math.hypot(mx - ax, my - ay)
                    if d > self.pose_sem_rodas_m:
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
