# Última mensagem

> Sobrescrito a cada mensagem. Atualizado em 22/09/2026.

---

# O QUE OS DOIS PERCURSOS ENSINARAM

| | Andou | Desvio final | Serpenteio |
|---|---|---|---|
| `ki = 0,25` | **4,34 m** | 3,1 cm à direita | começa em 1,6 m |
| `ki = 0,12` | 3,50 m | 3,2 cm à esquerda | **desde o início** |

Mesmo desvio final, mas o `0,25` anda mais longe e serpenteia menos. **Reduzir o
ganho foi o caminho errado** — e agora eu sei exatamente por quê (o anti-windup
acoplado ao ganho, já corrigido).

## Por que ele andou menos com o ki menor

Isso eu não tinha previsto. Com `ki=0,12` a correção saturou em 6%. Base de 12%
mais 6% daria um pico de 18% — acima do teto de 15% da Regra Nº 0.

Aí entra o rebaixamento que implementei hoje: ele **baixa os dois lados em 3%**,
deixando 9% e 15% em vez de 12% e 12%. O robô mantém toda a autoridade de curva
e **perde velocidade**.

Funcionou como projetado. Eu só não tinha percebido que isso apareceria como
**distância menor** no percurso. Vale registrar: **quando a correção satura, o
robô fica mais lento.** É uma troca consciente — velocidade por controle — e é a
escolha certa, mas é bom saber que existe.

---

# O PRÓXIMO AJUSTE, E POR QUE É ESTE

Agora que o anti-windup não depende mais do ganho, existe um botão que mexe
**diretamente** no sobrepasso, sem tocar na resposta a erros novos:

**`HEADING_INTEGRAL_MAX` — quanta memória o integral guarda.** Hoje são 24
graus·segundo.

- O `kp` responde ao erro **agora**. Não mexer.
- O `ki` diz a **velocidade** com que o integral aprende. Não mexer (0,25 é o
  melhor medido).
- O **limite do integral** diz o **tamanho do sobrepasso** quando o erro inverte.
  É este que causa o serpenteio.

Reduzir o limite de 24 para 12 graus·segundo deve cortar o sobrepasso pela
metade, mantendo intactas a resposta rápida e a velocidade de aprendizado. Uma
variável, um efeito.

---

# O QUE EU PROPONHO

**Rodada 1 — linha de base com a instrumentação nova.** `ki=0,25`, limite 24,
exatamente a configuração dos 4,34 m. Serve para ter os números de oscilação
(excursão, cruzamentos, desvio médio) da melhor configuração conhecida.

**Rodada 2 — limite do integral em 12.** Mesmo percurso, e comparamos.

São dois percursos de 20 s. Se preferir, dá para pular a rodada 1 e ir direto ao
limite 12, comparando com os 4,34 m que já medimos — economiza um percurso, mas
a comparação fica menos limpa, porque a medição antiga não tinha as métricas de
oscilação.

---

# O QUE EU PRECISO DE VOCÊ

1. **Robô de volta à linha de partida.**
2. Me diga **"pode"**, e se prefere fazer as **duas rodadas** ou **pular direto
   para o limite 12**.

E, se der, um dado da pista que ainda não tenho: **quantas vezes o robô cruzou a
linha central** em cada um dos percursos anteriores. É o número que mede
oscilação de forma direta — e a partir de agora o sensor também vai medi-lo, mas
a sua contagem no chão é a referência para eu confiar na minha.
