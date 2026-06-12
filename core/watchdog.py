"""
core/watchdog.py
Watchdog do robô (Fase 1.5 — Blindagem): se o loop 50Hz travar, alguém
de fora reinicia o sistema e os freios voltam ao estado seguro
(BREAK=HIGH é o estado inicial do motor_driver).

Três modos, escolhidos automaticamente em arm():
  systemd — rodando como serviço (NOTIFY_SOCKET presente): envia READY=1 ao
            armar e WATCHDOG=1 a cada alimentação. Com WatchdogSec=5 no
            .service, processo travado → systemd mata e reinicia o serviço.
            (Kernel travado é coberto pelo RuntimeWatchdogSec do systemd,
            que alimenta o /dev/watchdog de hardware — ver deploy/.)
  device  — execução manual na Pi (sem systemd): escreve direto em
            /dev/watchdog. Processo travado → o SoC reinicia a Pi.
            No desligamento gracioso escreve 'V' (magic close) para
            desarmar sem reboot.
  mock    — PC de dev ou --mock: nenhum acesso a dispositivo; registra as
            alimentações e expõe would_have_fired para o harness de validação.
"""

import os
import time
import logging

from config.settings import (
    MOCK_MODE, WATCHDOG_DEVICE, WATCHDOG_TIMEOUT_S, WATCHDOG_PET_INTERVAL_S,
)

log = logging.getLogger(__name__)


def _sd_notify(msg: bytes) -> bool:
    """Envia uma mensagem ao socket de notificação do systemd (sem dependências)."""
    addr = os.environ.get("NOTIFY_SOCKET")
    if not addr:
        return False
    try:
        import socket
        if addr.startswith("@"):          # socket abstrato do Linux
            addr = "\0" + addr[1:]
        with socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM) as s:
            s.connect(addr)
            s.send(msg)
        return True
    except Exception as e:
        log.warning(f"[Watchdog] sd_notify falhou: {e}")
        return False


class HardwareWatchdog:
    """
    Interface única de watchdog para o loop de controle.
    Uso: arm() no startup → pet() a cada ciclo (rate-limited internamente)
    → disarm() no shutdown gracioso.
    """

    def __init__(self,
                 timeout_s: float = WATCHDOG_TIMEOUT_S,
                 pet_interval_s: float = WATCHDOG_PET_INTERVAL_S):
        self.timeout_s      = timeout_s
        self.pet_interval_s = pet_interval_s
        self.mode           = None      # "systemd" | "device" | "mock"
        self.armed          = False
        self._last_pet      = None      # time.perf_counter() da última alimentação
        self._fd            = None      # arquivo de /dev/watchdog (modo device)

    # ─────────────────────────────────────────
    # CICLO DE VIDA
    # ─────────────────────────────────────────
    def arm(self):
        """Escolhe o modo e ativa o watchdog."""
        if MOCK_MODE:
            self.mode = "mock"
        elif os.environ.get("NOTIFY_SOCKET"):
            self.mode = "systemd"
            _sd_notify(b"READY=1")
        else:
            try:
                self._fd  = open(WATCHDOG_DEVICE, "wb", buffering=0)
                self.mode = "device"
            except Exception as e:
                # Sem permissão/dispositivo: degrada para mock e avisa alto —
                # em produção o robô deve rodar via systemd (ver deploy/).
                log.warning(f"[Watchdog] {WATCHDOG_DEVICE} indisponível ({e}) — "
                            "modo degradado SEM watchdog real. Em produção, "
                            "rode via systemd (deploy/frota-robo.service).")
                self.mode = "mock"

        self.armed     = True
        self._last_pet = time.perf_counter()
        self.pet(force=True)
        log.info(f"[Watchdog] Armado (modo {self.mode}, "
                 f"alimentação a cada {self.pet_interval_s:.1f}s).")

    def pet(self, force: bool = False):
        """
        Alimenta o watchdog. Chamado a cada ciclo do loop 50Hz; internamente
        limita a escrita real a uma vez por pet_interval_s.
        """
        if not self.armed:
            return
        now = time.perf_counter()
        if not force and (now - self._last_pet) < self.pet_interval_s:
            return
        self._last_pet = now
        if self.mode == "systemd":
            _sd_notify(b"WATCHDOG=1")
        elif self.mode == "device":
            try:
                self._fd.write(b".")
            except Exception as e:
                log.error(f"[Watchdog] Falha ao alimentar: {e}")

    def disarm(self):
        """Desarma no shutdown gracioso (evita reboot por parada intencional)."""
        if not self.armed:
            return
        self.armed = False
        if self.mode == "device" and self._fd:
            try:
                self._fd.write(b"V")   # magic close — desarma o HW sem reboot
                self._fd.close()
            except Exception:
                pass
            self._fd = None
        elif self.mode == "systemd":
            _sd_notify(b"STOPPING=1")
        log.info("[Watchdog] Desarmado (shutdown gracioso).")

    # ─────────────────────────────────────────
    # DIAGNÓSTICO / TELEMETRIA
    # ─────────────────────────────────────────
    @property
    def would_have_fired(self) -> bool:
        """
        MOCK/diagnóstico: True se, armado, a última alimentação for mais velha
        que timeout_s — na Pi isto significaria reinício do serviço/placa.
        """
        if not self.armed or self._last_pet is None:
            return False
        return (time.perf_counter() - self._last_pet) > self.timeout_s

    def health(self) -> dict:
        """Resumo para a telemetria (dashboard/Torre)."""
        age = (None if self._last_pet is None
               else round(time.perf_counter() - self._last_pet, 3))
        return {"mode": self.mode, "armed": self.armed, "last_pet_age_s": age}
