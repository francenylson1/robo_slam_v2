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


class Missao:

    def __init__(self, *, motors, pose_source, heading, bumper, nav, assist,
                 state: dict, cfg, base_poi, historico: str | None = None,
                 clock=time.monotonic):
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
        pts, motivo = plan.planejar((p.x_m, p.y_m), (poi["x"], poi["y"]))
        return pts, poi, motivo

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

    def _impedimento_de_largada(self):
        st = self.state
        if st.get("fleet_estop"):
            return "E-Stop geral da frota acionado"
        if getattr(self.motors, "_emergency", False):
            return "motor em emergência"
        if self.nav.editando():
            return "o mapa está sendo editado — feche o editor antes"
        if self.bumper.blocked_front:
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
                       "fase": None, "remiras": 0})
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
        if self.bumper.blocked_front:
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
            return "o centro do robô entrou na margem de uma área", FALA_PERDIDO
        # BNO × Aurora desde o começo da fase (girando ou reto). O BNO cresce
        # para a DIREITA e o Aurora para a ESQUERDA: por isso o sinal trocado.
        if m["fase"] in (GIRAR, RETO) and m.get("bno0") is not None:
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
        """Rodas × Aurora numa janela: rodas no ar, patinando ou empurrado."""
        m, c = self.m, self.c
        circ = c.ROBOT_WHEEL_CIRCUMFERENCE_M / c.TICKS_PER_REVOLUTION
        m["enc"] += (abs(self.motors.current_left_tps)
                     + abs(self.motors.current_right_tps)) / 2.0 * dt * circ
        if m["enc_ult"] is not None:
            m["aur"] += math.hypot(p.x_m - m["enc_ult"][0], p.y_m - m["enc_ult"][1])
        m["enc_ult"] = (p.x_m, p.y_m)
        if self._clock() - m["enc_t0"] < c.MISSAO_ENCODER_JANELA_S:
            return None
        enc, aur = m["enc"], m["aur"]
        m["enc"], m["aur"], m["enc_t0"] = 0.0, 0.0, self._clock()
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
                self.motors.set_speed(*lado)
                return
            if modo == "pulso":
                if agora - m["giro_t0"] >= c.MISSAO_GIRO_PULSO_S:
                    self.motors.stop()
                    m["giro_modo"], m["giro_t0"] = "pausa", agora
                else:
                    self.motors.set_speed(*m["giro_lado"])
                return
            # "espera" (depois do contínuo) ou "pausa" (depois de um pulso)
            self.motors.stop()
            espera = c.MISSAO_GIRO_ESPERA_S if modo == "espera" else c.MISSAO_GIRO_PAUSA_S
            if agora - m["giro_t0"] < espera:
                return
            if abs(e) <= c.MISSAO_GIRO_TOL_DEG:
                self._assentar(self._conferir_giro)
                return
            m["pulsos"] += 1
            if m["pulsos"] > c.MISSAO_GIRO_MAX_PULSOS:
                self._encerrar(False, f"cancelada: não conseguiu apontar "
                                      f"({m['pulsos'] - 1} pulsos, faltam {e:+.0f}°)", FALA_PRESO)
                return
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
            if falta <= 0.02 or dist <= 0.03:
                self.motors.stop()
                self._assentar(self._fim_do_trecho)
                return
            m["dmin"] = min(m["dmin"], dist)
            if dist > m["dmin"] + 0.10:
                log.warning(f"[Missao] Afastando-se do ponto (mínimo {m['dmin'] * 100:.0f} cm) "
                            f"— para onde está, sem ré.")
                self.motors.stop()
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
            # Mira: a cada 0,5 s o Aurora desloca a referência da malha.
            if self._clock() - m["mira_t"] >= c.MISSAO_MIRA_S:
                m["mira_t"] = self._clock()
                err = normaliza_graus(math.degrees(math.atan2(ay - p.y_m, ax - p.x_m))
                                      - p.rumo_deg)
                if abs(err) > c.MISSAO_REMIRAR_DEG:
                    self._remirar()
                    return
                self.assist.mover_referencia(bno - err)
            base = c.MISSAO_APROX_PCT if falta < c.MISSAO_APROX_M else c.MISSAO_RETO_PCT
            base = min(base, c.MISSAO_TETO_PCT)
            cmd = self.assist.corrigir(base, base, bno, True, dt)
            esq, dir_ = cmd if cmd is not None else (base, base)
            self.motors.set_speed(min(esq, c.MISSAO_TETO_PCT), min(dir_, c.MISSAO_TETO_PCT))
            return

    def _rumo_desejado(self, p):
        m = self.m
        if m["giro_rumo_final"] is not None:
            return m["giro_rumo_final"]
        ax, ay = m["giro_alvo_xy"]
        return math.degrees(math.atan2(ay - p.y_m, ax - p.x_m))

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
            self._chegou()
            return
        self._entrar_reto(p, bno)

    def _entrar_reto(self, p, bno):
        m, c = self.m, self.c
        ax, ay = self._alvo()
        plan = self.nav.planejador()
        if plan is not None and not self._reta_livre(plan, (p.x_m, p.y_m), (ax, ay)):
            self._encerrar(False, "cancelada: o caminho até o próximo ponto cruza a margem", FALA_PERDIDO)
            return
        self.assist.soltar()
        err = normaliza_graus(math.degrees(math.atan2(ay - p.y_m, ax - p.x_m)) - p.rumo_deg)
        self.assist.mover_referencia(bno - err)
        self._marcar_fase(RETO, p, bno)
        agora = self._clock()
        dist = math.hypot(ax - p.x_m, ay - p.y_m)
        m["dir"] = ((ax - p.x_m) / dist, (ay - p.y_m) / dist) if dist > 1e-6 else (1.0, 0.0)
        m.update({"dmin": dist, "mira_t": agora, "av_t0": agora, "av_v0": dist,
                  "enc": 0.0, "aur": 0.0, "enc_t0": agora, "enc_ult": None})

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
                self._encerrar(False, f"parou a {dist * 100:.0f} cm de {m['destino']} "
                               f"(tolerância {tol * 100:.0f} cm)", FALA_PRESO)
                return
        if not self._ultimo_trecho():
            m["trecho"] += 1
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
                    }, ensure_ascii=False) + "\n")
            except Exception as e:
                log.error(f"[Missao] Falha ao gravar o histórico: {e}")
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
