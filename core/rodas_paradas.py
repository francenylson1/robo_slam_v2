"""
core/rodas_paradas.py
"Rodas paradas" = nenhum pulso dos encoders há pelo menos janela_s.

Lê os CONTADORES (left/right_ticks_odo), que a thread dos Hall sempre
incrementa — inclusive com alguém empurrando o robô. O current_*_tps do
motor_driver só é atualizado com o PID de velocidade ligado e ficava em zero
(achado em 29/09, na P3).

AMOSTRADO SEMPRE (02/10/2026): antes, o teste só olhava os contadores quando
alguém perguntava. Depois de o robô andar, a 1ª pergunta via contadores
diferentes da pergunta anterior e marcava "mudou agora" — o 1º clique
("Começar a mapear", "Medir a fita", "Concluir", "Usar este ambiente") era
sempre recusado com o robô parado, e o 2º passava. Agora o main chama
amostrar() a 10 Hz; a pergunta continua olhando os contadores na hora, então
um pulso entre amostras nunca passa por "parado".

Só lê contadores: não comanda motor nem toca em GPIO.
"""

import threading
import time


class RodasParadas:

    def __init__(self, contadores_fn, janela_s: float = 0.5, clock=time.monotonic):
        self._contadores = contadores_fn
        self.janela_s = janela_s
        self._clock = clock
        self._lock = threading.Lock()
        self._ult = None
        self._mudou_em = clock()

    def amostrar(self):
        agora = self._clock()
        cont = self._contadores()
        with self._lock:
            if cont != self._ult:
                self._ult, self._mudou_em = cont, agora

    def __call__(self) -> bool:
        self.amostrar()
        with self._lock:
            return self._clock() - self._mudou_em >= self.janela_s
