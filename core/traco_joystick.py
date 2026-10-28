"""
core/traco_joystick.py — o que rodas, BNO e Aurora dizem com o robô no
JOYSTICK (28/10/2026).

Na volta da P3-corredor1 (18:55) o BNO e o Aurora discordaram ~5° na rampinha
da porta, e depois dela as rodas viravam à esquerda enquanto o Aurora mostrava
o robô virando à direita. As rodas não patinam (conferido pelo Prof.): a
diferença entre os pulsos de cada roda é o giro VERDADEIRO. Aqui, a 10 Hz, com
o robô em JOYSTICK e localizado, cada linha guarda os três — parado também
(o desvio parado na rampa é parte da medida).
"""
import logging
import os
import time

log = logging.getLogger(__name__)

CABECALHO = ("hora,ticks_esq,ticks_dir,cmd_esq,cmd_dir,bno_graus,"
             "x_cm,y_cm,rumo_aurora\n")


class TracoJoystick:
    MAX_LINHAS = 200_000              # ~5,5 h a 10 Hz por arquivo

    def __init__(self, motors, heading, pose_source, state, pasta,
                 max_idade_s=0.5, relogio=time.time):
        self.motors, self.heading, self.pose = motors, heading, pose_source
        self.state, self.pasta = state, pasta
        self.max_idade_s = max_idade_s
        self._relogio = relogio
        self._f = None
        self._linhas = 0

    def _abrir(self):
        os.makedirs(self.pasta, exist_ok=True)
        nome = time.strftime("joystick_%Y%m%d_%H%M%S.csv", time.localtime(self._relogio()))
        self._f = open(os.path.join(self.pasta, nome), "w", encoding="utf-8", buffering=1)
        self._f.write(CABECALHO)
        self._linhas = 0
        log.info(f"[TracoJoystick] Gravando {nome}.")

    def amostrar(self):
        """Uma linha, se o robô está em JOYSTICK e o Aurora dá pose válida."""
        if self.state.get("mode") != "JOYSTICK":
            return
        p = self.pose.pose_valida(self.max_idade_s)
        if p is None:
            return
        try:
            if self._f is None or self._linhas >= self.MAX_LINHAS:
                if self._f is not None:
                    self._f.close()
                self._abrir()
            t = self._relogio()
            bno = self.heading.yaw_deg if self.heading.healthy else None
            cmd = self.state.get("cmd_motores") or (0.0, 0.0)
            self._f.write(
                f"{time.strftime('%H:%M:%S', time.localtime(t))}.{int(t * 1000) % 1000:03d},"
                f"{getattr(self.motors, 'left_ticks_odo', 0)},"
                f"{getattr(self.motors, 'right_ticks_odo', 0)},"
                f"{cmd[0]:.1f},{cmd[1]:.1f},"
                f"{'' if bno is None else round(bno, 2)},"
                f"{p.x_m * 100:.1f},{p.y_m * 100:.1f},{p.rumo_deg:.2f}\n")
            self._linhas += 1
        except Exception as e:                  # gravar não pode parar o robô
            log.error(f"[TracoJoystick] {e}")
            self._f = None
