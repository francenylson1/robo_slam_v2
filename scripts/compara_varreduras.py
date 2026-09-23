#!/usr/bin/env python3
"""
scripts/compara_varreduras.py
Compara o que o C1 viu do MESMO ponto do salão em dois momentos diferentes.

É o teste que decide entre as opções B e C da Fase 4
(docs/FASE4_ARQUITETURA_FROTA.md):
  - se boa parte do que o C1 vê a 22 cm se repete de um dia para o outro
    (paredes, colunas, balcão), a frota pode se localizar com ele — opção B;
  - se o que domina muda (cadeiras, mesas, pessoas), o caminho é marcador no
    teto — opção C.

COMO GRAVAR (o gravador do frota-robo já roda sozinho, 1 varredura/s):
  1. Marque um ponto no chão com fita (a base é um bom lugar) e a direção
     em que o robô fica de frente.
  2. Em cada dia, estacione o robô ali, na mesma direção, e deixe-o PARADO
     por uns 2 minutos. Anote a hora.
  3. Compare as duas janelas:

    python3 scripts/compara_varreduras.py \\
        data/varreduras/2026-09-24 --janela-a 14:00-14:05 \\
        data/varreduras/2026-09-26 --janela-b 10:30-10:35

  Cada origem pode ser um arquivo .jsonl ou a pasta de um dia. Só entram as
  varreduras com o robô parado ("mov": false).

O QUE ELE FAZ:
  - para cada grau, a mediana da distância em cada janela;
  - descarta o setor cego traseiro (145°–204°, a coluna do robô) e retornos
    abaixo de 15 cm (decisão 5 do projeto: raio mínimo só no mapeamento);
  - procura o giro (±15°) que melhor alinha as duas janelas, porque ninguém
    estaciona exatamente na mesma direção;
  - conta em quantos graus as duas medianas concordam (±5 cm ou ±3%).

Os limiares do veredito (70% / 40%) são um ponto de partida. Eles devem ser
calibrados com o professor depois das primeiras comparações reais.
"""

import argparse
import glob
import json
import os
import statistics
import sys

SETOR_CEGO   = (145, 204)   # medido em 21/09/2026 — a coluna do próprio robô
MIN_CM       = 15.0
GIRO_MAX     = 15
MIN_VARRED   = 20
LIMIAR_B     = 70.0
LIMIAR_C     = 40.0


def carregar(origem: str, janela: str | None):
    if os.path.isdir(origem):
        arquivos = sorted(glob.glob(os.path.join(origem, "*.jsonl")))
    else:
        arquivos = [origem]
    ini = fim = None
    if janela:
        a, b = janela.split("-")
        ini, fim = a.strip(), b.strip()
    import time as _t
    regs = []
    for arq in arquivos:
        with open(arq, encoding="utf-8") as f:
            for linha in f:
                try:
                    r = json.loads(linha)
                except ValueError:
                    continue            # linha cortada por um SIGKILL
                if r.get("mov"):
                    continue
                hhmm = _t.strftime("%H:%M", _t.localtime(r["t"]))
                if ini and not (ini <= hhmm <= fim):
                    continue
                regs.append(r)
    return regs


def perfil(regs):
    """Mediana da distância (cm) por grau, e em quantas varreduras o grau voltou."""
    bins = [[] for _ in range(360)]
    for r in regs:
        for ang_c, mm in r["p"]:
            cm = mm / 10.0
            if cm < MIN_CM:
                continue
            g = int(round(ang_c / 100.0)) % 360
            if SETOR_CEGO[0] <= g <= SETOR_CEGO[1]:
                continue
            bins[g].append(cm)
    n = max(len(regs), 1)
    # Só vale o grau que voltou em pelo menos metade das varreduras: um retorno
    # esporádico (alguém passando) não é estrutura.
    return [statistics.median(b) if len(b) >= n / 2 else None for b in bins]


def concordam(a, b):
    return abs(a - b) <= max(5.0, 0.03 * max(a, b))


def comparar(pa, pb, giro):
    ambos = iguais = 0
    for g in range(360):
        a, b = pa[g], pb[(g + giro) % 360]
        if a is None or b is None:
            continue
        ambos += 1
        iguais += concordam(a, b)
    return ambos, iguais


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[2])
    ap.add_argument("origem_a")
    ap.add_argument("origem_b")
    ap.add_argument("--janela-a", help="HH:MM-HH:MM")
    ap.add_argument("--janela-b", help="HH:MM-HH:MM")
    arg = ap.parse_args()

    ra = carregar(arg.origem_a, arg.janela_a)
    rb = carregar(arg.origem_b, arg.janela_b)
    print(f"Varreduras com o robô parado: A = {len(ra)}, B = {len(rb)}")
    if len(ra) < MIN_VARRED or len(rb) < MIN_VARRED:
        print(f"Poucas varreduras (mínimo {MIN_VARRED} em cada). Deixe o robô "
              "parado por mais tempo ou confira as janelas.")
        return 2

    pa, pb = perfil(ra), perfil(rb)
    melhor = max(range(-GIRO_MAX, GIRO_MAX + 1),
                 key=lambda d: comparar(pa, pb, d)[1])
    ambos, iguais = comparar(pa, pb, melhor)
    pct = 100.0 * iguais / ambos if ambos else 0.0

    print(f"Giro que alinha B com A: {melhor:+d}°")
    print(f"Graus com retorno estável nas duas janelas: {ambos} "
          f"(de {360 - (SETOR_CEGO[1] - SETOR_CEGO[0] + 1)} úteis)")
    print(f"Graus em que as duas concordam: {iguais} ({pct:.0f}%)")
    print()
    print("Por setor de 30° (0° = frente):")
    for s in range(0, 360, 30):
        amb = igu = 0
        for g in range(s, s + 30):
            a, b = pa[g], pb[(g + melhor) % 360]
            if a is None or b is None:
                continue
            amb += 1
            igu += concordam(a, b)
        barra = "#" * int(round(10 * igu / amb)) if amb else ""
        txt = f"{100*igu/amb:5.0f}%" if amb else "   - "
        print(f"  {s:3d}°–{s+29:3d}°  {txt}  {barra}")
    print()
    if pct >= LIMIAR_B:
        print(f"VEREDITO: {pct:.0f}% ≥ {LIMIAR_B:.0f}% — a estrutura se repete. "
              "Aponta para a opção B (localizar com o C1).")
    elif pct <= LIMIAR_C:
        print(f"VEREDITO: {pct:.0f}% ≤ {LIMIAR_C:.0f}% — o que o C1 vê mudou. "
              "Aponta para a opção C (marcador no teto).")
    else:
        print(f"VEREDITO: {pct:.0f}% — inconclusivo. Comparar mais pontos do "
              "salão e mais dias.")
    print("(Limiares iniciais, a calibrar com as primeiras comparações reais.)")
    return 0


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    sys.exit(main())
