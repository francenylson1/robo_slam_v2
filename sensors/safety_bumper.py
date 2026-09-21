"""
sensors/safety_bumper.py
Lê o RPLIDAR C1 e mantém a flag `blocked_front`.
Parte do loop de segurança de 50Hz — integrado ao main.py.

FAIL-CLOSED (Fase 1.5 — Blindagem):
A segurança falha "fechada": se não houver varredura VÁLIDA do LIDAR há mais
que LIDAR_FRESH_TIMEOUT_S (LIDAR desconectado, travado ou biblioteca ausente),
`blocked_front` retorna True — o robô fica bloqueado até o dado voltar.
O loop real reconecta automaticamente com backoff progressivo.
Em MOCK puro (dev no PC) o fail-closed fica inativo por padrão, para não travar
o robô simulado; o harness de validação o ativa explicitamente.
"""

import threading
import time
import logging

log = logging.getLogger(__name__)

from config.settings import (
    OBSTACLE_STOP_DISTANCE_M, MOCK_MODE,
    LIDAR_FRESH_TIMEOUT_S, LIDAR_RECONNECT_BACKOFF_S, LIDAR_BAUDRATE,
)

try:
    from rplidar import RPLidar
    RPLIDAR_OK = True
except ImportError:
    RPLIDAR_OK = False
    log.warning("[SafetyBumper] rplidar não disponível — modo MOCK.")


if RPLIDAR_OK:
    class _C1Lidar(RPLidar):
        """
        Adaptador do RPLIDAR C1 para a biblioteca `rplidar` (escrita para A1/A2).

        ⚠️ VALIDADO NO HARDWARE (21/09/2026). Dois desvios do C1:

        1. Baud: 460800 (o padrão da biblioteca é 115200) — ver LIDAR_BAUDRATE.
        2. Motor: o C1 gira sozinho ao ser energizado e NÃO implementa o comando
           SET_PWM (`A5 F0`) dos A1/A2. A `iter_scans()` chama `start_motor()`
           internamente, que envia esse comando; os bytes da carga útil são então
           reinterpretados como novos comandos e o protocolo sai de sincronia —
           o sintoma é "Descriptor length mismatch" no primeiro descritor.
           Neutralizar start_motor/stop_motor resolve; o controle do motor fica
           por conta do DTR.
        """

        def start_motor(self):
            self._serial.dtr = False      # DTR baixo = motor girando
            time.sleep(0.5)

        def stop_motor(self):
            self._serial.dtr = True
            time.sleep(0.1)


class SafetyBumper:
    """
    Monitora a zona frontal do robô (±30° em torno de 0°).
    Se qualquer leitura < OBSTACLE_STOP_DISTANCE_M → blocked_front = True.
    Se o dado do LIDAR envelhecer além de LIDAR_FRESH_TIMEOUT_S e o
    fail-closed estiver ativo → blocked_front = True (independente da varredura).
    """

    FRONT_ARC_DEG  = 30    # ± graus em torno de 0° (frente)
    LIDAR_PORT     = "/dev/ttyUSB0"

    def __init__(self, fail_closed: bool | None = None):
        # fail_closed=None → automático: ativo sempre que o robô está em modo
        # REAL (um LIDAR físico é esperado). Em MOCK fica inativo por padrão.
        self.fail_closed    = (not MOCK_MODE) if fail_closed is None else fail_closed
        self._blocked_scan  = False   # veredito da última varredura avaliada
        self._last_scan_ts  = None    # time.perf_counter() da última varredura válida
        self._running       = False
        self._thread        = None
        self._lidar         = None
        self._nearest_deg   = None   # direção do ponto frontal mais próximo (graus, ±)
        self._nearest_m     = None   # distância desse ponto (m)

    # ─────────────────────────────────────────
    # ESTADO EXPOSTO (lido pelo loop 50Hz)
    # ─────────────────────────────────────────
    @property
    def blocked_front(self) -> bool:
        """Fail-closed: sem varredura fresca → considera bloqueado."""
        if self.fail_closed and not self.healthy:
            return True
        return self._blocked_scan

    @property
    def healthy(self) -> bool:
        """True se houve varredura válida há menos de LIDAR_FRESH_TIMEOUT_S."""
        if self._last_scan_ts is None:
            return False
        return (time.perf_counter() - self._last_scan_ts) <= LIDAR_FRESH_TIMEOUT_S

    def health(self) -> dict:
        """Resumo de saúde do sensor para a telemetria (dashboard/Torre)."""
        age = (None if self._last_scan_ts is None
               else round(time.perf_counter() - self._last_scan_ts, 3))
        return {
            "healthy":         self.healthy,
            "fail_closed":     self.fail_closed,
            "last_scan_age_s": age,
            "nearest_deg":     (None if self._nearest_deg is None
                                else round(self._nearest_deg, 1)),
            "nearest_m":       (None if self._nearest_m is None
                                else round(self._nearest_m, 2)),
        }

    # ─────────────────────────────────────────
    # CICLO DE VIDA
    # ─────────────────────────────────────────
    def start(self):
        self._running = True
        self._thread  = threading.Thread(target=self._scan_loop,
                                          daemon=True, name="SafetyBumper")
        self._thread.start()
        log.info(f"[SafetyBumper] Monitoramento iniciado "
                 f"(fail-closed: {'ATIVO' if self.fail_closed else 'inativo/MOCK'}).")

    def stop(self):
        self._running = False
        # Fechar a porta aqui, com a thread ainda dentro de iter_scans, provoca
        # "[Errno 9] Bad file descriptor" — um ERRO espúrio num desligamento
        # gracioso. Esperar a thread sair do laço (ela mesma desconecta o LIDAR
        # no seu finally) mantém o log limpo. O join é curto: a thread sai na
        # próxima varredura (~70ms a 13.8Hz).
        if self._thread is not None and self._thread.is_alive():
            self._thread.join(timeout=2.0)
        self._disconnect_lidar()

    def _disconnect_lidar(self):
        if self._lidar:
            try:
                self._lidar.stop()
                self._lidar.disconnect()
            except Exception:
                pass
            self._lidar = None

    # ─────────────────────────────────────────
    # LOOP DE VARREDURA (thread)
    # ─────────────────────────────────────────
    def _scan_loop(self):
        if MOCK_MODE:
            log.info("[SafetyBumper] Modo MOCK — varreduras via injeção (feed_scan).")
            while self._running:
                time.sleep(0.1)
            return

        if not RPLIDAR_OK:
            # Modo REAL sem biblioteca: nunca haverá dado fresco, então o
            # fail-closed mantém o robô bloqueado — comportamento desejado.
            log.error("[SafetyBumper] Biblioteca rplidar ausente em modo REAL — "
                      "robô permanece BLOQUEADO (fail-closed).")
            while self._running:
                time.sleep(1.0)
            return

        attempt = 0
        while self._running:
            try:
                self._lidar = _C1Lidar(self.LIDAR_PORT, baudrate=LIDAR_BAUDRATE)
                # Um processo anterior morto deixa o C1 TRANSMITINDO. Sem o STOP
                # abaixo, o resíduo no buffer desalinha o primeiro descritor e a
                # conexão só pega na 2ª ou 3ª tentativa do backoff.
                self._lidar.stop()          # A5 25 — encerra varredura remanescente
                self._lidar.clean_input()
                log.info(f"[SafetyBumper] LIDAR conectado em {self.LIDAR_PORT} "
                         f"@ {LIDAR_BAUDRATE} baud.")
                attempt = 0
                for scan in self._lidar.iter_scans():
                    if not self._running:
                        break
                    self.feed_scan(scan)
                # iter_scans terminou sem exceção → trata como desconexão
            except Exception as e:
                log.error(f"[SafetyBumper] Falha no LIDAR: {e}")
            finally:
                self._disconnect_lidar()

            if not self._running:
                break
            delay = LIDAR_RECONNECT_BACKOFF_S[
                min(attempt, len(LIDAR_RECONNECT_BACKOFF_S) - 1)]
            attempt += 1
            log.warning(f"[SafetyBumper] Sem LIDAR — fail-closed ativo "
                        f"(blocked_front=True). Reconectando em {delay:.0f}s "
                        f"(tentativa {attempt}).")
            time.sleep(delay)

    # ─────────────────────────────────────────
    # AVALIAÇÃO DE VARREDURAS
    # ─────────────────────────────────────────
    def feed_scan(self, scan) -> bool:
        """
        Avalia uma varredura (lista de (quality, angle_deg, distance_mm)),
        atualiza `blocked_front` e renova o timestamp de dado fresco.
        Usado pelo loop real do LIDAR e pelo harness de validação
        (injeção de varreduras sintéticas).
        """
        self._blocked_scan = self._check_front(scan)
        self._last_scan_ts = time.perf_counter()
        return self.blocked_front

    def set_mock_obstacle(self, distance_m: float, angle_deg: float = 0.0) -> bool:
        """
        Monta uma varredura sintética com um único ponto e a avalia.
        Helper de validação em MOCK.
        """
        scan = [(15, angle_deg % 360, distance_m * 1000.0)]
        return self.feed_scan(scan)

    def _check_front(self, scan) -> bool:
        """
        Varre uma vez e faz duas coisas: decide o bloqueio e guarda QUAL ponto do
        arco frontal está mais perto. A direção do obstáculo não muda nada na
        segurança (o bloqueio continua sendo por distância), mas é o que permite
        o rosto animado olhar para o lado certo — ver web/templates/rosto.html.
        """
        bloqueado = False
        perto_ang = None
        perto_m   = None

        for _, angle, distance_mm in scan:
            distance_m = distance_mm / 1000.0
            if distance_m <= 0:
                continue
            # Normaliza ângulo para 0–360
            a = angle % 360
            in_front = (a <= self.FRONT_ARC_DEG) or (a >= 360 - self.FRONT_ARC_DEG)
            if not in_front:
                continue
            if distance_m < OBSTACLE_STOP_DISTANCE_M:
                bloqueado = True
            if perto_m is None or distance_m < perto_m:
                perto_m = distance_m
                # Em graus COM SINAL: negativo à esquerda, positivo à direita.
                perto_ang = a - 360.0 if a > 180.0 else a

        self._nearest_deg = perto_ang
        self._nearest_m   = perto_m
        return bloqueado
