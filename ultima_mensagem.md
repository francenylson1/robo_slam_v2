# Última mensagem

> Sobrescrito a cada mensagem. Atualizado em 22/09/2026.

---

# A MEDIÇÃO CONTRARIOU A PREMISSA DO TRIM

```
Desvio FINAL:  -0,6°
Excursão:      -8,4° a +4,1°   (amplitude 12,5°)
Cruzou o rumo 6x
Desvio médio quadrático: 2,7°     ← o melhor até agora
Correção média EM REGIME: -3,04%  ← NEGATIVA
```

## O número bom

O RMS caiu para **2,7°** — melhor ainda que os 3,9° da rodada anterior, com a
mesma configuração. E o desvio final foi de apenas −0,6°.

## O número que muda tudo

A correção em regime veio **negativa**. Isso significa que o robô precisou de
**mais roda esquerda** para andar reto — ou seja, agora o **motor direito está
mais forte**.

Em todas as medidas anteriores era o contrário:

| Medida | O que indicava |
|---|---|
| Teste A3 (só esquerdo) | girou bem — esquerdo forte |
| Teste A4 (só direito) | girou pouco — direito fraco |
| Desvio sem correção | +40,5°, para a **direita** (= esquerdo mais forte) |
| Correções anteriores | **+5,28%**, **+6,00%** (positivas) |
| **Esta medição** | **−3,04%** (negativa) |

**A assimetria inverteu de sinal entre uma rodada e outra.**

## Por que isso importa mais que o resultado

Se a assimetria não é constante, **um trim fixo é perigoso**: quando o
desequilíbrio virasse, o trim passaria a empurrar **a favor** do erro em vez de
contra — e pioraria exatamente o que deveria melhorar.

Isso também explica por que o RMS varia tanto entre rodadas idênticas (3,9° e
depois 2,7°): não é ruído de medição, é o robô mudando de comportamento.

Causas possíveis, todas plausíveis:

1. **Bateria caindo** ao longo da tarde — os dois motores não perdem torque na
   mesma proporção;
2. **Aquecimento dos motores** depois de tantas rodadas;
3. **Piso** com variação entre um trecho e outro da pista;
4. A assimetria simplesmente **não é estável**, e nunca foi.

---

# O QUE EU PROPONHO

**Repetir a medição, sem mudar nada.** Mesma configuração, mesmo percurso.

- Se a correção em regime vier **negativa de novo**, a assimetria realmente
  inverteu (e aí vale investigar a bateria).
- Se vier **positiva**, o desequilíbrio é **variável** — e a conclusão é que o
  trim fixo **não serve para este robô**. A malha adaptativa, com o integral,
  passa a ser não um complemento, mas a única solução correta.

Nos dois casos eu aprendo algo que muda o projeto. E em nenhum deles fixo um
número antes de saber.

---

# O QUE EU PRECISO DE VOCÊ

1. **Robô na linha de partida.**
2. **"Pode"** para a repetição.
3. Se tiver anotado: **o desvio lateral desta última rodada** — mesmo aproximado.
   Com o RMS de 2,7° eu esperaria algo em torno de 15 cm em 3 metros, e quero
   confirmar.

Uma pergunta que só você pode responder: **há quanto tempo a bateria não é
carregada?** Se estiver caindo, isso explica a inversão e muda o que devemos
concluir — e reforça a urgência do ADS1115, que é justamente quem mediria isso.
