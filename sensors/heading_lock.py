"""
sensors/heading_lock.py
Lê o BNO085 via I2C e fornece o Yaw atual para correção de linha reta.
Integrado ao loop de 50Hz do main.py.
"""

import time
import threading
import logging
import math
import random

log = logging.getLogger(__name__)

from config.settings import GPIO_AVAILABLE, MOCK_MODE, I2C_BUS, I2C_ADDR_BNO085

try:
    import smbus2
    SMBUS_OK = True
except ImportError:
    SMBUS_OK = False


class HeadingLock:
    """
    Lê quaterniões do BNO085 e calcula Yaw (graus).
    Usado pelo loop de controle para micro-ajustar as rodas
    e manter linha reta.
    """

    # Registros básicos do BNO085 para leitura de Euler/quaternião
    # O BNO085 usa o protocolo SHTP; aqui usamos leitura simplificada via I2C
    BNO085_I2C_ADDR    = I2C_ADDR_BNO085
    REPORT_ROTATION_QT = 0x05   # Rotation Vector

    def __init__(self):
        self.yaw_deg        = 0.0
        self.locked_yaw     = None   # Yaw travado para linha reta
        self._running       = False
        self._thread        = None
        self._bus           = None
        self.mock_yaw       = 0.0    # Yaw simulado em MOCK (graus)
        self.mock_noise_deg = 0.0    # ruído ± aplicado ao mock_yaw (graus)

        if SMBUS_OK and GPIO_AVAILABLE:
            try:
                self._bus = smbus2.SMBus(I2C_BUS)
                log.info(f"[HeadingLock] BNO085 conectado (addr=0x{self.BNO085_I2C_ADDR:02X}).")
            except Exception as e:
                log.error(f"[HeadingLock] Falha I2C: {e}")

    def start(self):
        self._running = True
        self._thread  = threading.Thread(target=self._read_loop,
                                          daemon=True, name="HeadingLock")
        self._thread.start()

    def stop(self):
        self._running = False

    def set_mock_yaw(self, yaw: float):
        """Define o Yaw simulado (graus) para uso em MOCK / validação."""
        self.mock_yaw = yaw

    def read_once(self) -> float:
        """Passo de leitura síncrono: atualiza e devolve yaw_deg."""
        try:
            self.yaw_deg = self._read_yaw()
        except Exception as e:
            log.warning(f"[HeadingLock] Erro de leitura: {e}")
        return self.yaw_deg

    def lock_heading(self):
        """Trava o Yaw atual como referência de linha reta."""
        self.locked_yaw = self.yaw_deg
        log.info(f"[HeadingLock] Yaw travado em {self.locked_yaw:.1f}°")

    def get_yaw_error(self) -> float:
        """
        Retorna o desvio em graus em relação ao Yaw travado.
        Positivo = desviou para direita. Negativo = desviou para esquerda.
        """
        if self.locked_yaw is None:
            return 0.0
        error = self.yaw_deg - self.locked_yaw
        # Normaliza para [-180, 180]
        if error > 180:
            error -= 360
        elif error < -180:
            error += 360
        return error

    def _read_loop(self):
        while self._running:
            self.read_once()
            time.sleep(0.02)  # 50Hz

    def _read_yaw(self) -> float:
        if MOCK_MODE or not self._bus:
            # Em MOCK retorna o Yaw simulado, com ruído opcional limitado.
            if self.mock_noise_deg:
                return self.mock_yaw + random.uniform(-self.mock_noise_deg, self.mock_noise_deg)
            return self.mock_yaw

        # NOTA: leitura real do BNO085 exige o protocolo SHTP — implementar com
        # a lib adafruit-circuitpython-bno08x na fase de hardware. O bloco abaixo
        # é um placeholder e NÃO retorna quaternião válido em hardware.
        try:
            data = self._bus.read_i2c_block_data(self.BNO085_I2C_ADDR, 0x00, 8)
            # Converte bytes para quaterniões (formato BNO085)
            qi = (data[1] << 8 | data[0]) / 16384.0
            qj = (data[3] << 8 | data[2]) / 16384.0
            qk = (data[5] << 8 | data[4]) / 16384.0
            qr = (data[7] << 8 | data[6]) / 16384.0
            # Quaternião → Yaw (ângulo Z)
            yaw_rad = math.atan2(2*(qr*qk + qi*qj), 1 - 2*(qj*qj + qk*qk))
            return math.degrees(yaw_rad)
        except Exception:
            return self.yaw_deg
