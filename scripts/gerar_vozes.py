#!/usr/bin/env python3
"""
scripts/gerar_vozes.py
Gera os arquivos de voz do robô a partir das frases do settings.py (Fase 2).

O robô NÃO sintetiza voz em operação. Na Pi 5, o Piper leva ~4 s para produzir
uma frase de 2 s — um "Com licença!" com 4 segundos de atraso chega depois da
pessoa. Então as frases são geradas aqui, na bancada, e versionadas como .wav.
Os robôs da frota recebem os arquivos prontos pelo git e só tocam.

Uso NA PI (onde o Piper está instalado):
    python3 scripts/gerar_vozes.py
    python3 scripts/gerar_vozes.py --voz pt_BR-cadu-medium    # experimentar outra

Depois, ouvir o que saiu:
    python3 scripts/gerar_vozes.py --ouvir

Preparar o Piper (uma vez, em qualquer máquina de bancada):
    python3 -m venv ~/piper-venv
    ~/piper-venv/bin/pip install piper-tts
    mkdir -p ~/piper-vozes && cd ~/piper-vozes
    V=pt_BR-faber-medium
    B=https://huggingface.co/rhasspy/piper-voices/resolve/main/pt/pt_BR/faber/medium
    curl -sL $B/$V.onnx -o $V.onnx && curl -sL $B/$V.onnx.json -o $V.onnx.json

Vozes pt-BR disponíveis: faber, cadu, jeff (medium) e edresson (low).
A escolhida em 22/09/2026, de ouvido, foi a faber.
"""

import argparse
import os
import subprocess
import sys
import wave

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config.settings import AUDIO_DIR, VOZ_FRASES, VOZ_MODELO

PIPER_PADRAO  = os.path.expanduser("~/piper-venv/bin/piper")
VOZES_PADRAO  = os.path.expanduser("~/piper-vozes")


def duracao_s(caminho: str) -> float:
    with wave.open(caminho) as w:
        return w.getnframes() / w.getframerate()


def gerar(piper: str, modelo: str, destino: str) -> int:
    os.makedirs(destino, exist_ok=True)
    erros = 0

    for chave, texto in VOZ_FRASES.items():
        saida = os.path.join(destino, f"{chave}.wav")
        try:
            subprocess.run([piper, "-m", modelo, "-f", saida],
                           input=texto, text=True, check=True,
                           capture_output=True)
        except subprocess.CalledProcessError as e:
            print(f"  ✗ {chave}: piper falhou — {e.stderr.strip()[:200]}")
            erros += 1
            continue

        tam = os.path.getsize(saida)
        # Um .wav de 44 bytes é só o cabeçalho: o Piper "funcionou" e não
        # produziu áudio nenhum. Já aconteceu com texto vazio.
        if tam < 1000:
            print(f"  ✗ {chave}: arquivo vazio ({tam} bytes)")
            erros += 1
            continue

        print(f"  ✓ {chave:8} {duracao_s(saida):4.2f}s  {tam//1024:4d} KB  “{texto}”")

    return erros


def ouvir(destino: str) -> int:
    """Toca o que foi gerado, pelo PipeWire (nunca em cima do hardware:
    o PipeWire da sessão segura a placa e um aplay direto dá 'ocupado')."""
    import time
    for chave in VOZ_FRASES:
        caminho = os.path.join(destino, f"{chave}.wav")
        if not os.path.exists(caminho):
            print(f"  ✗ {chave}: não gerado ainda")
            continue
        print(f"  ♪ {chave}")
        subprocess.run(["pw-play", caminho])
        time.sleep(0.6)
    return 0


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--voz", default=VOZ_MODELO,
                   help=f"modelo Piper a usar (padrão: {VOZ_MODELO})")
    p.add_argument("--piper", default=PIPER_PADRAO, help="binário do piper")
    p.add_argument("--vozes", default=VOZES_PADRAO, help="pasta dos modelos .onnx")
    p.add_argument("--destino", default=AUDIO_DIR, help="onde gravar os .wav")
    p.add_argument("--ouvir", action="store_true",
                   help="apenas tocar os arquivos já gerados")
    args = p.parse_args()

    destino = os.path.abspath(args.destino)

    if args.ouvir:
        return ouvir(destino)

    modelo = os.path.join(os.path.expanduser(args.vozes), f"{args.voz}.onnx")

    if not os.path.exists(args.piper):
        print(f"Piper não encontrado em {args.piper}.")
        print("Veja o cabeçalho deste arquivo para instalar (é ferramenta de")
        print("bancada — de propósito NÃO está no requirements.txt).")
        return 2
    if not os.path.exists(modelo):
        print(f"Modelo de voz não encontrado: {modelo}")
        return 2

    print(f"Voz: {args.voz}")
    print(f"Destino: {destino}\n")
    erros = gerar(args.piper, modelo, destino)

    print()
    if erros:
        print(f"{erros} frase(s) falharam.")
        return 1
    print(f"{len(VOZ_FRASES)} frases geradas. Ouvir: "
          f"python3 scripts/gerar_vozes.py --ouvir")
    return 0


if __name__ == "__main__":
    sys.exit(main())
