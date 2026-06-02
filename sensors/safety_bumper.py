"""
sensors/safety_bumper.py
Lê o RPLIDAR C1 e mantém a flag `blocked_front`.
Parte do loop de segurança de 50Hz — integrado ao main.py.
"""

import threading
import time
import logging

log = logging.getLogger(__name__)

from config.settings import OBSTACLE_STOP_DISTANCE_M, MOCK_MODE

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
    """

    FRONT_ARC_DEG  = 30    # ± graus em torno de 0° (frente)
    LIDAR_PORT     = "/dev/ttyUSB0"

    def __init__(self):
        self.blocked_front = False
        self._running      = False
        self._thread       = None
        self._lidar        = None

    def start(self):
        self._running = True
        self._thread  = threading.Thread(target=self._scan_loop,
                                          daemon=True, name="SafetyBumper")
        self._thread.start()
        log.info("[SafetyBumper] Monitoramento iniciado.")

    def stop(self):
        self._running = False
        if self._lidar:
            try:
                self._lidar.stop()
                self._lidar.disconnect()
            except Exception:
                pass

    def _scan_loop(self):
        if MOCK_MODE or not RPLIDAR_OK:
            log.info("[SafetyBumper] Modo MOCK — blocked_front sempre False.")
            while self._running:
                time.sleep(0.1)
            return

        try:
            self._lidar = RPLidar(self.LIDAR_PORT)
            for scan in self._lidar.iter_scans():
                if not self._running:
                    break
                self.feed_scan(scan)
        except Exception as e:
            log.error(f"[SafetyBumper] Erro no scan: {e}")

    def feed_scan(self, scan) -> bool:
        """
        Avalia uma varredura (lista de (quality, angle_deg, distance_mm)) e
        atualiza `blocked_front`. Usado pelo loop real do LIDAR e pelo harness
        de validação (injeção de varreduras sintéticas).
        """
        self.blocked_front = self._check_front(scan)
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
