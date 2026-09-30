"""
slam/missao.py
A MISSÃO: "vá até o POI X" — o primeiro caminho em que um pedido de rede
acaba movendo o robô. Decidida com o professor em 29/09/2026, questão por
questão (fim de docs/FASE4_ARQUITETURA_FROTA.md).

QUEM MOVE O ROBÔ: só esta classe, e só por motors.set_speed(), dentro do
loop de 50 Hz (tick). O dashboard NUNCA manda velocidade: ele pede um POI
(iniciar), e a missão decide o resto. O validate_phase1.py acusa qualquer
outro chamador de set_speed.

COMO ANDA (decisão 2), para cada trecho reto da rota:
  GIRAR    — parado. O Aurora diz QUANTO girar; o BNO (100 Hz) fecha o giro.
             Só passam DIFERENÇAS de ângulo, com o sinal invertido: no Aurora
             a esquerda aumenta, no BNO a direita aumenta.
  RETO     — 12%, com a malha de rumo (HeadingAssist). A cada 0,5 s o Aurora
             corrige a MIRA deslocando a referência, sem zerar o integral.
             8% nos últimos 40 cm.
  ASSENTAR — parado 0,5 s entre fases, antes de conferir.
  Chega a < 15 cm (10 cm na base), ou para onde está se PASSAR do ponto.

O QUE PARA (decisões 3 e 4) — cancela e NÃO retoma:
  PARAR / E-Stop da Torre / joystick / troca de modo (vêm de fora, cancelar)
  bumper · pose inválida (0,3 s) · BNO sem sinal · BNO × Aurora > 10°
  bateria sem permissão · centro do robô dentro da margem · sem avanço
  (5 cm ou 5° a cada 3 s) · encoder × Aurora (rodas no ar, patinando,
  empurrado) · tempo > 2 × estimativa + 20 s · emergência do motor_driver.

A missão vive só na memória: se o serviço reiniciar, o robô volta parado e
sem missão (decisão 3).
"""

import json
import logging
import math
import os
import threading
import time

from sensors.pose_source import normaliza_graus

log = logging.getLogger(__name__)

# Fases
GIRAR, RETO, ASSENTAR = "girando", "reto", "assentando"

# Grupos de fala (decisão 6). None = calado.
FALA_INICIO, FALA_CHEGOU = "missao_inicio", "missao_chegou"
FALA_BASE, FALA_CHEGOU_BASE = "missao_base", "missao_chegou_base"
FALA_PERDIDO, FALA_PRESO = "missao_perdido", "missao_preso"
FALA_APERTADO = "missao_apertado"
FALA_PERTO = "missao_perto"         # parou perto do destino, fora da tolerância


def malha_da_missao(cfg):
    """A malha de rumo DA MISSÃO — separada da do joystick (que é a da Fase 3,
    intocada). Mesmos ganhos; teto da missão, roda lenta nunca abaixo de
    MISSAO_RODA_MIN_PCT e integração condicional (30/09/2026, a "costura").
    Uma fábrica só, usada pelo main.py e pelo harness: a malha testada é a
    malha que roda no robô."""
    from core.heading_assist import HeadingAssist
    return HeadingAssist(
        kp_pct=cfg.HEADING_KP_PCT, ki_pct=cfg.HEADING_KI_PCT,
        limite_integral=cfg.HEADING_INTEGRAL_MAX, trim_pct=cfg.HEADING_TRIM_PCT,
        max_corr_pct=cfg.HEADING_MAX_CORR_PCT, teto_pct=cfg.MISSAO_TETO_PCT,
        invert=cfg.HEADING_INVERT, tol_pct=cfg.HEADING_STRAIGHT_TOL_PCT, enabled=True,
        piso_pct=cfg.MISSAO_RODA_MIN_PCT, integracao_condicional=True,
    )


class Missao:

    def __init__(self, *, motors, pose_source, heading, bumper, nav, assist,
                 state: dict, cfg, base_poi, historico: str | None = None,
                 traco_dir: str | None = None, clock=time.monotonic):
        self.motors   = motors
        self.pose     = pose_source
        self.heading  = heading
        self.bumper   = bumper
        self.nav      = nav
        self.assist   = assist
        self.state    = state
        self.c        = cfg                  # objeto com as constantes MISSAO_*
        self.base_poi = base_poi             # {"nome": "base", "x", "y", "rumo"}
        self.historico = historico
        # Traço de diagnóstico dos RETOS (30/09/2026, para a "costura" de
        # ±10°): uma linha por ciclo, gravada numa thread no fim da missão.
        # Só observa — não muda nada do que a missão faz. None = desligado.
        self.traco_dir = traco_dir
        self._clock   = clock
        self._lock    = threading.Lock()
        self._pendente = None
        self._cancelar_pedido = None         # (motivo, operador) vindo de fora
        self.m        = None                 # missão em andamento (dict)
        self.resultado = None
        self._fala_id = 0
        self.fala     = None                 # {"id": n, "grupo": "..."}

    # ─────────────────────────────────────────
    # DISPONIBILIDADE E PEDIDOS (thread da web)
    # ─────────────────────────────────────────
    @property
    def disponivel(self) -> bool:
        return getattr(self.pose, "fonte", None) is not None

    @property
    def ativa(self) -> bool:
        return self.m is not None or self._pendente is not None

    def _poi(self, nome):
        if nome == self.base_poi["nome"]:
            return dict(self.base_poi)
        return self.nav.poi(nome)

    def planejar(self, nome):
        """(pontos, poi, motivo) da pose ATUAL até o POI. Só calcula."""
        if not self.disponivel:
            return None, None, "este robô não tem localização"
        poi = self._poi(nome)
        if poi is None:
            return None, None, "POI não encontrado no desenho salvo"
        p = self.pose.pose_valida(self.c.POSE_MAX_IDADE_MISSAO_S)
        if p is None:
            return None, poi, f"a pose do robô não vale: {self.pose.motivo()}"
        plan = self.nav.planejador()
        if plan is None:
            return None, poi, "planta ainda não gerada"
        pts, motivo = self._rota(plan, (p.x_m, p.y_m), poi, nome == self.base_poi["nome"])
        return pts, poi, motivo

    def _rota(self, plan, origem, poi, e_base: bool):
        """
        Rota até o POI. Na BASE (decisão de 30/09/2026), se o último trecho
        chegaria muito torto em relação ao rumo da fita, a rota passa antes por
        um ponto de APROXIMAÇÃO, MISSAO_APROX_BASE_M atrás da base na linha do
        rumo: o robô chega andando reto na direção certa e o giro final fica
        pequeno. Medido em 30/09: um giro final de 174° escorregou o robô 11 cm.
        Sem espaço para a aproximação (área proibida, parede), vai direto.
        """
        c = self.c
        destino = (poi["x"], poi["y"])
        pts, motivo = plan.planejar(origem, destino)
        rumo = poi.get("rumo")
        if pts is None or not e_base or rumo is None or len(pts) < 2:
            return pts, motivo
        ux, uy = math.cos(math.radians(rumo)), math.sin(math.radians(rumo))
        (ax, ay), (bx, by) = pts[-2], pts[-1]
        chegada = math.degrees(math.atan2(by - ay, bx - ax))
        if abs(normaliza_graus(chegada - rumo)) <= c.MISSAO_APROX_ALINHADO_DEG:
            return pts, motivo                       # já chega alinhado
        # O ponto precisa de FOLGA da margem: o robô para alguns cm depois
        # (inércia) e escorrega no giro. Na 1ª prova (30/09 12:30) o ponto a
        # 60 cm caiu na beira da margem da M4 e a missão cancelou ali. Sem
        # folga a 60 cm, tenta mais perto da base (45, 30 cm).
        for d in c.MISSAO_APROX_DISTANCIAS_M:
            aprox = (destino[0] - d * ux, destino[1] - d * uy)
            if math.hypot(aprox[0] - origem[0], aprox[1] - origem[1]) < c.MISSAO_CHEGADA_M:
                continue
            if not (self._folga_livre(plan, aprox, c.MISSAO_APROX_FOLGA_M)
                    and self._reta_livre(plan, aprox, destino)):
                continue
            ate, _ = plan.planejar(origem, aprox)
            if ate is None:
                continue
            return [tuple(q) for q in ate] + [destino], motivo
        return pts, motivo

    @staticmethod
    def _folga_livre(plan, xy, raio) -> bool:
        """O ponto e um círculo de `raio` em volta dele fora de toda margem."""
        if not plan.livre(*xy):
            return False
        for k in range(16):
            a = k * math.pi / 8
            if not plan.livre(xy[0] + raio * math.cos(a), xy[1] + raio * math.sin(a)):
                return False
        return True

    def iniciar(self, nome: str, quem: str, rota_vista):
        """
        Pedido de "vá até o POI". rota_vista = os pontos que o operador VIU no
        /mapa. A missão replaneja da pose atual e só aceita se bater com o que
        foi visto (MISSAO_ROTA_TOL_M) — a rota vista é a que o robô segue.
        Dois pedidos: vale o último (o anterior é cancelado, calado).
        """
        if not self.disponivel:
            return False, "este robô não tem localização"
        impedimento = self._impedimento_de_largada()
        if impedimento:
            return False, impedimento
        pts, poi, motivo = self.planejar(nome)
        if pts is None:
            return False, motivo
        if len(pts) < 2 or math.hypot(pts[-1][0] - pts[0][0],
                                      pts[-1][1] - pts[0][1]) < self.c.MISSAO_CHEGADA_M:
            return False, f"o robô já está em {nome}"
        if not self._bate(pts, rota_vista):
            return False, "a rota mudou desde que foi mostrada — veja a rota de novo"
        comp = sum(math.hypot(b[0] - a[0], b[1] - a[1]) for a, b in zip(pts, pts[1:]))
        giros = len(pts) - 1 + (1 if poi.get("rumo") is not None else 0)
        estimativa = (comp / self.c.MISSAO_VEL_ESTIMADA_MS
                      + giros * 90.0 / self.c.MISSAO_GIRO_ESTIMADO_DPS)
        e_base = nome == self.base_poi["nome"]
        with self._lock:
            if self.m is not None:
                self._cancelar_pedido = ("substituída por um novo destino", True)
            self._pendente = {
                "destino": nome, "quem": quem, "rota": [tuple(p) for p in pts],
                "poi": poi, "base": e_base, "comprimento": comp,
                "limite_s": 2 * estimativa + self.c.MISSAO_TEMPO_FOLGA_S,
            }
        log.info(f"[Missao] Pedido de {quem}: ir até {nome} "
                 f"({comp:.2f} m, {len(pts) - 1} trecho(s)).")
        return True, f"indo até {nome}"

    def cancelar(self, motivo: str, operador: bool = True):
        """Chamado de fora (PARAR, joystick, modo, E-Stop). O loop executa."""
        with self._lock:
            if self._pendente is not None:
                self._pendente = None
            if self.m is not None:
                self._cancelar_pedido = (motivo, operador)
        # Parar é imediato, mesmo antes do próximo ciclo.
        if self.m is not None:
            self.motors.stop()

    def _bumper_ate(self, limite_m: float) -> bool:
        """Bumper com distância própria (giro 20 cm, aproximação 30 cm):
        fail-closed (LIDAR sem dado fresco = bloqueado) e algo a menos de
        limite_m do C1, no arco da frente."""
        if not self.bumper.healthy:
            return True
        perto = (self.bumper.health() or {}).get("nearest_m")
        return perto is not None and perto < limite_m

    def _impedimento_de_largada(self):
        st = self.state
        if st.get("fleet_estop"):
            return "E-Stop geral da frota acionado"
        if getattr(self.motors, "_emergency", False):
            return "motor em emergência"
        if self.nav.editando():
            return "o mapa está sendo editado — feche o editor antes"
        if self._bumper_ate(self.c.MISSAO_BUMPER_GIRO_M):
            return "há algo na frente do robô (bumper)"
        if not self.heading.healthy:
            return "o BNO (rumo) está sem sinal"
        bat = st.get("battery") or {}
        if bat.get("missao_permitida") is False:
            return f"bateria não permite missão ({bat.get('nivel', '?')})"
        return None

    def _bate(self, pts, vista) -> bool:
        if not isinstance(vista, (list, tuple)) or len(vista) != len(pts):
            return False
        tol = self.c.MISSAO_ROTA_TOL_M
        try:
            return all(math.hypot(a[0] - b[0], a[1] - b[1]) <= tol
                       for a, b in zip(pts, vista))
        except Exception:
            return False

    # ─────────────────────────────────────────
    # O LOOP (50 Hz)
    # ─────────────────────────────────────────
    def tick(self, dt: float = 0.02):
        with self._lock:
            pend, self._pendente = self._pendente, None
            canc, self._cancelar_pedido = self._cancelar_pedido, None
        if canc is not None and self.m is not None:
            self._encerrar(False, f"cancelada: {canc[0]}", None if canc[1] else FALA_PERDIDO)
        if pend is not None:
            self._comecar(pend)
        if self.m is None:
            return
        try:
            self._passo(dt)
        except Exception as e:           # qualquer erro aqui PARA o robô
            log.exception("[Missao] Erro no passo — parando.")
            self._encerrar(False, f"cancelada: erro interno ({e})", None)

    def _comecar(self, pend):
        agora = self._clock()
        self.m = dict(pend)
        self.m.update({"trecho": 0, "inicio": agora, "inicio_epoch": time.time(),
                       "fase": None, "remiras": 0, "traco": []})
        self.state["mode"] = "AUTONOMO"
        self.resultado = None
        self._falar(FALA_BASE if pend["base"] else FALA_INICIO)
        self._entrar_girar(self.m["rota"][1])

    # ─── vigias ───────────────────────────────
    def _vigias(self, p, bno):
        m, c = self.m, self.c
        if getattr(self.motors, "_emergency", False):
            return "emergência do motor (Regra Nº 0)", None
        if self.state.get("fleet_estop"):
            return "E-Stop geral da frota", None
        # Reto: o bumper normal (50 cm). Girando ou parado: 20 cm
        # (decisão de 29/09). Nos dois, sem dado do LIDAR = para.
        if m["fase"] != RETO:
            bloqueado = self._bumper_ate(c.MISSAO_BUMPER_GIRO_M)
        elif m.get("falta", 9.0) < c.MISSAO_APROX_M:
            bloqueado = self._bumper_ate(c.MISSAO_BUMPER_APROX_M)   # lento, 8%
        else:
            bloqueado = self.bumper.blocked_front                     # 12%: 50 cm
        if bloqueado:
            return "algo à frente (bumper)", None
        if p is None:
            return f"perdeu a localização ({self.pose.motivo(c.POSE_MAX_IDADE_MISSAO_S)})", FALA_PERDIDO
        if bno is None:
            return "o BNO (rumo) ficou sem sinal", FALA_PERDIDO
        bat = self.state.get("battery") or {}
        if bat.get("missao_permitida") is False:
            return f"bateria ({bat.get('nivel', '?')})", None
        if self._clock() - m["inicio"] > m["limite_s"]:
            return f"tempo esgotado ({m['limite_s']:.0f} s)", FALA_PRESO
        plan = self.nav.planejador()
        if plan is not None and not plan.livre(p.x_m, p.y_m):
            return "o centro do robô entrou na margem de uma área", FALA_APERTADO
        # BNO × Aurora desde o começo da fase (girando ou reto). O BNO cresce
        # para a DIREITA e o Aurora para a ESQUERDA: por isso o sinal trocado.
        # No GIRO só compara com o robô PARADO e assentado: girando a ~30°/s,
        # a pose do Aurora chega ~0,3 s atrasada e a diferença passa de 10°
        # sem erro nenhum (P4, 29/09 17:28: "−60° × −50°"; parados, 1–2°).
        assentado = (m["fase"] == GIRAR and m.get("giro_modo") in ("espera", "pausa")
                     and self._clock() - m.get("giro_t0", 0.0) >= 0.4)
        # Girando, o atraso não troca o SENTIDO: BNO e Aurora girando para
        # lados opostos é sinal trocado (espiral), e cancela na hora.
        if m["fase"] == GIRAR and not assentado and m.get("bno0") is not None:
            gb = -normaliza_graus(bno - m["bno0"])
            ga = normaliza_graus(p.rumo_deg - m["rumo0"])
            if abs(gb) > 15.0 and abs(ga) > 5.0 and (gb > 0) != (ga > 0):
                return (f"BNO e Aurora discordam do giro — sentidos opostos "
                        f"({gb:+.0f}° × {ga:+.0f}°)"), FALA_PERDIDO
        if (m["fase"] == RETO or assentado) and m.get("bno0") is not None:
            giro_bno = -normaliza_graus(bno - m["bno0"])
            giro_aur = normaliza_graus(p.rumo_deg - m["rumo0"])
            if abs(normaliza_graus(giro_bno - giro_aur)) > c.MISSAO_DIVERGENCIA_DEG:
                return (f"BNO e Aurora discordam do giro ({giro_bno:+.0f}° × "
                        f"{giro_aur:+.0f}°)"), FALA_PERDIDO
        return None

    def _vigia_avanco(self, medida: float, minimo: float, rotulo: str):
        """medida decresce quando há avanço (distância ou erro de rumo)."""
        m, agora = self.m, self._clock()
        if agora - m["av_t0"] >= self.c.MISSAO_AVANCO_JANELA_S:
            if m["av_v0"] - medida < minimo:
                return f"sem avanço ({rotulo})"
            m["av_t0"], m["av_v0"] = agora, medida
        return None

    def _vigia_encoder(self, p, dt):
        """Rodas × Aurora numa janela: rodas no ar, patinando ou empurrado.

        Lê os CONTADORES de pulsos (left/right_ticks_odo), que a thread dos
        Hall incrementa sempre. NÃO usar current_*_tps: o motor_driver só o
        atualiza com o PID de velocidade ligado, e a missão comanda por
        set_speed — ele fica em zero. Foi o que cancelou a 1ª P3 (29/09,
        16:34) como "empurrado? 42 × 0 cm"."""
        m, c = self.m, self.c
        circ = c.ROBOT_WHEEL_CIRCUMFERENCE_M / c.TICKS_PER_REVOLUTION
        tl = getattr(self.motors, "left_ticks_odo", 0)
        tr = getattr(self.motors, "right_ticks_odo", 0)
        if m.get("odo_ult") is not None:
            # max(0, …): se alguém zerar os contadores, a janela perde um passo
            dl = max(0, tl - m["odo_ult"][0])
            dr = max(0, tr - m["odo_ult"][1])
            m["enc"] += (dl + dr) / 2.0 * circ
            m["enc_total"] = m.get("enc_total", 0.0) + (dl + dr) / 2.0 * circ
        m["odo_ult"] = (tl, tr)
        # Aurora: deslocamento em LINHA RETA na janela (início → agora). Somar
        # passo a passo acumularia o ruído da pose (~5 mm a cada leitura) e
        # esconderia as rodas no ar.
        if m["enc_ult"] is None:
            m["enc_ult"] = (p.x_m, p.y_m)
        if self._clock() - m["enc_t0"] < c.MISSAO_ENCODER_JANELA_S:
            return None
        enc = m["enc"]
        aur = math.hypot(p.x_m - m["enc_ult"][0], p.y_m - m["enc_ult"][1])
        m["enc"], m["enc_t0"], m["enc_ult"] = 0.0, self._clock(), (p.x_m, p.y_m)
        if enc >= c.MISSAO_ENCODER_MIN_M and aur < c.MISSAO_ENCODER_RAZAO * enc:
            return f"rodas giram e o robô não anda (rodas no ar ou patinando: {enc * 100:.0f} × {aur * 100:.0f} cm)"
        if aur >= c.MISSAO_ENCODER_MIN_M and enc < c.MISSAO_ENCODER_RAZAO * aur:
            return f"o robô anda sem as rodas girarem (empurrado? {aur * 100:.0f} × {enc * 100:.0f} cm)"
        return None

    # ─── fases ────────────────────────────────
    def _alvo(self):
        return self.m["rota"][self.m["trecho"] + 1]

    def _marcar_fase(self, fase, p=None, bno=None):
        m = self.m
        m["fase"] = fase
        m["fase_t0"] = self._clock()
        if p is not None:
            m["rumo0"], m["bno0"] = p.rumo_deg, bno

    def _entrar_girar(self, alvo_xy=None, rumo_final=None):
        """Aponta para alvo_xy (ou para rumo_final, no fim). Lê a pose no
        próximo passo — aqui só registra o pedido."""
        self.motors.stop()
        self.assist.soltar()
        m = self.m
        m["giro_alvo_xy"], m["giro_rumo_final"] = alvo_xy, rumo_final
        m["bno_alvo"] = None
        m["rumo0"] = m["bno0"] = None        # a divergência só conta com o giro começado
        m["fase"] = GIRAR
        m["fase_t0"] = self._clock()

    def _passo(self, dt):
        m, c = self.m, self.c
        p = self.pose.pose_valida(c.POSE_MAX_IDADE_MISSAO_S)
        bno = self.heading.yaw_deg if self.heading.healthy else None
        v = self._vigias(p, bno)
        if v:
            self._encerrar(False, f"cancelada: {v[0]}", v[1])
            return

        if m["fase"] == ASSENTAR:
            self.motors.stop()
            if self._clock() - m["fase_t0"] >= c.MISSAO_ASSENTAR_S:
                m["depois"](p, bno)
            return

        if m["fase"] == GIRAR:
            if m["bno_alvo"] is None:
                # Já em cima do ponto? Não se gira para ele: a direção de um
                # ponto a poucos cm é ruído (2ª P3, 29/09). Conta como alcançado.
                if m["giro_alvo_xy"] is not None:
                    gx, gy = m["giro_alvo_xy"]
                    tol = (c.MISSAO_CHEGADA_BASE_M if m["base"] else c.MISSAO_CHEGADA_M)
                    if math.hypot(gx - p.x_m, gy - p.y_m) < min(c.MISSAO_PERTO_M, tol):
                        self._fim_do_trecho(p, bno)
                        return
                # Início do giro: o Aurora diz QUANTO. Converte para o BNO.
                desejado = self._rumo_desejado(p)
                err = normaliza_graus(desejado - p.rumo_deg)       # + = à esquerda
                if abs(err) <= c.MISSAO_GIRO_TOL_DEG:
                    self._fim_do_giro(p, bno)
                    return
                m["bno_alvo"] = bno - err                          # BNO: direita +
                self._marcar_fase(GIRAR, p, bno)
                m["av_t0"], m["av_v0"] = self._clock(), abs(err)
                m["pulsos"] = 0
                m["pulso_ganho"] = c.MISSAO_GIRO_PULSO_GANHO   # °/s, aprende a cada pulso
                m["pulso_bno0"] = None
                m["pulso_pct"] = c.MISSAO_GIRO_FINO_PCT    # regulado pelo que rende
                m["pulso_e0"] = None
                m["pulso_medir"] = False
                m["giro_pct"] = c.MISSAO_GIRO_PCT          # regulado pela velocidade
                m["giro_vel_t"], m["giro_vel_bno"] = self._clock(), bno
                # Giro pequeno (menos que a antecipação) vai direto aos pulsos.
                m["giro_modo"] = ("continuo" if abs(err) > c.MISSAO_GIRO_ANTECIPA_DEG
                                  else "pausa")
                m["giro_t0"] = self._clock() - c.MISSAO_GIRO_PAUSA_S
            e = normaliza_graus(m["bno_alvo"] - bno)               # + = girar à direita
            pct = min(c.MISSAO_GIRO_PCT, c.MISSAO_TETO_PCT)
            lado = (pct, -pct) if e > 0 else (-pct, pct)           # à direita: esquerda p/ frente
            agora = self._clock()
            modo = m["giro_modo"]
            # Medido na P2: parar NO alvo passa do ponto (inércia de 15–39°).
            # Contínuo até faltarem 25°, espera a inércia, termina com pulsos.
            if modo == "continuo":
                if abs(e) <= c.MISSAO_GIRO_ANTECIPA_DEG:
                    self.motors.stop()
                    m["giro_modo"], m["giro_t0"] = "espera", agora
                    return
                av = self._vigia_avanco(abs(e), c.MISSAO_AVANCO_MIN_DEG, "girando")
                if av:
                    self._encerrar(False, f"cancelada: {av}", FALA_PRESO)
                    return
                # Regula a força pela velocidade de giro medida pelo BNO.
                if agora - m["giro_vel_t"] >= c.MISSAO_GIRO_AJUSTE_S:
                    vel = abs(normaliza_graus(bno - m["giro_vel_bno"])) / (agora - m["giro_vel_t"])
                    if vel < c.MISSAO_GIRO_VEL_MIN_DPS:
                        m["giro_pct"] = min(c.MISSAO_GIRO_PCT_MAX, m["giro_pct"] + 1.0)
                    elif vel > c.MISSAO_GIRO_VEL_MAX_DPS:
                        m["giro_pct"] = max(c.MISSAO_GIRO_PCT, m["giro_pct"] - 1.0)
                    m["giro_vel_t"], m["giro_vel_bno"] = agora, bno
                g = min(m["giro_pct"], c.MISSAO_TETO_PCT)
                self.motors.set_speed(*((g, -g) if e > 0 else (-g, g)))
                return
            if modo == "pulso":
                if agora - m["giro_t0"] >= m.get("pulso_dur", c.MISSAO_GIRO_PULSO_S):
                    self.motors.stop()
                    m["giro_modo"], m["giro_t0"] = "pausa", agora
                else:
                    self.motors.set_speed(*m["giro_lado"])
                return
            # "espera" (depois do contínuo) ou "pausa" (depois de um pulso).
            # Só mede quando o robô PAROU de girar (BNO sem mudar 0,3° em
            # 0,25 s), com teto de 2 s: medir ainda girando por inércia fazia
            # o pulso seguinte passar do ponto.
            self.motors.stop()
            espera = c.MISSAO_GIRO_ESPERA_S if modo == "espera" else c.MISSAO_GIRO_PAUSA_S
            if m.get("quieto_ref") is None or abs(normaliza_graus(bno - m["quieto_ref"])) > 0.3:
                m["quieto_ref"], m["quieto_t"] = bno, agora
            parado = agora - m["quieto_t"] >= 0.25
            if agora - m["giro_t0"] < espera or (not parado and agora - m["giro_t0"] < 2.0):
                return
            m["quieto_ref"] = None
            # Os pulsos miram 3°; depois de 5 pulsos, os 5° da aceitação bastam.
            alvo = c.MISSAO_GIRO_ALVO_DEG if m["pulsos"] < 5 else c.MISSAO_GIRO_TOL_DEG
            if abs(e) <= alvo:
                self._assentar(self._conferir_giro)
                return
            # Quanto o último pulso rendeu? Ajusta o ganho (°/s de pulso) e,
            # desde 30/09/2026, a FORÇA do próximo pulso.
            if m.get("pulso_bno0") is not None and m.get("pulso_dur"):
                rendeu = abs(normaliza_graus(bno - m["pulso_bno0"]))
                m["pulso_ganho"] = max(2.0, min(40.0, rendeu / m["pulso_dur"]))
                pct_ant = m["pulso_pct"]
                passou = m["pulso_e0"] is not None and (e > 0) != (m["pulso_e0"] > 0)
                if passou and m["pulso_pct"] > c.MISSAO_GIRO_FINO_PCT:
                    # Passou do ponto: um passo de força para baixo.
                    m["pulso_pct"] = max(c.MISSAO_GIRO_FINO_PCT, m["pulso_pct"] - 1.0)
                elif (not passou and rendeu < c.MISSAO_GIRO_PULSO_POUCO_DEG
                      and m["pulso_dur"] >= c.MISSAO_GIRO_PULSO_MAX_S - 1e-9
                      and m["pulso_pct"] < c.MISSAO_GIRO_PCT_MAX):
                    # Pulso mais longo e quase nada: o piso (ou um rodízio)
                    # segura mais que 8% vence (30/09: 25 pulsos, faltando 9–12°).
                    m["pulso_pct"] = min(c.MISSAO_GIRO_PCT_MAX, m["pulso_pct"] + 1.0)
                    m["pulso_medir"] = True
                if m["pulso_pct"] != pct_ant:
                    m["giro_pct_max"] = max(m.get("giro_pct_max", 0.0), m["pulso_pct"])
                    log.warning(f"[Missao] Pulso de {m['pulso_dur']:.2f} s a {pct_ant:.0f}% "
                                f"rendeu {rendeu:.1f}° — próximo a {m['pulso_pct']:.0f}%"
                                f"{' (passou do ponto)' if passou else ' (giro pesado: piso ou rodízio?)'}.")
                self._anotar_giro(p, bno, f"pulso {pct_ant:.0f}% {m['pulso_dur']:.2f}s "
                                          f"rendeu {rendeu:.1f} faltam {e:+.1f}")
            m["pulsos"] += 1
            if m["pulsos"] > c.MISSAO_GIRO_MAX_PULSOS:
                self._encerrar(False, f"cancelada: não conseguiu apontar "
                                      f"({m['pulsos'] - 1} pulsos, faltam {e:+.0f}°, "
                                      f"força até {m['pulso_pct']:.0f}%)", FALA_PRESO)
                return
            # Mira ~70% do que falta, para não passar do ponto. Depois de subir
            # a força, o 1º pulso é o mais curto: mede antes de insistir.
            if m["pulso_medir"]:
                m["pulso_dur"], m["pulso_medir"] = c.MISSAO_GIRO_PULSO_MIN_S, False
            else:
                m["pulso_dur"] = max(c.MISSAO_GIRO_PULSO_MIN_S,
                                     min(c.MISSAO_GIRO_PULSO_MAX_S,
                                         0.7 * abs(e) / m["pulso_ganho"]))
            m["pulso_bno0"], m["pulso_e0"] = bno, e
            g = min(m["pulso_pct"], c.MISSAO_TETO_PCT)
            lado = (g, -g) if e > 0 else (-g, g)
            m["giro_modo"], m["giro_t0"], m["giro_lado"] = "pulso", agora, lado
            self.motors.set_speed(*lado)
            return

        if m["fase"] == RETO:
            ax, ay = self._alvo()
            dist = math.hypot(ax - p.x_m, ay - p.y_m)
            # Quanto falta AO LONGO do trecho: para quando cruza a linha do
            # ponto. Parar ao entrar no raio de 15 cm deixava sempre ~15 cm de
            # erro (pego pela P0 em 29/09); o raio é só a ACEITAÇÃO, no fim.
            ux, uy = m["dir"]
            falta = (ax - p.x_m) * ux + (ay - p.y_m) * uy
            m["falta"] = falta
            if falta <= c.MISSAO_PARADA_ANTECIPA_M or dist <= 0.03:
                self.motors.stop()
                self._log_trecho(p)
                self._assentar(self._fim_do_trecho)
                return
            m["dmin"] = min(m["dmin"], dist)
            if dist > m["dmin"] + 0.10:
                log.warning(f"[Missao] Afastando-se do ponto (mínimo {m['dmin'] * 100:.0f} cm) "
                            f"— para onde está, sem ré.")
                self.motors.stop()
                self._log_trecho(p)
                self._assentar(self._fim_do_trecho)
                return
            av = self._vigia_avanco(dist, c.MISSAO_AVANCO_MIN_M, "reto")
            if av:
                self._encerrar(False, f"cancelada: {av}", FALA_PRESO)
                return
            enc = self._vigia_encoder(p, dt)
            if enc:
                self._encerrar(False, f"cancelada: {enc}", FALA_PRESO)
                return
            # Mira: a cada 0,5 s o Aurora desloca a referência da malha — aos
            # poucos (no máximo 3° por vez), e NUNCA nos últimos 50 cm, onde a
            # direção do ponto muda a cada centímetro (2ª P3, 29/09).
            mira_err = mira_passo = None
            if dist >= c.MISSAO_MIRA_MIN_M and self._clock() - m["mira_t"] >= c.MISSAO_MIRA_S:
                m["mira_t"] = self._clock()
                err = normaliza_graus(math.degrees(math.atan2(ay - p.y_m, ax - p.x_m))
                                      - p.rumo_deg)
                mira_err = err
                if abs(err) > c.MISSAO_REMIRAR_DEG:
                    self._remirar()
                    return
                ref = self.assist.yaw_ref
                novo = bno - err
                if ref is None:
                    self.assist.mover_referencia(novo)
                else:
                    passo = normaliza_graus(novo - ref)
                    if abs(passo) >= c.MISSAO_MIRA_ZONA_DEG:
                        passo = max(-c.MISSAO_MIRA_PASSO_DEG, min(c.MISSAO_MIRA_PASSO_DEG, passo))
                        self.assist.mover_referencia(ref + passo)
                        mira_passo = passo
            base = c.MISSAO_APROX_PCT if falta < c.MISSAO_APROX_M else c.MISSAO_RETO_PCT
            base = min(base, c.MISSAO_TETO_PCT)
            cmd = self.assist.corrigir(base, base, bno, True, dt)
            esq, dir_ = cmd if cmd is not None else (base, base)
            esq, dir_ = min(esq, c.MISSAO_TETO_PCT), min(dir_, c.MISSAO_TETO_PCT)
            self.motors.set_speed(esq, dir_)
            self._anotar(p, bno, esq, dir_, dist, falta, mira_err, mira_passo)
            return

    TRACO_MAX_LINHAS = 30000          # ~10 min de reto a 50 Hz

    def _anotar(self, p, bno, esq, dir_, dist, falta, mira_err, mira_passo):
        m = self.m
        if self.traco_dir is None or len(m["traco"]) >= self.TRACO_MAX_LINHAS:
            return
        ref = self.assist.yaw_ref
        m["traco"].append((
            round(self._clock() - m["inicio"], 3), m["trecho"] + 1,
            round(bno, 2), None if ref is None else round(ref, 2),
            round(esq, 2), round(dir_, 2),
            round(p.x_m * 100, 1), round(p.y_m * 100, 1), round(p.rumo_deg, 2),
            round(dist * 100, 1), round(falta * 100, 1),
            None if mira_err is None else round(mira_err, 2),
            None if mira_passo is None else round(mira_passo, 2), "reto", ""))

    def _anotar_giro(self, p, bno, nota):
        """Uma linha por pulso de giro medido (força, duração, quanto rendeu)."""
        m = self.m
        if self.traco_dir is None or len(m["traco"]) >= self.TRACO_MAX_LINHAS:
            return
        lado = m.get("giro_lado") or (None, None)
        m["traco"].append((
            round(self._clock() - m["inicio"], 3), m["trecho"] + 1,
            round(bno, 2), None if m.get("bno_alvo") is None else round(m["bno_alvo"], 2),
            lado[0], lado[1],
            round(p.x_m * 100, 1), round(p.y_m * 100, 1), round(p.rumo_deg, 2),
            None, None, None, None, "pulso", nota))

    def _gravar_traco(self, m, texto):
        """Grava o traço numa thread: escrever milhares de linhas dentro do
        loop de 50 Hz atrasaria um ciclo."""
        linhas = m.get("traco") or []
        if self.traco_dir is None or not linhas:
            return
        nome = (time.strftime("traco_%Y%m%d_%H%M%S", time.localtime(m["inicio_epoch"]))
                + f"_{m['destino']}.csv").replace(" ", "_").replace("/", "_")
        caminho = os.path.join(self.traco_dir, nome)
        cab = ("t_s,trecho,bno_graus,ref_graus,esq_pct,dir_pct,x_cm,y_cm,rumo_aurora,"
               "dist_cm,falta_cm,mira_erro_graus,mira_passo_graus,fase,nota")

        def escrever():
            try:
                os.makedirs(self.traco_dir, exist_ok=True)
                with open(caminho, "w", encoding="utf-8") as f:
                    f.write(f"# {m['destino']} — {texto}\n{cab}\n")
                    for r in linhas:
                        f.write(",".join("" if v is None else str(v) for v in r) + "\n")
            except Exception as e:
                log.error(f"[Missao] Falha ao gravar o traço: {e}")
        self.traco_ultimo = caminho
        threading.Thread(target=escrever, daemon=True, name="TracoMissao").start()

    def _rumo_desejado(self, p):
        m = self.m
        if m["giro_rumo_final"] is not None:
            return m["giro_rumo_final"]
        ax, ay = m["giro_alvo_xy"]
        return math.degrees(math.atan2(ay - p.y_m, ax - p.x_m))

    def _log_trecho(self, p):
        """Diagnóstico: o que o Aurora e as rodas dizem de cada trecho reto."""
        m = self.m
        sx, sy = m.get("seg_ini", (p.x_m, p.y_m))
        aur = math.hypot(p.x_m - sx, p.y_m - sy)
        log.info(f"[Missao] Trecho {m['trecho'] + 1}: Aurora {aur * 100:.0f} cm × "
                 f"rodas {m.get('enc_total', 0.0) * 100:.0f} cm "
                 f"(ao mandar parar; a inércia soma alguns cm).")

    def _assentar(self, depois):
        m = self.m
        m["fase"], m["fase_t0"], m["depois"] = ASSENTAR, self._clock(), depois

    def _conferir_giro(self, p, bno):
        """Depois de assentar, o Aurora confere: dentro de 5°? Senão, gira de novo."""
        m, c = self.m, self.c
        err = normaliza_graus(self._rumo_desejado(p) - p.rumo_deg)
        if abs(err) <= c.MISSAO_GIRO_TOL_DEG:
            self._fim_do_giro(p, bno)
            return
        m["remiras"] += 1
        if m["remiras"] > c.MISSAO_GIRO_MAX_TENT:
            self._encerrar(False, f"cancelada: não conseguiu apontar ({err:+.0f}°)", FALA_PRESO)
            return
        self._entrar_girar(m["giro_alvo_xy"], m["giro_rumo_final"])

    def _fim_do_giro(self, p, bno):
        m = self.m
        m["remiras"] = 0
        if m["giro_rumo_final"] is not None:
            self._conferir_depois_do_giro_final(p)
            return
        self._entrar_reto(p, bno)

    def _conferir_depois_do_giro_final(self, p):
        """
        O giro final ESCORREGA o robô (30/09/2026: 11 cm num giro de 174°, e
        a missão dizia "chegou a 3 cm"). Depois dele, confere a POSIÇÃO de novo:
        dentro da tolerância → chegou; fora → corrige MISSAO_CORRECOES_FINAIS
        vez(es), replanejando de onde está; fora depois disso → encerra dizendo
        a verdade (não finge que chegou).
        """
        m, c = self.m, self.c
        poi = m["poi"]
        dist = math.hypot(poi["x"] - p.x_m, poi["y"] - p.y_m)
        tol = c.MISSAO_CHEGADA_BASE_M if m["base"] else c.MISSAO_CHEGADA_M
        m["erro_final_m"] = dist
        if dist <= tol:
            self._chegou()
            return
        if m.get("correcoes", 0) >= c.MISSAO_CORRECOES_FINAIS:
            self._encerrar(False, f"parou perto de {m['destino']}: a {dist * 100:.0f} cm "
                                  f"depois do giro final (tolerância {tol * 100:.0f} cm)",
                           FALA_PERTO)
            return
        m["correcoes"] = m.get("correcoes", 0) + 1
        log.warning(f"[Missao] Depois do giro final ficou a {dist * 100:.0f} cm de "
                    f"{m['destino']} — corrigindo ({m['correcoes']}ª vez).")
        # Corrigir não conta como replanejamento por caminho apertado.
        self._replanejar(p, "correção depois do giro final", conta=False)

    def _entrar_reto(self, p, bno):
        m, c = self.m, self.c
        ax, ay = self._alvo()
        plan = self.nav.planejador()
        if plan is not None and not self._reta_livre(plan, (p.x_m, p.y_m), (ax, ay)):
            self._replanejar(p, "a reta até o próximo ponto cruza a margem")
            return
        self.assist.soltar()
        err = normaliza_graus(math.degrees(math.atan2(ay - p.y_m, ax - p.x_m)) - p.rumo_deg)
        self.assist.mover_referencia(bno - err)
        self._marcar_fase(RETO, p, bno)
        agora = self._clock()
        dist = math.hypot(ax - p.x_m, ay - p.y_m)
        m["dir"] = ((ax - p.x_m) / dist, (ay - p.y_m) / dist) if dist > 1e-6 else (1.0, 0.0)
        m.update({"dmin": dist, "mira_t": agora, "av_t0": agora, "av_v0": dist,
                  "enc": 0.0, "aur": 0.0, "enc_t0": agora, "enc_ult": None,
                  "odo_ult": None, "enc_total": 0.0, "seg_ini": (p.x_m, p.y_m),
                  "falta": dist})

    @staticmethod
    def _reta_livre(plan, a, b) -> bool:
        n = int(math.hypot(b[0] - a[0], b[1] - a[1]) / 0.02) + 1
        return all(plan.livre(a[0] + (b[0] - a[0]) * k / n, a[1] + (b[1] - a[1]) * k / n)
                   for k in range(n + 1))

    def _remirar(self):
        m = self.m
        m["remiras"] += 1
        if m["remiras"] > self.c.MISSAO_GIRO_MAX_TENT:
            self._encerrar(False, "cancelada: saiu da mira várias vezes", FALA_PRESO)
            return
        log.warning("[Missao] Mira fora de 20° no reto — parando para girar de novo.")
        self._entrar_girar(self._alvo())

    def _replanejar(self, p, motivo: str, conta: bool = True):
        """Rota nova de onde o robô está até o mesmo destino (decisão de
        29/09). Mesmas regras do planejador; sem rota, ou replanejamentos
        demais, para com a fala de caminho apertado. conta=False: a correção
        depois do giro final, que tem limite próprio."""
        m, c = self.m, self.c
        if conta and m.get("replanos", 0) >= c.MISSAO_MAX_REPLANOS:
            self._encerrar(False, f"cancelada: {motivo} (replanejou {m['replanos']} vezes)",
                           FALA_APERTADO)
            return
        plan = self.nav.planejador()
        poi = m["poi"]
        pts, mot = (self._rota(plan, (p.x_m, p.y_m), poi, m["base"])
                    if plan is not None else (None, "sem planejador"))
        if pts is None:
            self._encerrar(False, f"cancelada: {motivo}; sem rota nova ({mot})", FALA_APERTADO)
            return
        if conta:
            m["replanos"] = m.get("replanos", 0) + 1
        m["rota"] = [tuple(q) for q in pts]
        m["trecho"] = 0
        m["limite_s"] += c.MISSAO_TEMPO_FOLGA_S
        vez = f"{m['replanos']}ª vez" if conta else "correção, fora da conta"
        log.warning(f"[Missao] {motivo} — replanejou de onde está "
                    f"({len(pts) - 1} trecho(s), {vez}).")
        self._entrar_girar(self._alvo())

    def _ultimo_trecho(self) -> bool:
        return self.m["trecho"] + 2 >= len(self.m["rota"])

    def _fim_do_trecho(self, p, bno):
        m, c = self.m, self.c
        if self._ultimo_trecho():
            ax, ay = self._alvo()
            dist = math.hypot(ax - p.x_m, ay - p.y_m)
            tol = c.MISSAO_CHEGADA_BASE_M if m["base"] else c.MISSAO_CHEGADA_M
            m["erro_final_m"] = dist
            if dist > tol:
                # Fala própria (decisão de 30/09/2026): antes era "Estou preso,
                # preciso de ajuda" — e o robô NÃO está preso, só parou perto.
                self._encerrar(False, f"parou perto de {m['destino']}: a {dist * 100:.0f} cm "
                               f"(tolerância {tol * 100:.0f} cm)", FALA_PERTO)
                return
        if not self._ultimo_trecho():
            m["trecho"] += 1
            plan = self.nav.planejador()
            if plan is not None and not self._reta_livre(plan, (p.x_m, p.y_m), self._alvo()):
                self._replanejar(p, "a reta até o próximo ponto cruza a margem")
                return
            self._entrar_girar(self._alvo())
            return
        rumo = m["poi"].get("rumo")
        if rumo is not None:
            self._entrar_girar(None, rumo_final=rumo)
            return
        self._chegou()

    def _chegou(self):
        m = self.m
        dur = self._clock() - m["inicio"]
        erro = m.get("erro_final_m")
        extra = f", a {erro * 100:.0f} cm do ponto" if erro is not None else ""
        self._encerrar(True, f"chegou em {m['destino']} ({dur:.0f} s{extra})",
                       FALA_CHEGOU_BASE if m["base"] else FALA_CHEGOU)

    # ─── fim ──────────────────────────────────
    def _encerrar(self, ok: bool, texto: str, fala):
        m = self.m
        self.motors.stop()
        self.assist.soltar()
        self.state["mode"] = "JOYSTICK"
        dur = self._clock() - m["inicio"] if m else 0.0
        self.resultado = {"ok": ok, "texto": texto, "quando": time.time(),
                          "destino": m["destino"] if m else None,
                          "duracao_s": round(dur, 1)}
        (log.info if ok else log.warning)(f"[Missao] {texto}")
        if fala:
            self._falar(fala)
        if self.historico and m:
            try:
                os.makedirs(os.path.dirname(self.historico), exist_ok=True)
                with open(self.historico, "a", encoding="utf-8") as f:
                    f.write(json.dumps({
                        "inicio": time.strftime("%Y-%m-%d %H:%M:%S",
                                                time.localtime(m["inicio_epoch"])),
                        "destino": m["destino"], "quem": m["quem"],
                        "rota": [[round(x, 3), round(y, 3)] for x, y in m["rota"]],
                        "comprimento_m": round(m["comprimento"], 2),
                        "ok": ok, "resultado": texto, "duracao_s": round(dur, 1),
                        # 30/09: força máxima que o giro em pulsos precisou
                        # (> 8% = piso pesado ou rodízio brigando).
                        "giro_pct_max": m.get("giro_pct_max"),
                    }, ensure_ascii=False) + "\n")
            except Exception as e:
                log.error(f"[Missao] Falha ao gravar o histórico: {e}")
        if m:
            self._gravar_traco(m, texto)
        self.m = None

    def _falar(self, grupo):
        self._fala_id += 1
        self.fala = {"id": self._fala_id, "grupo": grupo}

    # ─────────────────────────────────────────
    def estado(self) -> dict:
        m = self.m
        d = {"disponivel": self.disponivel, "ativa": m is not None,
             "resultado": self.resultado, "fala": self.fala}
        if not self.disponivel:
            d["motivo"] = "este robô não tem localização"
        if m is not None:
            p = self.pose.pose_valida()
            falta = None
            if p is not None:
                pts = [(p.x_m, p.y_m)] + m["rota"][m["trecho"] + 1:]
                falta = sum(math.hypot(b[0] - a[0], b[1] - a[1]) for a, b in zip(pts, pts[1:]))
            d.update({"destino": m["destino"], "quem": m["quem"],
                      "fase": m["fase"] if m["fase"] != ASSENTAR else "parado",
                      "trecho": m["trecho"] + 1, "trechos": len(m["rota"]) - 1,
                      "falta_m": None if falta is None else round(falta, 2),
                      "tempo_s": round(self._clock() - m["inicio"], 1),
                      "rota": [[round(x, 3), round(y, 3)] for x, y in m["rota"]]})
        return d
