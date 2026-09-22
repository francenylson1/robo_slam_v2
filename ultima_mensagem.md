# Última mensagem

> Sobrescrito a cada mensagem. Atualizado em 22/09/2026.

---

# 1ª RODADA FEITA — correção DESLIGADA

```
Percurso: 6,0 s — parou por tempo (o LIDAR não precisou intervir)
DESVIO DE RUMO: +40,5°
```

## O que esse número significa

Positivo = **para a direita** (convenção que confirmamos no seu robô hoje).

O robô girou **40,5 graus para a direita** enquanto tentava andar reto por ~1,4
metro. Isso é muito — em 10 metros ele estaria andando quase de lado.

E **bate exatamente com o que já tínhamos medido**: nos testes A3 e A4, o lado
esquerdo rendeu visivelmente mais que o direito com a mesma potência. Motor
esquerdo mais forte faz o robô curvar para a direita. A previsão e a medida
concordam.

Ou seja: **o problema que a Fase 3 existe para resolver acabou de aparecer com
número**, não como impressão.

---

# O QUE EU PRECISO DE VOCÊ AGORA

## 1. Meça com a trena

Quanto o centro do robô se afastou lateralmente da linha de direção que você
marcou? **Em centímetros, e para que lado.**

Minha expectativa, pelos 40,5° de rumo: algo entre **30 e 50 cm para a
direita**. Se a sua medida bater nessa ordem de grandeza, as duas vias de
medição concordam e o dado é sólido.

## 2. Recoloque o robô na posição inicial

- De volta à **linha de partida**, alinhado na mesma direção de antes.
- Mesmo ponto, mesma orientação — senão a comparação entre as duas rodadas
  perde o sentido.

## 3. Me diga "pode" de novo

Aí eu disparo a **2ª rodada, com a correção LIGADA**, exatamente nas mesmas
condições: 8% de potência, 6 segundos.

---

# O que vai provar o gate

A comparação dos dois desvios:

| | Desvio de rumo | Desvio lateral (sua trena) |
|---|---|---|
| **Sem correção** | **+40,5°** | você vai medir |
| **Com correção** | ? | ? |

Se o segundo for muito menor que o primeiro, a malha de rumo está provada e o
gate da Fase 3 fecha. Se não for, eu ajusto o ganho e repetimos — é exatamente
para isso que o `kp` existe.

Mantenha a mão na chave geral.
