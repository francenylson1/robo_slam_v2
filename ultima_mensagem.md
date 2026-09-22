# Última mensagem

> Sobrescrito a cada mensagem. Atualizado em 22/09/2026.

---

# A PARTIDA SUAVE FALHOU — e o motivo vale mais que o experimento

```
Desvio FINAL:  +94,3°      (você mediu ~90° em ~2 m — as medidas batem)
Correção:      +6,00% SATURADA o percurso inteiro
Parada limpa pelo LIDAR
```

Pior resultado da sessão inteira. O robô descreveu um arco em vez de andar reto.

## A causa foi erro meu de dimensionamento

A rampa começava em **35% da potência alvo** — ou seja, **4,2%** partindo de 12%.

Mas nós medimos hoje que **8% é o mínimo para este robô sair do lugar**. E esse
número é do **conjunto**. Abaixo dele, é perfeitamente possível que **um motor
gire e o outro não** — e aí não existe "assimetria suave": existe um motor parado
e outro puxando, o que é um **pivô**.

Tentei suavizar a partida levando o robô para uma faixa de potência onde ele
**não funciona de forma previsível**.

Já corrigi: a rampa agora parte de **8%** e sobe até o alvo.

---

# O ACHADO DE HARDWARE, que fica

> **Abaixo de ~8% de potência, este robô não anda de forma previsível.**

Isso não é sobre a partida suave. É uma característica do hardware, e tem
consequência direta sobre a **Fase 4**:

Um robô garçom precisa **aproximar-se devagar** de uma mesa para entregar. Se
abaixo de 8% ele pivota em vez de andar, essa aproximação terá que ser feita com
**pulsos curtos a 8%**, e não com potência reduzida contínua.

É o tipo de restrição que só aparece testando, e que teria custado caro se
descoberta durante um evento.

---

# ONDE ESTAMOS, honestamente

A sessão de ajuste fino rendeu isto:

| Configuração | Por metro | RMS |
|---|---|---|
| kp 0,105 · limite 24 | 10,6 cm/m | 10,8° |
| kp 0,105 · limite 12 | 19,3 cm/m | 12,9° |
| **kp 0,45 · limite 12** | **6,8 / 7,1 cm/m** | 2,7° a 4,7° |
| Partida suave (rampa errada) | inutilizável | 40,2° |

**A melhor configuração é a que já está no código**: `kp=0,45`, `ki=0,25`,
limite 12, trim 0. Ela dá 7 cm por metro, com o desvio nascendo quase todo na
largada.

Duas tentativas de melhorar a largada falharam, e por motivos diferentes e
igualmente instrutivos:

- **trim fixo** — a assimetria troca de sinal entre rodadas (+6,00%, −3,04%,
  +3,90%), então nenhum valor fixo serve;
- **partida suave** — na versão errada, levou o robô abaixo do piso de potência.

---

# O QUE EU PROPONHO AGORA

**Uma última rodada**, com a rampa corrigida (8% → 12% em 2,5 s). Se melhorar a
largada, fica. Se não melhorar, eu desligo a rampa e encerramos com a
configuração que já está boa.

Ou **encerramos a sessão por aqui** — o gate da Fase 3 está cumprido desde os
4,34 m, e hoje o robô já andou muito.

Sua escolha. Se for rodar, robô na linha e caminho livre **em toda a altura**.
