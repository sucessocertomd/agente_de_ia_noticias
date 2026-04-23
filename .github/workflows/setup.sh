#!/usr/bin/env bash
# setup.sh — Configura e instala o NewsAgent
set -e

echo "═══════════════════════════════════════"
echo "  NewsAgent — Setup Automático"
echo "═══════════════════════════════════════"

# Verifica Python 3.11+
python3 -c "import sys; assert sys.version_info >= (3,11), 'Precisa Python 3.11+'" \
    || { echo "ERRO: Python 3.11+ necessário"; exit 1; }

# Cria virtualenv
python3 -m venv venv
source venv/bin/activate

# Instala dependências
pip install --upgrade pip -q
pip install -r requirements.txt -q

# Cria estrutura de pastas
mkdir -p logs data

# Cria .env se não existir
if [ ! -f .env ]; then
    cp .env.example .env
    echo ""
    echo "⚠️  Arquivo .env criado. Preencha os valores antes de rodar:"
    echo "   nano .env"
    echo ""
else
    echo "✓ .env já existe"
fi

echo ""
echo "✓ Setup concluído!"
echo ""
echo "Próximos passos:"
echo "  1. Edite o .env com seus tokens"
echo "  2. Teste agora:  source venv/bin/activate && python agent.py --now"
echo "  3. Rode em bg:   nohup python agent.py > logs/stdout.log 2>&1 &"
echo "  4. Ou use o serviço systemd (veja README.md)"
echo ""
