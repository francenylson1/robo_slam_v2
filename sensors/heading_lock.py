"""
sensors/heading_lock.py
Lê o BNO085 (módulo GY-BNO08x) em modo UART-RVC e fornece o Yaw atual
para correção de linha reta. Integrado ao loop de 50Hz do main.py.

POR QUE UART-RVC E NÃO I2C:
O controlador I2C de hardware da Raspberry Pi tem um bug de silício conhecido
— não respeita clock stretching — e o BNO085 (protocolo SHTP) o usa
intensamente, causando travamentos. No modo UART-RVC (PS0=3V3, PS1=GND) o
sensor transmite Yaw/Pitch/Roll prontos a 100Hz / 115200 baud pelo pino SDA
(que vira TX) → GPIO15/RXD da Pi. Fiação completa: docs/BNO085_UART_RVC.md

Quadro RVC (19 bytes): AA AA | índice | yaw | pitch | roll | accX | accY |
accZ | 3 reservados | checksum — int16 little-endian em centésimos de grau.
checksum = soma dos bytes 2..17 & 0xFF.
"""

import time
import threading
import logging
import random

log = logging.getLogger(__name__)

from config.settings import GPIO_AVAILABLE, MOCK_MODE, BNO_UART_PORT, BNO_UART_BAUD

try:
    import serial
    SERIAL_OK = True
except ImportError:
    SERIAL_OK = False
    log.warning("[HeadingLock] pyserial não disponível — modo MOCK.")

RVC_HEADER    = b"\xAA\xAA"
RVC_FRAME_LEN = 19


class HeadingLock:
    """
    Mantém self.yaw_deg atualizado (100Hz no hardware via UART-RVC; injetado
    em MOCK) e calcula o erro em relação ao Yaw travado (linha reta).
    """

    def __init__(self):
        self.yaw_deg        = 0.0
        self.locked_yaw     = None   # Yaw travado para linha reta
        self._running       = False
        self._thread        = None
        self._serial        = None
        self._last_frame_ts = None   # perf_counter do último quadro RVC válido
        self.mock_yaw       = 0.0    # Yaw simulado em MOCK (graus)
        self.mock_noise_deg = 0.0    # ruído ± aplicado ao mock_yaw (graus)

        if SERIAL_OK and GPIO_AVAILABLE:
            try:
                self._serial = serial.Serial(BNO_UART_PORT, BNO_UART_BAUD,
                                             timeout=0.1)
                log.info(f"[HeadingLock] BNO085 UART-RVC em {BNO_UART_PORT} "
                         f"@ {BNO_UART_BAUD} baud.")
            except Exception as e:
                log.error(f"[HeadingLock] Falha ao abrir {BNO_UART_PORT}: {e} — "
                          "verifique raspi-config (serial HW on, console off) "
                          "e a fiação (docs/BNO085_UART_RVC.md).")

    # ─────────────────────────────────────────
    # PARSER DO QUADRO RVC (puro — validável em MOCK)
    # ─────────────────────────────────────────
    @staticmethod
    def parse_rvc_frame(frame: bytes) -> float | None:
        """
        Valida e decodifica um quadro RVC de 19 bytes.
        Retorna o Yaw em graus ou None (header/checksum inválido).
        """
        if len(frame) != RVC_FRAME_LEN or frame[0:2] != RVC_HEADER:
            return None
        if (sum(frame[2:18]) & 0xFF) != frame[18]:
            return None
        return int.from_bytes(frame[3:5], "little", signed=True) / 100.0

    # ─────────────────────────────────────────
    # CICLO DE VIDA
    # ─────────────────────────────────────────
    def start(self):
        self._running = True
        self._thread  = threading.Thread(target=self._read_loop,
                                          daemon=True, name="HeadingLock")
        self._thread.start()

    def stop(self):
        self._running = False
        if self._serial:
            try:
                self._serial.close()
            except Exception:
                pass

    # ─────────────────────────────────────────
    # INTERFACE (inalterada — MOCK e validação intactos)
    # ─────────────────────────────────────────
    def set_mock_yaw(self, yaw: float):
        """Define o Yaw simulado (graus) para uso em MOCK / validação."""
        self.mock_yaw = yaw

    def read_once(self) -> float:
        """
        Passo de leitura síncrono: atualiza e devolve yaw_deg.
        Em MOCK aplica mock_yaw (+ruído). No hardware, o yaw é atualizado
        pela thread UART a 100Hz — aqui apenas devolve o valor corrente.
        """
        if MOCK_MODE or self._serial is None:
            if self.mock_noise_deg:
                self.yaw_deg = self.mock_yaw + random.uniform(
                    -self.mock_noise_deg, self.mock_noise_deg)
            else:
                self.yaw_deg = self.mock_yaw
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

    @property
    def healthy(self) -> bool:
        """True se um quadro RVC válido chegou há < 1s (em MOCK: sempre True)."""
        if MOCK_MODE or self._serial is None:
            return True
        if self._last_frame_ts is None:
            return False
        return (time.perf_counter() - self._last_frame_ts) <= 1.0

    # ─────────────────────────────────────────
    # THREAD DE LEITURA
    # ─────────────────────────────────────────
    def _read_loop(self):
        if MOCK_MODE or self._serial is None:
            while self._running:
                self.read_once()
                time.sleep(0.02)  # 50Hz
            return

        # Hardware: consome o fluxo RVC (100Hz) com ressincronização por header
        buf = b""
        while self._running:
            try:
                buf += self._serial.read(RVC_FRAME_LEN)
                while True:
                    i = buf.find(RVC_HEADER)
                    if i < 0:
                        buf = buf[-1:]          # guarda 1 byte (header partido)
                        break
                    if len(buf) - i < RVC_FRAME_LEN:
                        buf = buf[i:]           # quadro incompleto — aguarda
                        break
                    yaw = self.parse_rvc_frame(buf[i:i + RVC_FRAME_LEN])
                    if yaw is None:
                        buf = buf[i + 2:]       # checksum ruim — ressincroniza
                        continue
                    self.yaw_deg        = yaw
                    self._last_frame_ts = time.perf_counter()
                    buf = buf[i + RVC_FRAME_LEN:]
            except Exception as e:
                log.error(f"[HeadingLock] Erro na UART: {e}")
                time.sleep(0.5)
