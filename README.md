# 🤖 NewsAgent — Agente Autônomo de Notícias de IA

Agente que coleta, filtra, resume e envia notícias de IA e tecnologia para o seu Telegram **todo dia às 6h da manhã (9h UTC)**, de forma 100% autônoma via **GitHub Actions** — sem servidor, sem custo de infraestrutura.

## Arquitetura

```
FONTES (RSS + Scraping)
       │
       ▼
 [Coleta Assíncrona]    ← aiohttp + BeautifulSoup (timeout real via ClientTimeout)
       │
       ▼
 [Filtro por Keywords]
       │
       ▼
 [Anti-duplicatas]      ← Cache local (data/seen_hashes.json)
       │
       ▼
 [Curadoria + Resumo]   ← Groq (llama-3.3-70b) via API
       │
       ▼
 [Telegram Bot]         ← Sessão isolada com force_close=True
       │
       ▼
    📱 SEU CELULAR (06h toda manhã)
       │
       ▼
 [sys.exit(0)]          ← Processo encerra imediatamente
```

## Por que o GitHub Actions não travava antes (e agora encerra corretamente)

Três problemas foram corrigidos:

1. **`aiohttp` timeout como `int`** — era ignorado em algumas versões do aiohttp.
   Agora usa `aiohttp.ClientTimeout(total=10)` corretamente.

2. **Sockets keep-alive órfãos** — o `TCPConnector` padrão mantém conexões abertas,
   impedindo o event loop de fechar. Agora todos os connectors usam `force_close=True`
   e são fechados explicitamente com `await connector.close()`.

3. **Timeout global ausente** — se qualquer etapa travasse, o processo ficava preso
   até o limite de 15 min do Actions. Agora `asyncio.wait_for(..., timeout=300)`
   garante saída em até 5 minutos.

## Pré-requisitos

- Conta Groq com API Key → https://console.groq.com
- Bot Telegram criado via @BotFather
- Seu Chat ID (use @userinfobot)
- Repositório no GitHub (Actions gratuito para repositórios públicos e privados)

## Configuração (GitHub Actions)

### 1. Fork / clone este repositório

```bash
git clone <seu-repo>
cd news_agent
```

### 2. Configure os Secrets no GitHub

Vá em `Settings → Secrets and variables → Actions → New repository secret`:

| Secret | Valor |
|---|---|
| `TELEGRAM_BOT_TOKEN` | Token do seu bot (ex: `123456:ABC-...`) |
| `TELEGRAM_CHAT_ID` | Seu chat ID (ex: `-100123456789`) |
| `GROQ_API_KEY` | Sua API key do Groq |
| `AI_PROVIDER` | `groq` |

### 3. Habilite o workflow

O arquivo `.github/workflows/daily_digest.yml` já está configurado.
Após o push, vá em `Actions` no GitHub e habilite os workflows se solicitado.

### 4. Teste imediatamente (sem esperar as 6h)

Vá em `Actions → NewsAgent — Daily Digest → Run workflow`.

## Estrutura do projeto

```
news_agent/
├── agent.py                              ← Código principal (corrigido)
├── requirements.txt                      ← Dependências limpas (sem APScheduler)
├── README.md
├── .github/
│   └── workflows/
│       └── daily_digest.yml              ← Cron do GitHub Actions
└── data/
    └── seen_hashes.json                  ← Cache anti-duplicatas (gerado em runtime)
```

> **Nota:** `data/seen_hashes.json` não persiste entre execuções do Actions
> (cada run cria um ambiente limpo). Para persistência real, use um Gist, S3,
> ou faça commit do arquivo ao final de cada execução.

## Personalização

Edite `agent.py`:

- **`sources`** — adicione ou remova fontes RSS/scraping dentro de `collect_news()`
- **`keywords`** — palavras-chave para filtrar relevância
- **`MAX_NEWS`** — quantas notícias por digest (padrão: 10, via env var)
- **`GLOBAL_TIMEOUT`** — tempo máximo total em segundos (padrão: 300)

Edite `daily_digest.yml`:

- **`cron: '0 9 * * *'`** — horário em UTC (9h UTC = 6h Brasília)

## Custos estimados

| Item | Custo mensal |
|---|---|
| Groq API (curadoria diária) | Gratuito (free tier generoso) |
| GitHub Actions | Gratuito (até 2.000 min/mês em repos privados) |
| Telegram Bot | Gratuito |
| **Total** | **$0/mês** |

## Adicionando outros providers de IA

Descomente no `requirements.txt` o provider desejado e adicione a classe correspondente em `agent.py` seguindo o mesmo padrão da `GroqProvider`:

```python
class AnthropicProvider:
    name = "Anthropic"
    def __init__(self):
        import anthropic
        self._client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

    def complete(self, prompt: str) -> str:
        msg = self._client.messages.create(
            model="claude-3-5-haiku-20241022",
            max_tokens=2000,
            messages=[{"role": "user", "content": prompt}],
        )
        return msg.content[0].text.strip()
```
