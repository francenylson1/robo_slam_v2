"""
sensors/battery_monitor.py
Leitura da tensão da bateria via ADS1115 (canal A0) e divisor resistivo.
Divisor: R1=100kΩ + R2=6.8kΩ → Vout_max=2.67V para Vbat=42V.
Atualiza a cada BATTERY_READ_INTERVAL_S segundos em thread dedicada.

NÍVEIS (24/09/2026): a Fase 4 só roda autônomo com a bateria medida. O monitor
classifica a tensão em "ok", "baixa", "critica" ou "desconhecida":
  - "baixa" só avisa; "critica" e "desconhecida" negam missão autônoma
    (missao_permitida = False). Sem leitura não há autonomia: fail-closed para
    a missão, fail-soft para o resto (o joystick não depende disto);
  - mudar entre níveis conhecidos exige BATTERY_CONFIRM_READS leituras seguidas
    (a tensão cede sob carga do motor e volta), e voltar a um nível melhor
    exige BATTERY_HYSTERESIS_V além do limite;
  - leitura fora de [BATTERY_VALID_MIN_V, BATTERY_VALID_MAX_V] é descartada
    (A0 solto lê ~0 V, que não é a bateria), e sem leitura boa por
    BATTERY_STALE_S o nível vira "desconhecida".
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
    BATTERY_READ_INTERVAL_S, BATTERY_CAL_FACTOR,
    BATTERY_LOW_V, BATTERY_CRITICAL_V, BATTERY_HYSTERESIS_V,
    BATTERY_CONFIRM_READS, BATTERY_STALE_S,
    BATTERY_VALID_MIN_V, BATTERY_VALID_MAX_V,
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

    # Anti-inundação do log: com o ADS1115 ausente do barramento, a leitura
    # falha em TODO ciclo. Loga a 1ª falha e depois uma a cada _ERR_REPEAT
    # (a 5s por leitura, ~1 linha a cada 5 minutos), mais a recuperação.
    _ERR_REPEAT = 60

    def __init__(self):
        self.voltage_v   = 0.0
        self.percent     = 0.0
        self._running    = False
        self._thread     = None
        self._bus        = None
        self.mock_vbat   = 38.0   # tensão simulada em MOCK (~80%); ajustável via set_mock_voltage()
        self._err_streak = 0      # falhas consecutivas de leitura (anti-inundação do log)
        self._lock         = threading.Lock()
        self._nivel        = "desconhecida"
        self._candidato    = None   # nível que está sendo confirmado
        self._confirmacoes = 0
        self._last_ok_ts   = None   # time.monotonic() da última leitura válida

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

    def read_once(self, agora: float | None = None) -> dict:
        """
        Faz uma leitura síncrona, atualiza voltage_v/percent e devolve get_status().
        Usado pela thread de monitoramento e pelo harness de validação (sem esperar
        o intervalo de 5s). `agora` (time.monotonic) é injetável para o harness.
        """
        agora = time.monotonic() if agora is None else agora
        try:
            raw_v = self._read_vout()
            vbat  = self._vout_to_vbat(raw_v)
            if not (BATTERY_VALID_MIN_V <= vbat <= BATTERY_VALID_MAX_V):
                raise ValueError(f"{vbat:.1f} V fora da faixa plausível "
                                 f"({BATTERY_VALID_MIN_V:g}–{BATTERY_VALID_MAX_V:g} V): "
                                 "A0 solto ou divisor errado?")
            self.voltage_v = vbat
            self.percent   = self._voltage_to_percent(vbat)
            self._registrar_leitura(vbat, agora)
            if self._err_streak:
                log.info(f"[BatteryMonitor] Leitura restabelecida após "
                         f"{self._err_streak} falha(s).")
                self._err_streak = 0
        except Exception as e:
            # Sem o ADS1115 no barramento, isto falharia a cada leitura e
            # inundaria o journald (17 mil linhas/dia a 5s). Loga a primeira
            # falha e depois só a cada _ERR_REPEAT, além da recuperação.
            self._err_streak += 1
            if self._err_streak == 1 or self._err_streak % self._ERR_REPEAT == 0:
                log.warning(f"[BatteryMonitor] Erro de leitura ({self._err_streak}x): {e}")
        return self.get_status(agora)

    # ─────────────────────────────────────────
    # NÍVEL DA BATERIA (24/09/2026)
    # ─────────────────────────────────────────
    def _classificar(self, vbat: float) -> str:
        """Nível da tensão, com histerese a favor do nível atual."""
        h = BATTERY_HYSTERESIS_V
        lim_crit  = BATTERY_CRITICAL_V + (h if self._nivel == "critica" else 0.0)
        lim_baixa = BATTERY_LOW_V + (h if self._nivel in ("baixa", "critica") else 0.0)
        if vbat < lim_crit:
            return "critica"
        if vbat < lim_baixa:
            return "baixa"
        return "ok"

    def _registrar_leitura(self, vbat: float, agora: float):
        with self._lock:
            self._last_ok_ts = agora
            cand = self._classificar(vbat)
            if self._nivel == "desconhecida":
                self._mudar_nivel(cand, vbat)
                return
            if cand == self._nivel:
                self._candidato, self._confirmacoes = None, 0
                return
            if cand != self._candidato:
                self._candidato, self._confirmacoes = cand, 0
            self._confirmacoes += 1
            if self._confirmacoes >= BATTERY_CONFIRM_READS:
                self._mudar_nivel(cand, vbat)

    def _mudar_nivel(self, novo: str, vbat: float | None):
        if novo != self._nivel:
            txt = f"{vbat:.1f} V" if vbat is not None else "sem leitura"
            aviso = log.info if novo == "ok" else log.warning
            aviso(f"[BatteryMonitor] Bateria: {self._nivel} → {novo} ({txt}).")
        self._nivel = novo
        self._candidato, self._confirmacoes = None, 0

    def nivel(self, agora: float | None = None) -> str:
        """ok / baixa / critica / desconhecida (sem leitura boa há BATTERY_STALE_S)."""
        agora = time.monotonic() if agora is None else agora
        with self._lock:
            if self._last_ok_ts is None or agora - self._last_ok_ts > BATTERY_STALE_S:
                if self._nivel != "desconhecida":
                    self._mudar_nivel("desconhecida", None)
            return self._nivel

    def missao_permitida(self, agora: float | None = None) -> bool:
        """Missão autônoma só com a bateria medida e acima do nível crítico."""
        return self.nivel(agora) in ("ok", "baixa")

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
        return vbat * ratio / BATTERY_CAL_FACTOR

    def _vout_to_vbat(self, vout: float) -> float:
        """Vout → Vbat (tensão real da bateria)."""
        ratio = BATTERY_R2_OHM / (BATTERY_R1_OHM + BATTERY_R2_OHM)
        return vout / ratio * BATTERY_CAL_FACTOR if ratio > 0 else 0.0

    def _voltage_to_percent(self, vbat: float) -> float:
        """Converte tensão real em porcentagem de carga (0–100%)."""
        pct = ((vbat - BATTERY_MIN_V) / (BATTERY_MAX_V - BATTERY_MIN_V)) * 100.0
        return max(0.0, min(100.0, pct))

    def get_status(self, agora: float | None = None) -> dict:
        nivel = self.nivel(agora)
        return {
            "voltage_v":        round(self.voltage_v, 2),
            "percent":          round(self.percent, 1),
            "nivel":            nivel,
            "missao_permitida": nivel in ("ok", "baixa"),
        }
