# 🤖 NewsAgent — Agente Autônomo de Notícias de IA

Agente que coleta, filtra, resume e envia notícias de IA e tecnologia para o seu Telegram **todo dia às 6h da manhã**, de forma 100% autônoma.

## Arquitetura

```
FONTES (RSS + Scraping)
       │
       ▼
 [Coleta Assíncrona]  ← aiohttp + BeautifulSoup
       │
       ▼
 [Filtro por Keywords]
       │
       ▼
 [Anti-duplicatas]   ← Cache local (data/seen_hashes.json)
       │
       ▼
 [Curadoria + Resumo] ← Claude (Anthropic API)
       │
       ▼
 [Telegram Bot]       ← Mensagem formatada com MarkdownV2
       │
       ▼
    📱 SEU CELULAR (06h toda manhã)
```

## Pré-requisitos

- Python 3.11+
- Conta Anthropic com API Key → https://console.anthropic.com
- Bot Telegram criado via @BotFather
- Seu Chat ID (use @userinfobot)

## Instalação

```bash
# 1. Clone / baixe o projeto
cd news_agent

# 2. Rode o setup automático
chmod +x setup.sh
./setup.sh

# 3. Preencha o .env
nano .env

# 4. Teste agora mesmo (sem esperar as 6h)
source venv/bin/activate
python agent.py --now
```

## Rodar como serviço permanente (Linux)

```bash
# Copie o arquivo de serviço
sudo cp news-agent.service /etc/systemd/system/

# Edite o caminho do usuário dentro do arquivo
sudo nano /etc/systemd/system/news-agent.service

# Ative e inicie
sudo systemctl daemon-reload
sudo systemctl enable news-agent
sudo systemctl start news-agent

# Veja os logs em tempo real
sudo journalctl -u news-agent -f
```

## Rodar em VPS / servidor simples

```bash
# Com nohup (continua após fechar o terminal)
nohup python agent.py > logs/stdout.log 2>&1 &

# Ver logs
tail -f logs/agent.log
```

## Personalização

Edite `agent.py`:

- **`SOURCES`** — adicione ou remova fontes RSS/scraping
- **`KEYWORDS`** — palavras-chave para filtrar relevância
- **`SEND_HOUR / SEND_MINUTE`** — horário de envio (padrão: 06:00 Brasília)
- **`MAX_NEWS_PER_DIGEST`** — quantas notícias por dia (padrão: 10)

## Custos estimados

| Item | Custo mensal |
|---|---|
| Claude API (curadoria diária ~2k tokens) | ~$0.50 |
| VPS básica para rodar 24/7 | ~$5.00 |
| Telegram Bot | Grátis |
| **Total** | **~$5.50/mês** |

## Estrutura de pastas

```
news_agent/
├── agent.py              ← Código principal
├── requirements.txt
├── .env.example
├── .env                  ← Seus tokens (não commitar!)
├── setup.sh
├── news-agent.service    ← Daemon systemd
├── logs/
│   └── agent.log
└── data/
    └── seen_hashes.json  ← Cache anti-duplicatas
```
