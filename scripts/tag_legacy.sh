#!/bin/bash
# scripts/tag_legacy.sh
# Executa no repositório ANTIGO (robo_slam v1) para preservar o legado
# antes de arquivar o repositório no GitHub.
#
# Como usar:
#   cd ~/robo_slam          ← pasta do repo ANTIGO
#   bash scripts/tag_legacy.sh

set -e

echo "=== Arquivamento do robo_slam v1 ==="
echo ""

# 1. Garante que estamos no repo certo
if [ ! -f "src/core/robot_motor_controller.py" ]; then
  echo "ERRO: Execute este script dentro do diretório robo_slam (v1)."
  exit 1
fi

# 2. Cria tag de referência final
git add -A
git commit -m "chore: snapshot final antes do arquivamento — migrado para robo_slam_v2" || true
git tag -a "legacy-v1-referencia" -m "Versão legada arquivada. Núcleo motor migrado para robo_slam_v2."
git push origin main --tags

echo ""
echo "✅ Tag 'legacy-v1-referencia' criada e enviada."
echo ""
echo "Próximos passos:"
echo "  1. Acesse https://github.com/francenylson1/robo_slam"
echo "  2. Settings → Danger Zone → Archive this repository"
echo "  3. O repo ficará disponível somente para leitura."
echo ""
echo "Referência do núcleo motor:"
echo "  Tag:    v1.0-estavel-base"
echo "  Commit: d3727e0"
echo "  Pinos documentados em: robo_slam_v2/docs/NUCLEO_MOTOR.md"
