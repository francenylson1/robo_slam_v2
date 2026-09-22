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

Do v1 veio o desenho; o que NÃO veio foi o sinal:

1. **A referência é travada ao entrar na reta, não é um rumo absoluto.** Copiado
   do v1 — sem isso o robô tentaria voltar ao rumo anterior depois de cada curva.
2. **O sinal NÃO foi copiado.** O v1 usa `INVERT_CORRECTION = True` porque
   calcula o yaw do quaternion (convenção matemática: esquerda aumenta). Nós
   lemos UART-RVC, onde a DIREITA aumenta — confirmado no robô em 22/09 com um
   giro guiado de 90° que deu +92,8°. Copiar o True teria criado realimentação
   positiva: o robô faria uma espiral em vez de endireitar.
3. **O v1 é P puro; aqui é P + I.** Lá o PID de velocidade por roda matava a
   assimetria dos motores na origem, então sobrava pouco para o rumo corrigir.
   Sem essa camada, a assimetria vira uma perturbação CONSTANTE, e contra ela o
   proporcional puro sempre deixa resíduo. Medido em 22/09: com P puro a
   correção saturou e o robô ainda desviou 23° em 6 s. O integral aprende esse
   desvio e o cancela.

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
import time

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

    def __init__(self, *, kp_pct: float, ki_pct: float, max_corr_pct: float,
                 invert: bool, tol_pct: float, teto_pct: float,
                 limite_integral: float, enabled: bool):
        self.kp_pct       = kp_pct
        self.ki_pct       = ki_pct
        self.max_corr_pct = max_corr_pct
        self.invert       = invert
        self.tol_pct      = tol_pct
        self.teto_pct     = teto_pct   # Regra Nº 0: potência máxima permitida
        self.enabled      = enabled
        self._yaw_ref     = None       # None = não estamos numa reta
        self._integral    = 0.0        # graus·s acumulados
        self._t_ant       = None
        self.limite_integral = limite_integral

    # ─────────────────────────────────────────
    @property
    def yaw_ref(self):
        return self._yaw_ref

    def soltar(self):
        """Esquece a referência E o integral. Chamado ao girar, parar ou perder
        o sensor. O integral acumulado numa reta não vale para a próxima: o
        robô pode ter mudado de piso, de carga ou de direção."""
        self._yaw_ref  = None
        self._integral = 0.0
        self._t_ant    = None

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
                 yaw_deg: float | None, yaw_ok: bool, dt: float | None = None):
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

        # ── P + I ────────────────────────────────────────────────────────
        # O termo proporcional sozinho NÃO resolve este robô. Medido em
        # 22/09/2026: um motor é sistematicamente mais forte que o outro, e
        # contra uma perturbação CONSTANTE o controle proporcional puro sempre
        # deixa erro residual — ele só age enquanto o erro existe. Com P puro a
        # correção saturou em 2,4% e o robô ainda desviou 23° em 6 s.
        #
        # O v1 não precisava de integral porque tinha o PID de velocidade por
        # roda embaixo, que matava a assimetria na origem. Aqui essa camada não
        # existe (exige os dois encoders, e o direito está com defeito), então o
        # integral é quem aprende o desvio constante e o cancela.
        agora = time.monotonic() if dt is None else None
        if dt is None:
            dt = 0.0 if self._t_ant is None else max(0.0, agora - self._t_ant)
            self._t_ant = agora

        self._integral += err * dt
        # Anti-windup com limite FIXO em graus·segundo, independente do ganho.
        #
        # A primeira versão limitava em `max_corr / ki`, e isso era uma
        # armadilha: reduzir o ki pela metade DOBRAVA o limite do integral (de
        # 24 para 50 graus·s), então ele acumulava o dobro de memória e levava o
        # dobro do tempo para descarregar quando o erro invertia. Baixar o ganho
        # AGRAVAVA o windup — exatamente o oposto do pretendido. Medido em
        # 22/09/2026: com ki=0,25 o desvio final foi +4,8°; com ki=0,12, −11,4°.
        #
        # Com limite fixo, mexer no ki muda só a FORÇA da correção, e não a
        # memória do integral. Uma variável de cada vez.
        self._integral = max(-self.limite_integral,
                             min(self.limite_integral, self._integral))

        corr = self.kp_pct * err + self.ki_pct * self._integral
        corr = max(-self.max_corr_pct, min(self.max_corr_pct, corr))

        base = (esq + dir_) / 2.0
        return self._respeitar_teto(base - corr, base + corr, base)

    def _respeitar_teto(self, esq: float, dir_: float, base: float):
        """Mantém os dois lados dentro do teto da Regra Nº 0 SEM matar a
        diferença entre eles.

        A correção soma ao comando base: com 15% de base e 6% de correção daria
        21%, e ≥20% não é cortado — é EMERGENCY STOP. A malha não pode provocar
        emergência em operação normal.

        Em vez de cortar o lado que estourou (o que mataria a diferença, que é
        justamente o que faz o robô virar), rebaixa os DOIS juntos. Perde-se um
        pouco de velocidade e mantém-se toda a autoridade de correção.
        """
        pico = max(abs(esq), abs(dir_))
        if pico <= self.teto_pct:
            return esq, dir_
        excesso = pico - self.teto_pct
        sinal = 1.0 if base >= 0 else -1.0
        return esq - sinal * excesso, dir_ - sinal * excesso

    def health(self) -> dict:
        return {
            "enabled":  self.enabled,
            "em_reta":  self._yaw_ref is not None,
            "yaw_ref":  round(self._yaw_ref, 2) if self._yaw_ref is not None else None,
            "integral": round(self._integral, 2),
        }
