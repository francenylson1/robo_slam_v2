"""
sensors/scan_recorder.py
Grava varreduras do RPLIDAR C1 em disco, para a decisão B-ou-C da Fase 4.

A PERGUNTA QUE ELE RESPONDE (docs/FASE4_ARQUITETURA_FROTA.md):
o que o C1, a 22 cm do chão, vê no salão é estável o bastante entre eventos
para os robôs se localizarem com ele (opção B)? Ou dominam cadeiras e mesas que
mudam de lugar, e o caminho é marcador no teto (opção C)? Decidido com o
professor em 23/09/2026: observar primeiro, decidir depois, com dados.

POR QUE ELE VIVE DENTRO DO BUMPER:
a porta /dev/ttyUSB0 só tem um leitor, e esse leitor é o SafetyBumper. Um
gravador separado exigiria desligar o bumper. Aqui ele só COPIA as varreduras
que o bumper já leu.

A REGRA DESTE MÓDULO: ele nunca pode atrasar nem derrubar a segurança.
  - offer() roda na thread do bumper: não toca disco, não bloqueia, não lança.
    Fila cheia → a varredura é descartada e contada.
  - A escrita é de outra thread. Disco cheio ou erro de E/S → loga (com
    anti-inundação) e segue; o bumper nem fica sabendo.
  - O SafetyBumper ainda envolve a chamada em try/except (defesa dupla).

FORMATO: JSON Lines em texto puro, um arquivo por hora,
data/varreduras/AAAA-MM-DD/HH.jsonl. Texto puro, e não gzip, porque o serviço
é morto com SIGKILL nos testes de watchdog: uma linha cortada perde uma
varredura; um gzip cortado perde a hora inteira. Cada linha:
  {"t": epoch_s, "yaw": graus|null, "mov": bool, "p": [[ang_centigraus, mm], ...]}
"mov" diz se o operador estava comandando os motores — a comparação entre dias
usa só as varreduras com o robô parado.

VOLUME (medido na Pi em 23/09/2026): ~5 KB por varredura; a 1 Hz, ~18 MB por
hora, ~110 h dentro do teto de 2 GB. O teto
SCAN_RECORD_MAX_MB apaga as horas mais antigas primeiro.
"""

import json
import logging
import os
import queue
import threading
import time

log = logging.getLogger(__name__)


class ScanRecorder:

    def __init__(self, base_dir: str, period_s: float = 1.0,
                 max_total_mb: float = 2000.0,
                 yaw_fn=None, moving_fn=None, queue_size: int = 32):
        self.base_dir   = os.path.abspath(base_dir)
        self.period_s   = float(period_s)
        self.max_bytes  = int(max_total_mb * 1024 * 1024)
        self._yaw_fn    = yaw_fn
        self._moving_fn = moving_fn
        self._q         = queue.Queue(maxsize=queue_size)
        self._last_kept = None      # time.monotonic() da última varredura aceita
        self._running   = False
        self._thread    = None
        self._file      = None
        self._file_key  = None      # "AAAA-MM-DD/HH" do arquivo aberto
        self._io_errors = 0
        # Contadores para a telemetria e para o harness.
        self.kept       = 0
        self.dropped    = 0
        self.written    = 0

    # ─────────────────────────────────────────
    # LADO DO BUMPER — nunca bloqueia, nunca lança
    # ─────────────────────────────────────────
    def offer(self, scan) -> bool:
        """Chamado pela thread do bumper a cada varredura. True se aceita."""
        try:
            agora = time.monotonic()
            if self._last_kept is not None and agora - self._last_kept < self.period_s:
                return False
            pontos = [[int(round((a % 360) * 100)), int(d)]
                      for _, a, d in scan if d > 0]
            reg = {"t": round(time.time(), 3),
                   "yaw": self._safe(self._yaw_fn),
                   "mov": bool(self._safe(self._moving_fn)),
                   "p": pontos}
            self._q.put_nowait(reg)
            self._last_kept = agora
            self.kept += 1
            return True
        except queue.Full:
            self.dropped += 1
            return False
        except Exception:
            self.dropped += 1
            return False

    @staticmethod
    def _safe(fn):
        if fn is None:
            return None
        try:
            v = fn()
            return round(v, 2) if isinstance(v, float) else v
        except Exception:
            return None

    # ─────────────────────────────────────────
    # CICLO DE VIDA
    # ─────────────────────────────────────────
    def start(self):
        self._running = True
        self._thread = threading.Thread(target=self._write_loop, daemon=True,
                                        name="ScanRecorder")
        self._thread.start()
        log.info(f"[ScanRecorder] Gravando 1 varredura a cada {self.period_s:g} s "
                 f"em {self.base_dir} (teto {self.max_bytes // (1024*1024)} MB).")

    def stop(self):
        self._running = False
        if self._thread is not None and self._thread.is_alive():
            self._thread.join(timeout=2.0)
        self._close()

    def health(self) -> dict:
        return {"kept": self.kept, "dropped": self.dropped,
                "written": self.written, "io_errors": self._io_errors}

    # ─────────────────────────────────────────
    # LADO DO DISCO — thread própria
    # ─────────────────────────────────────────
    def _write_loop(self):
        while self._running or not self._q.empty():
            try:
                reg = self._q.get(timeout=0.5)
            except queue.Empty:
                continue
            self.write_record(reg)

    def write_record(self, reg: dict):
        """Escreve uma varredura. Público para o harness exercitar sem thread."""
        try:
            chave = time.strftime("%Y-%m-%d/%H", time.localtime(reg["t"]))
            if chave != self._file_key:
                self._close()
                self._enforce_cap()
                caminho = os.path.join(self.base_dir, chave + ".jsonl")
                os.makedirs(os.path.dirname(caminho), exist_ok=True)
                self._file = open(caminho, "a", encoding="utf-8")
                self._file_key = chave
            self._file.write(json.dumps(reg, separators=(",", ":")) + "\n")
            self._file.flush()
            self.written += 1
        except Exception as e:
            self._io_errors += 1
            # Anti-inundação: a 1ª falha e depois 1 a cada 60.
            if self._io_errors == 1 or self._io_errors % 60 == 0:
                log.error(f"[ScanRecorder] Falha ao gravar ({self._io_errors}x): {e} "
                          "— a segurança não é afetada.")
            self._close()

    def _close(self):
        if self._file is not None:
            try:
                self._file.close()
            except Exception:
                pass
        self._file = None
        self._file_key = None

    def _enforce_cap(self):
        """Apaga as horas mais antigas até o total caber no teto."""
        arquivos = []
        for raiz, _, nomes in os.walk(self.base_dir):
            for n in nomes:
                if n.endswith(".jsonl"):
                    p = os.path.join(raiz, n)
                    try:
                        arquivos.append((os.path.relpath(p, self.base_dir), p,
                                         os.path.getsize(p)))
                    except OSError:
                        pass
        arquivos.sort()     # AAAA-MM-DD/HH ordena cronologicamente
        total = sum(s for _, _, s in arquivos)
        for _, p, s in arquivos:
            if total <= self.max_bytes:
                break
            try:
                os.remove(p)
                total -= s
                log.info(f"[ScanRecorder] Teto atingido — apagada {p}.")
            except OSError:
                pass
