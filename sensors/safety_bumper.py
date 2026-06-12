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
    LIDAR_FRESH_TIMEOUT_S, LIDAR_RECONNECT_BACKOFF_S,
)

try:
    from rplidar import RPLidar
    RPLIDAR_OK = True
except ImportError:
    RPLIDAR_OK = False
    log.warning("[SafetyBumper] rplidar não disponível — modo MOCK.")


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
                self._lidar = RPLidar(self.LIDAR_PORT)
                log.info(f"[SafetyBumper] LIDAR conectado em {self.LIDAR_PORT}.")
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
        for _, angle, distance_mm in scan:
            distance_m = distance_mm / 1000.0
            if distance_m <= 0:
                continue
            # Normaliza ângulo para 0–360
            a = angle % 360
            in_front = (a <= self.FRONT_ARC_DEG) or (a >= 360 - self.FRONT_ARC_DEG)
            if in_front and distance_m < OBSTACLE_STOP_DISTANCE_M:
                return True
        return False
