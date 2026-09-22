"""
core/heading_assist.py
Malha fechada de rumo — o robô anda reto (Fase 3).

O PROBLEMA: motores de hoverboard com drivers independentes nunca são idênticos.
Medido neste robô em 22/09/2026 (Etapa A): com a MESMA potência de 8%, o lado
esquerdo rende visivelmente mais que o direito. Um comando "reto" descreve uma
curva. Dá para disfarçar calibrando PWM na tentativa e erro, mas quem sustenta a
reta com bateria caindo, carga mudando e piso variando é a malha fechada.

O ALGORITMO é o do próprio v1 (`~/robo_slam/joystick_controller_2026.py`), que
já roda neste robô:

    ao ENTRAR na reta:  trava a referência de rumo (yaw_ref)
    a cada ciclo:       err  = normaliza(yaw_atual - yaw_ref)
                        corr = satura(kp * err)
                        esquerda = base - corr ; direita = base + corr
    ao GIRAR ou PARAR:  solta a referência

Duas coisas desse desenho não se descobre sozinho, e por isso foram copiadas:

1. **A referência é travada ao entrar na reta, não é um rumo absoluto.** Sem
   isso o robô tentaria voltar ao rumo anterior depois de cada curva.
2. **O sinal é invertido neste robô** (`BNO_STRAIGHT_INVERT_CORRECTION = True`
   no v1). Casa com a medida de 21/09: girar para a DIREITA aumenta o yaw.

A DIFERENÇA para o v1: aqui a correção é aplicada em **potência (%)**, não em
TPS. O v1 corrige o setpoint de velocidade e deixa o PID de cada roda executar;
isso exige os DOIS encoders, e o encoder direito deste robô está com defeito
físico (Etapa B, 22/09/2026). Consequência prática: sem a malha interna de
velocidade, perturbações viram desvio e são corrigidas DEPOIS, em vez de
absorvidas ANTES — o robô oscila um pouco mais em torno da linha. Para o gate de
2 m a ≤15% a diferença é pequena. Detalhes e o porquê: docs/ETAPA_B_ENCODERS.md.

FAIL-SOFT: sem BNO085 saudável, a correção simplesmente não acontece e o comando
do operador passa intacto. O rumo nunca pode BLOQUEAR o robô — quem faz isso é o
bumper, que é fail-closed.
"""

import logging

log = logging.getLogger(__name__)


def normaliza_graus(a: float) -> float:
    """Traz um ângulo para (-180, +180]. Sem isso, cruzar 0°/360° produziria um
    erro de ~360° e uma correção violenta na direção errada."""
    while a > 180.0:
        a -= 360.0
    while a <= -180.0:
        a += 360.0
    return a


class HeadingAssist:
    """Mantém a referência de rumo e devolve o comando corrigido."""

    def __init__(self, *, kp_pct: float, max_corr_pct: float,
                 invert: bool, tol_pct: float, enabled: bool):
        self.kp_pct       = kp_pct
        self.max_corr_pct = max_corr_pct
        self.invert       = invert
        self.tol_pct      = tol_pct
        self.enabled      = enabled
        self._yaw_ref     = None       # None = não estamos numa reta

    # ─────────────────────────────────────────
    @property
    def yaw_ref(self):
        return self._yaw_ref

    def soltar(self):
        """Esquece a referência. Chamado ao girar, parar ou perder o sensor."""
        self._yaw_ref = None

    def e_reta(self, esq: float, dir_: float) -> bool:
        """Comando de linha reta: os dois lados no mesmo sentido, nenhum parado,
        e a diferença entre eles dentro da tolerância. Giro no lugar (sentidos
        opostos) e curva (lados muito diferentes) NÃO são reta."""
        if esq == 0.0 or dir_ == 0.0:
            return False
        if (esq > 0) != (dir_ > 0):
            return False
        return abs(esq - dir_) <= self.tol_pct

    def corrigir(self, esq: float, dir_: float,
                 yaw_deg: float | None, yaw_ok: bool):
        """
        Devolve (esquerda, direita) corrigidos, ou **None** quando não há
        correção a fazer — e aí o comando do operador vale como veio.

        None acontece quando: a malha está desligada, o BNO085 não está
        saudável, ou o comando não é de linha reta.
        """
        if not self.enabled:
            return None
        if not yaw_ok or yaw_deg is None:
            self.soltar()          # fail-soft: sem sensor, sem correção
            return None
        if not self.e_reta(esq, dir_):
            self.soltar()          # girou ou parou → a próxima reta trava de novo
            return None

        if self._yaw_ref is None:
            self._yaw_ref = yaw_deg
            log.info(f"[HeadingAssist] Reta iniciada — referência {yaw_deg:.1f}°")

        err = normaliza_graus(yaw_deg - self._yaw_ref)
        if self.invert:
            err = -err

        corr = max(-self.max_corr_pct, min(self.max_corr_pct, self.kp_pct * err))
        base = (esq + dir_) / 2.0
        return base - corr, base + corr

    def health(self) -> dict:
        return {
            "enabled":  self.enabled,
            "em_reta":  self._yaw_ref is not None,
            "yaw_ref":  round(self._yaw_ref, 2) if self._yaw_ref is not None else None,
        }
