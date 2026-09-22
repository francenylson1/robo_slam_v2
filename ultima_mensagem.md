# Última mensagem

> Sobrescrito a cada mensagem. Atualizado em 22/09/2026.

---

# A MUDANÇA PIOROU — e o motivo é um erro meu

| | Desvio final | Correção máxima |
|---|---|---|
| `ki = 0,25` | **+4,8°** | −6,00% (saturado) |
| `ki = 0,12` | **−11,4°** | +6,00% (saturado) |

## O efeito colateral que eu não previ

No meu anti-windup, o limite do integral é `max_corr / ki`. Parecia sensato — o
integral não acumula além do que consegue virar correção.

Mas ao **reduzir o `ki` pela metade, eu dobrei esse limite**: de 24 para 50
graus·segundo. O integral passou a acumular o dobro de "memória", e leva o dobro
do tempo para descarregar quando o erro inverte de sinal.

Ou seja: **eu enfraqueci o ganho e, sem perceber, agravei o windup.** O efeito
líquido foi o oposto do pretendido. Erro de projeto meu, não do robô.

## E há um segundo problema, de medição

Medir só o rumo **no ponto final** não distingue duas situações completamente
diferentes:

- o robô desviou, corrigiu e **estabilizou** num rumo levemente torto;
- o robô está **no meio de uma oscilação**, e o número que eu li é só onde ele
  calhou de estar quando o tempo acabou.

Os −11,4° podem ser qualquer um dos dois. Não dá para ajustar um controlador com
essa medida.

---

# O QUE EU VOU FAZER

**1. Instrumentar direito, antes de mexer em mais ganhos.** O teste vai passar a
reportar:

- o **desvio máximo** para cada lado durante o percurso (não só o final);
- quantas vezes o robô **cruzou a linha** — que é a contagem das oscilações;
- o desvio **médio quadrático**, que mede o quanto ele ficou fora da linha no
  conjunto do percurso.

Com isso, "estabilizou torto" e "está oscilando" viram números diferentes.

**2. Desacoplar o anti-windup do `ki`.** O limite do integral passa a ser um
valor fixo em graus·segundo, independente do ganho. Assim mexer no `ki` muda só
a força da correção, e não a memória do integral.

**3. Voltar o `ki` para 0,25**, que é o melhor resultado medido até agora
(+4,8°, 3,1 cm em 4,34 m), e repetir com a instrumentação nova para ter uma
linha de base confiável.

---

# O QUE EU PRECISO DE VOCÊ

Você tem a pista demarcada, e isso vale mais que o meu sensor agora. Desta
rodada que acabou de acontecer:

1. **Em que marca o serpenteio começou?** (na rodada com `ki=0,25` foi em 1,6 m)
2. **Qual a maior saída para cada lado?** Quantos centímetros para a direita e
   quantos para a esquerda.
3. **Quantas vezes ele cruzou a linha central?**
4. **Onde parou e com que desvio final?**

Mesmo aproximado, esse perfil me diz mais que os números que o sensor me deu. Se
você tiver só um desses, priorize o **3** — o número de cruzamentos é o que
separa "está oscilando" de "está torto e estável".
