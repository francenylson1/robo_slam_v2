"""
sensors/c1_topo.py
Lê o C1 DE CIMA (1,43 m) e guarda a última volta para o gravador.

Decidido com o professor em 21/10/2026 (E1–E5, página do modo sombra):
  E1  linha de execução própria, SEPARADA do bumper. Não é segurança: se o C1
      de cima cair, só aparece aviso no log (com anti-inundação) e o leitor
      tenta de novo; o bumper e o loop de 50 Hz não ficam sabendo.
  E2  as voltas vão na MESMA linha do gravador (campo "c143"), junto da volta
      do C1 de baixo e da pose do Aurora.
  E3  1 volta por segundo — quem dita o ritmo é o gravador.
  E4  porta pelo número de série (FROTA_LIDAR_TOPO_PORT); vazio = desligado;
      RECUSA abrir a porta do bumper.
  E5  descarta a sombra do tubo e leituras < 15 cm; grava ângulo e distância
      crus (a posição do sensor no robô fica no código do mapa).

Nada aqui move o robô nem escreve em GPIO.
"""

import logging
import os
import threading
import time

from config.settings import (
    LIDAR_BAUDRATE, LIDAR_BUF_MAX_BYTES, LIDAR_PORT, LIDAR_RECONNECT_BACKOFF_S, LIDAR_TOPO_PORT,
    C1_TOPO_SOMBRA_DEG, C1_TOPO_MIN_MM, C1_TOPO_MAX_IDADE_S,
)

log = logging.getLogger(__name__)


def na_sombra(ang_deg: float, sombra=C1_TOPO_SOMBRA_DEG) -> bool:
    """True se o ângulo cai na sombra do tubo (a faixa pode atravessar o 0°)."""
    a, b = sombra
    ang = ang_deg % 360.0
    return (a <= ang <= b) if a <= b else (ang >= a or ang <= b)


def filtrar(scan, sombra=C1_TOPO_SOMBRA_DEG, min_mm=C1_TOPO_MIN_MM):
    """[(q, ang, mm)] do rplidar → [[centigraus, mm]], sem tubo nem perto demais."""
    return [[int(round((a % 360) * 100)), int(d)]
            for _, a, d in scan
            if d >= min_mm and not na_sombra(a, sombra)]


def mesma_porta(p1: str, p2: str) -> bool:
    """As duas apontam para o mesmo dispositivo? (by-id é link para ttyUSBn)"""
    if not p1 or not p2:
        return False
    return os.path.realpath(p1) == os.path.realpath(p2)


class C1Topo:

    def __init__(self, porta: str = LIDAR_TOPO_PORT, porta_bumper: str = LIDAR_PORT,
                 max_idade_s: float = C1_TOPO_MAX_IDADE_S):
        self.porta        = porta
        self.porta_bumper = porta_bumper
        self.max_idade_s  = max_idade_s
        self._ultima      = None     # (time.monotonic(), n, pontos)
        self._entregue_n  = None     # n da última volta entregue ao gravador
        self._n           = 0
        self._running     = False
        self._thread      = None
        self._lidar       = None
        self.falhas       = 0

    @property
    def ligado(self) -> bool:
        return bool(self.porta)

    # ─────────────────────────────────────────
    # LADO DO GRAVADOR
    # ─────────────────────────────────────────
    def volta_nova(self, agora: float | None = None):
        """{"idade_s", "p"} da última volta, se é nova e fresca; senão None."""
        u = self._ultima
        if u is None:
            return None
        t, n, pontos = u
        idade = (time.monotonic() if agora is None else agora) - t
        if n == self._entregue_n or idade > self.max_idade_s:
            return None
        self._entregue_n = n
        return {"idade_s": round(idade, 3), "p": pontos}

    def receber(self, scan, agora: float | None = None):
        """Guarda uma volta (a thread chama; o harness também)."""
        self._n += 1
        self._ultima = (time.monotonic() if agora is None else agora,
                        self._n, filtrar(scan))

    def health(self) -> dict:
        u = self._ultima
        return {"ligado": self.ligado, "voltas": self._n, "falhas": self.falhas,
                "idade_s": None if u is None else round(time.monotonic() - u[0], 2)}

    # ─────────────────────────────────────────
    # CICLO DE VIDA
    # ─────────────────────────────────────────
    def start(self):
        if not self.ligado:
            log.info("[C1Topo] FROTA_LIDAR_TOPO_PORT vazio — C1 de cima desligado.")
            return
        if mesma_porta(self.porta, self.porta_bumper):
            log.error(f"[C1Topo] {self.porta} é a porta do BUMPER — recuso abrir; "
                      "C1 de cima desligado. Confira /etc/frota.conf.")
            self.porta = ""
            return
        self._running = True
        self._thread = threading.Thread(target=self._loop, daemon=True, name="C1Topo")
        self._thread.start()

    def stop(self):
        self._running = False
        if self._thread is not None and self._thread.is_alive():
            self._thread.join(timeout=2.0)

    def _loop(self):
        from sensors.safety_bumper import _C1Lidar
        tentativa = 0
        while self._running:
            try:
                self._lidar = _C1Lidar(self.porta, baudrate=LIDAR_BAUDRATE)
                self._lidar.stop()          # resíduo de um processo anterior
                self._lidar.clean_input()
                log.info(f"[C1Topo] C1 de cima conectado em {self.porta}.")
                tentativa = 0
                for scan in self._lidar.varreduras(LIDAR_BUF_MAX_BYTES):
                    if not self._running:
                        break
                    self.receber(scan)
            except Exception as e:
                self.falhas += 1
                # Anti-inundação: a 1ª falha e depois 1 a cada 60.
                if self.falhas == 1 or self.falhas % 60 == 0:
                    log.warning(f"[C1Topo] Falha no C1 de cima ({self.falhas}x): {e} "
                                "— a segurança não é afetada.")
            finally:
                if self._lidar is not None:
                    try:
                        self._lidar.stop()
                        self._lidar.disconnect()
                    except Exception:
                        pass
                    self._lidar = None
            if not self._running:
                break
            espera = LIDAR_RECONNECT_BACKOFF_S[
                min(tentativa, len(LIDAR_RECONNECT_BACKOFF_S) - 1)]
            tentativa += 1
            time.sleep(espera)
