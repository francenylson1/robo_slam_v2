# Protocolo dos testes manuais — o que o professor faz, passo a passo

> Fase 3 em diante. Escrito em 22/09/2026, depois de três medições perdidas por
> combinação ruim entre quem dispara o teste e quem move o robô.

---

## Por que este documento existe

Nestes testes **o sensor é o robô e o atuador é a pessoa**. Se o movimento não
for feito do jeito certo, a medida não é "ruim": ela é **enganosa**, e uma
conclusão errada tirada dela custa mais caro que não medir.

Já aconteceu três vezes hoje:

1. contagem de encoder zerada porque a janela fechou antes de alguém empurrar;
2. o mesmo, de novo, porque o professor parou de girar para escrever uma
   mensagem;
3. o sinal do yaw medido com o robô cruzando o ±180°, o que tornou o resultado
   ambíguo entre "girou 110° num sentido" e "girou 249° no outro".

Nenhuma das três foi culpa do robô.

---

## Como as janelas funcionam

O Claude dispara o teste e **a mensagem dele chega enquanto o teste roda** (os
testes são lançados em segundo plano justamente para isso). Então:

- **Comece a agir assim que ler "► ... AGORA"**, uns 5 segundos depois do
  disparo, que é o tempo do sensor engatar.
- **Não escreva nada durante a janela.** Parar para responder foi o que zerou a
  medição do encoder. O Claude avisa quando pode parar.
- Se a janela acabar antes de você conseguir agir, **não invente um resultado**:
  diga que não deu tempo. Refazer custa 2 minutos; uma conclusão errada custa
  uma fase.

---

## Procedimento A — giro no lugar (sinal do yaw)

**Para que serve:** descobrir se, no nosso sensor, girar para a direita aumenta
ou diminui o yaw. Disso depende a malha de rumo endireitar ou espiralar.

**Nada é comandado.** Só o BNO085 é lido.

### Antes de começar

1. Robô **no chão**, apoiado nas duas rodas, como opera.
2. **Não levante o robô** e não o incline — a medida é do giro em torno do eixo
   vertical. Inclinar mistura outro eixo.
3. Escolha uma **referência fixa** na sala para a frente do robô apontar: uma
   porta, uma quina, um móvel.

### O giro

4. **"Para a direita" = sentido horário, visto de cima.** A frente do robô
   caminha para o lado direito dele. Como um relógio: a frente sai das **12h** e
   vai para as **3h**.
5. Gire **cerca de 90°** — um quarto de volta. **Não gire mais que isso**: giro
   grande aumenta a chance de cruzar o ±180° e é justamente o que estragou a
   primeira medida.
6. **Devagar**: leve uns **5 segundos** para fazer os 90°. O script lê a 50 Hz e
   avisa se perder leitura, mas devagar é mais seguro.
7. **Num movimento só, sem voltar.** Não faça vai-e-vem. Se passar do ponto,
   **deixe como está** — não corrija voltando, porque a volta cancela a soma.
8. Terminado o giro, **solte o robô e não encoste mais** até o fim da janela.

### O que o resultado vai dizer

```
Giro ACUMULADO: +91.3°   -> girar à DIREITA AUMENTA o yaw
Giro ACUMULADO: -91.3°   -> girar à DIREITA DIMINUI o yaw
```

O sinal é o que importa; o valor serve para conferir se o giro foi mesmo de
~90°. Se vier algo como ±15°, o robô mal girou e a medida não vale.

---

## Procedimento B — empurrar em linha reta (encoders)

**Para que serve:** contar os pulsos dos sensores Hall das rodas.

1. Robô no chão. A retenção é solta pelo script, então as rodas giram leves.
2. **Empurre para a frente e puxe para trás**, em linha reta, sem girar o robô.
3. **Devagar** — o contador tem debounce de 10 ms; giro rápido pode perder
   pulso.
4. **Não pare** durante a janela inteira, e **não escreva** para o Claude.
5. Referência: 45 ticks por volta da roda, e uma roda de 6,5" anda ~0,52 m por
   volta. Dois metros de ida e volta dão ~170 ticks por lado.

---

## Procedimento C — empurrar para sentir o freio

**Para que serve:** saber se o robô fica retido ou livre quando parado.

1. **Empurre com força moderada**, para frente e para trás, algumas vezes.
2. O que interessa é a **diferença de resistência** entre as duas janelas
   (segurando × livre), não o valor absoluto.
3. Empurre do mesmo jeito nas duas, senão a comparação não vale.

---

## Procedimento D — a reta de 2 metros (o gate da Fase 3)

**Para que serve:** provar que a malha de rumo funciona. Este é o único em que
o robô **anda sozinho**.

1. **Marque a linha de partida no chão** e alinhe as rodas nela.
2. **Marque também a direção** — um barbante, uma fita, ou a junta do piso —
   para dar de onde medir o desvio lateral.
3. **Saia da frente do robô.** O LIDAR vigia um arco de ±30° à frente e
   bloqueia qualquer coisa a menos de 0,50 m — inclusive você. Em 22/09/2026 uma
   rodada foi perdida porque o professor ainda estava alinhando o robô quando o
   teste começou. O script agora dá **6 segundos de carência** antes de andar, e
   se ainda houver obstáculo no arco ele recusa e diz a distância e o ângulo.

4. Fique **ao lado da chave geral** durante todo o percurso, nunca à frente.
   Enquanto não houver botão cogumelo, ela é o E-Stop.
5. O robô anda até o LIDAR bloquear (0,50 m de obstáculo) ou até o tempo acabar.
6. Ao parar, **meça o desvio lateral** em centímetros: o quanto o centro do robô
   saiu da linha de direção.
7. **O teste é feito DUAS vezes**: uma com a correção desligada, outra com ela
   ligada. **Sem o par de medidas não há prova de nada** — o número sozinho não
   diz se a malha ajudou.

---

## Procedimento E — o joystick não pode deixar comando velho (30/09/2026)

**Para que serve:** provar que soltar o manche, ou perder o controle, para o
robô — em giro e em reta. Refazer em todo robô da frota e depois de qualquer
mudança em `core/joystick_reader.py` ou `core/control_loop.py`.

Espaço livre em volta, alguém perto para segurar o robô.

1. **Giro cheio:** manche **todo** para o lado por ~3 s e solte de uma vez. Tem
   que girar o tempo todo (sem cortar a cada 0,2 s) e **parar na hora** ao soltar.
2. **Reta:** manche **todo** para a frente por ~2 s e solte de uma vez. Para na
   hora. (Era o caso perigoso: a malha de rumo reenviava a reta velha.)
3. **Controle desligado andando:** reta com o manche cheio e, **sem soltar**,
   segure o HOME até os LEDs apagarem. O robô para quando o controle apaga.
4. Conferência nos dados: no gravador de varreduras (`data/varreduras/`), o
   campo `mov` volta a `false` logo depois de soltar.

Fatos medidos que sustentam o desenho (hidraw do receptor):
- manche parado no fim do curso = **nenhum** evento (só muda quando o valor muda);
- controle desligado → centro em ~30 ms; fora do alcance (70 m) → centro ao
  perder o sinal, e o comando volta se o sinal voltar com o manche segurado.

---

## Procedimento F — o braço do Aurora (bancada, 30/09/2026)

**Para que serve:** medir onde o ponto que o Aurora reporta fica em relação ao
eixo de giro (`AURORA_BRACO_M`). **Refazer sempre que o suporte ou a posição do
Aurora mudar.** O robô gira sozinho: ~40 cm livres em volta, ninguém perto.

```bash
sudo systemctl stop frota-rosto frota-robo
.venv/bin/python scripts/bancada_pivo.py          # 1 volta para cada lado, 8%
sudo systemctl start frota-robo frota-rosto       # e "Localizar na fita"
```

Os dois sentidos têm que dar o mesmo braço (±2 cm). Se diferirem, o que mudou
é o centro de giro (uma roda rendendo mais), não o Aurora — não atualizar o
settings antes de entender. Medida de 30/09: −5,3 cm (frente) e +7,2 cm
(esquerda); a trena dava a caixa 4 cm atrás e centrada, ou seja, a origem da
pose do SDK não é o centro da caixa.

---

## Procedimento G — "Voltar para a base" medido na trena (30/09/2026)

**Para que serve:** a prova da chegada à base, depois de mexer em pose, braço,
giro ou missão.

1. Robô na fita (**a frente na linha**, centralizado) → "Localizar na fita".
2. Leve-o no joystick a 1,5–2 m, **virado para o lado contrário da fita** (o
   caso difícil: obriga o giro grande ou a aproximação).
3. `/mapa` → "Voltar para a base". A rota deve passar por um ponto **atrás** da
   base (aproximação) quando ele vier torto.
4. Na trena: quantos cm **antes/depois da linha** (cada lado da base) e quantos
   à **esquerda/direita** do meio da fita. Anotar também o que o sistema disse.
5. **Três voltas**, de lugares diferentes (uma de perto, ~80 cm, virado de lado).

Resultado de 30/09: 0,5–2,5 cm · 0,3–2,3 cm · 0 cm, centralizado; o sistema,
1 cm nas três (antes da correção do pivô: 11–12 cm). Uma tentativa parou no
giro com o **rodízio atravessado** — causa mecânica, o vigia parou certo.
