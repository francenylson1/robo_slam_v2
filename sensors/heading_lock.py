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

from config.settings import (
    GPIO_AVAILABLE, MOCK_MODE, BNO_UART_PORT, BNO_UART_BAUD,
    BNO_RESET_ON_START, BNO_MUTE_RESET_S, BNO_RESET_BACKOFF_S,
    BNO_POWER_CYCLE_FROM,
)
from sensors.bno_reset import (
    pulsar_reset, reset_disponivel,
    ligar_energia, ciclar_energia, energia_disponivel,
)

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

    def __init__(self, reset_fn=None, power_on_fn=None, power_cycle_fn=None):
        self.yaw_deg        = 0.0
        self.locked_yaw     = None   # Yaw travado para linha reta
        self._running       = False
        self._thread        = None
        self._serial        = None
        self._last_frame_ts = None   # perf_counter do último quadro RVC válido
        self.mock_yaw       = 0.0    # Yaw simulado em MOCK (graus)
        self.mock_noise_deg = 0.0    # ruído ± aplicado ao mock_yaw (graus)
        # Reset automático (23/09/2026) — ver _vigiar_mudo e sensors/bno_reset.py.
        # reset_fn é injetável para o harness provar a lógica em MOCK.
        self._reset_fn        = reset_fn if reset_fn is not None else pulsar_reset
        self._reset_ok        = reset_fn is not None or reset_disponivel()
        # Interruptor de energia (24/09/2026): corte total a partir da
        # BNO_POWER_CYCLE_FROM-ésima tentativa seguida. Injetável como o reset.
        self._ligar_fn        = power_on_fn if power_on_fn is not None else ligar_energia
        self._ciclo_fn        = power_cycle_fn if power_cycle_fn is not None else ciclar_energia
        self._ciclo_ok        = power_cycle_fn is not None or energia_disponivel()
        self.ciclos_total     = 0
        self._start_ts        = None
        self._last_reset_ts   = None
        self._resets_seguidos = 0
        self.resets_total     = 0
        self._mudo_avisado    = False

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
        if self._serial is not None:
            self._partida()
        self._start_ts = time.perf_counter()
        self._running = True
        self._thread  = threading.Thread(target=self._read_loop,
                                          daemon=True, name="HeadingLock")
        self._thread.start()

    def _partida(self):
        """
        Liga a energia do BNO (o GPIO 7 nasce solto: sem o serviço, o sensor
        fica desligado) e dá o reset de partida — o sensor às vezes acorda mudo
        com o robô, e um reset limpo com a alimentação estável substitui o
        desliga-e-religa manual.
        """
        if self._ciclo_ok and self._ligar_fn():
            log.info("[HeadingLock] Energia do BNO085 ligada (interruptor).")
            time.sleep(0.1)
        if BNO_RESET_ON_START and self._reset_ok:
            if self._reset_fn():
                log.info("[HeadingLock] Reset de partida do BNO085 (pino RST).")

    def stop(self):
        self._running = False
        # Fechar a porta aqui, com a thread ainda dentro de self._serial.read(),
        # produz um ERRO espúrio em todo desligamento gracioso
        # ("'NoneType' object cannot be interpreted as an integer"). Esperar a
        # thread sair do laço primeiro mantém o log limpo. O join é curto: a
        # leitura tem timeout próprio.
        if self._thread is not None and self._thread.is_alive():
            self._thread.join(timeout=2.0)
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
                    if self._mudo_avisado:
                        self._registrar_volta()
            except Exception as e:
                log.error(f"[HeadingLock] Erro na UART: {e}")
                time.sleep(0.5)
            self._vigiar_mudo()

    # ─────────────────────────────────────────
    # BNO085 MUDO → RESET AUTOMÁTICO (23/09/2026)
    # ─────────────────────────────────────────
    def _vigiar_mudo(self, agora: float | None = None) -> bool:
        """
        Sem quadro válido há BNO_MUTE_RESET_S → pulsa o RST. Se continuar mudo,
        a partir da BNO_POWER_CYCLE_FROM-ésima tentativa seguida faz o corte
        total de energia (24/09/2026: em 23/09 o RST não bastou); se o corte
        falhar, cai de volta no RST. Espaça as tentativas (BNO_RESET_BACKOFF_S)
        para não agir em rajada sobre um sensor fisicamente ausente. Devolve
        True se agiu agora.

        O salto do yaw depois do reset (o sensor zera na direção atual) não
        chega à malha de rumo: com 1 s sem quadro `healthy` já é False e ela
        solta a referência; aqui também se esquece o yaw travado.
        """
        agora = time.perf_counter() if agora is None else agora
        ultimo = self._last_frame_ts if self._last_frame_ts is not None else self._start_ts
        if ultimo is None or agora - ultimo < BNO_MUTE_RESET_S:
            return False
        if not self._mudo_avisado:
            self._mudo_avisado = True
            log.warning(f"[HeadingLock] BNO085 MUDO há {agora - ultimo:.1f} s — "
                        "malha de rumo sem correção (fail-soft)."
                        + ("" if (self._reset_ok or self._ciclo_ok)
                           else " Sem pino RST: religue o robô."))
        if not (self._reset_ok or self._ciclo_ok):
            return False
        if self._resets_seguidos:
            espera = BNO_RESET_BACKOFF_S[min(self._resets_seguidos - 1,
                                             len(BNO_RESET_BACKOFF_S) - 1)]
            if agora - self._last_reset_ts < espera:
                return False
        tentativa = self._resets_seguidos + 1
        como = "RST"
        if self._ciclo_ok and tentativa >= BNO_POWER_CYCLE_FROM:
            pulsou = self._ciclo_fn()
            if pulsou:
                como = "corte de energia"
                self.ciclos_total += 1
            else:
                log.error("[HeadingLock] Corte de energia do BNO085 falhou — tentando o RST.")
                pulsou = self._reset_fn() if self._reset_ok else False
        else:
            pulsou = self._reset_fn() if self._reset_ok else False
        self._last_reset_ts    = agora
        self._resets_seguidos  = tentativa
        self.resets_total     += 1
        self.locked_yaw        = None
        log.warning(f"[HeadingLock] Recuperação automática do BNO085 nº {tentativa} ({como})"
                    f"{'' if pulsou else ' — FALHOU'}.")
        return pulsou

    def _registrar_volta(self):
        log.info(f"[HeadingLock] BNO085 voltou a transmitir"
                 f"{f' após {self._resets_seguidos} reset(s)' if self._resets_seguidos else ''}.")
        self._mudo_avisado    = False
        self._resets_seguidos = 0
