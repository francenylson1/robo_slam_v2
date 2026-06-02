"""
sensors/battery_monitor.py
Leitura da tensão da bateria via ADS1115 (canal A0) e divisor resistivo.
Divisor: R1=100kΩ + R2=6.8kΩ → Vout_max=2.67V para Vbat=42V.
Atualiza a cada BATTERY_READ_INTERVAL_S segundos em thread dedicada.
"""

import time
import threading
import logging

log = logging.getLogger(__name__)

from config.settings import (
    GPIO_AVAILABLE, MOCK_MODE,
    I2C_BUS, I2C_ADDR_ADS1115,
    BATTERY_R1_OHM, BATTERY_R2_OHM,
    BATTERY_MAX_V, BATTERY_MIN_V,
    BATTERY_READ_INTERVAL_S,
)

try:
    import smbus2
    SMBUS_OK = True
except ImportError:
    SMBUS_OK = False
    log.warning("[BatteryMonitor] smbus2 não disponível — modo MOCK.")


class BatteryMonitor:
    """
    Lê a tensão da bateria de 42V via divisor resistivo + ADS1115.
    Publica voltage_v e percent em thread daemon.
    """

    # Configuração ADS1115 — single-shot, canal A0, ±4.096V, 128 SPS
    ADS1115_POINTER_CONVERSION = 0x00
    ADS1115_POINTER_CONFIG     = 0x01
    CONFIG_OS_SINGLE           = 0x8000
    CONFIG_MUX_AIN0_GND        = 0x4000   # A0 vs GND
    CONFIG_PGA_4096            = 0x0200   # ±4.096V
    CONFIG_MODE_SINGLE         = 0x0100
    CONFIG_DR_128SPS           = 0x0080
    CONFIG_CQUE_NONE           = 0x0003

    ADS1115_FULL_SCALE_MV      = 4096.0
    ADS1115_RESOLUTION         = 32768.0  # 2^15

    def __init__(self):
        self.voltage_v   = 0.0
        self.percent     = 0.0
        self._running    = False
        self._thread     = None
        self._bus        = None
        self.mock_vbat   = 38.0   # tensão simulada em MOCK (~80%); ajustável via set_mock_voltage()

        if SMBUS_OK and GPIO_AVAILABLE:
            try:
                self._bus = smbus2.SMBus(I2C_BUS)
                log.info(f"[BatteryMonitor] I2C bus {I2C_BUS} aberto (addr=0x{I2C_ADDR_ADS1115:02X}).")
            except Exception as e:
                log.error(f"[BatteryMonitor] Falha ao abrir I2C: {e}")

    def start(self):
        self._running = True
        self._thread  = threading.Thread(target=self._read_loop,
                                          daemon=True, name="BatteryMonitor")
        self._thread.start()
        log.info("[BatteryMonitor] Monitoramento iniciado.")

    def stop(self):
        self._running = False

    def set_mock_voltage(self, vbat: float):
        """Injeta uma tensão simulada (V) para uso em MOCK / validação."""
        self.mock_vbat = vbat

    def read_once(self) -> dict:
        """
        Faz uma leitura síncrona, atualiza voltage_v/percent e devolve get_status().
        Usado pela thread de monitoramento e pelo harness de validação (sem esperar
        o intervalo de 5s).
        """
        try:
            raw_v = self._read_vout()
            self.voltage_v = self._vout_to_vbat(raw_v)
            self.percent   = self._voltage_to_percent(self.voltage_v)
        except Exception as e:
            log.warning(f"[BatteryMonitor] Erro de leitura: {e}")
        return self.get_status()

    # ─────────────────────────────────────────
    # LOOP DE LEITURA
    # ─────────────────────────────────────────
    def _read_loop(self):
        while self._running:
            self.read_once()
            time.sleep(BATTERY_READ_INTERVAL_S)

    def _read_vout(self) -> float:
        """Lê a tensão no ponto de medição do divisor (saída do ADS1115)."""
        if MOCK_MODE or not self._bus:
            # Simula a tensão definida em mock_vbat (default 38V ~80%)
            return self._vbat_to_vout(self.mock_vbat)

        config = (self.CONFIG_OS_SINGLE |
                  self.CONFIG_MUX_AIN0_GND |
                  self.CONFIG_PGA_4096 |
                  self.CONFIG_MODE_SINGLE |
                  self.CONFIG_DR_128SPS |
                  self.CONFIG_CQUE_NONE)

        config_bytes = [(config >> 8) & 0xFF, config & 0xFF]
        self._bus.write_i2c_block_data(I2C_ADDR_ADS1115,
                                        self.ADS1115_POINTER_CONFIG,
                                        config_bytes)
        time.sleep(0.01)  # aguarda conversão (~8ms a 128 SPS)

        data = self._bus.read_i2c_block_data(I2C_ADDR_ADS1115,
                                               self.ADS1115_POINTER_CONVERSION, 2)
        raw = (data[0] << 8) | data[1]
        if raw > 32767:
            raw -= 65536

        vout = (raw / self.ADS1115_RESOLUTION) * self.ADS1115_FULL_SCALE_MV / 1000.0
        return vout

    # ─────────────────────────────────────────
    # CONVERSÕES
    # ─────────────────────────────────────────
    def _vbat_to_vout(self, vbat: float) -> float:
        """Vbat → Vout (tensão no ponto do divisor)."""
        ratio = BATTERY_R2_OHM / (BATTERY_R1_OHM + BATTERY_R2_OHM)
        return vbat * ratio

    def _vout_to_vbat(self, vout: float) -> float:
        """Vout → Vbat (tensão real da bateria)."""
        ratio = BATTERY_R2_OHM / (BATTERY_R1_OHM + BATTERY_R2_OHM)
        return vout / ratio if ratio > 0 else 0.0

    def _voltage_to_percent(self, vbat: float) -> float:
        """Converte tensão real em porcentagem de carga (0–100%)."""
        pct = ((vbat - BATTERY_MIN_V) / (BATTERY_MAX_V - BATTERY_MIN_V)) * 100.0
        return max(0.0, min(100.0, pct))

    def get_status(self) -> dict:
        return {
            "voltage_v": round(self.voltage_v, 2),
            "percent":   round(self.percent, 1),
        }
