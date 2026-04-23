"""
NewsAgent v2 — Otimizado para GitHub Actions
Executa o digest e encerra o processo imediatamente.
"""

import asyncio
import logging
import os
import sys
import json
import hashlib
from datetime import datetime
from dataclasses import dataclass, field

import aiohttp
from bs4 import BeautifulSoup
from dotenv import load_dotenv

load_dotenv()

# Garantir pastas de persistência
os.makedirs("logs", exist_ok=True)
os.makedirs("data", exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    handlers=[
        logging.FileHandler("logs/agent.log", encoding="utf-8"),
        logging.StreamHandler(),
    ],
)
log = logging.getLogger("NewsAgent")

# ══════════════════════════════════════════════════════
# CONFIGURAÇÃO
# ══════════════════════════════════════════════════════

TELEGRAM_TOKEN   = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
MAX_NEWS         = int(os.getenv("MAX_NEWS", "10"))
CACHE_FILE       = "data/seen_hashes.json"
AI_PROVIDER      = os.getenv("AI_PROVIDER", "groq").lower()

# Timeout global: 5 minutos máximo para o processo inteiro
GLOBAL_TIMEOUT = 300

# ══════════════════════════════════════════════════════
# PROVIDER IA
# ══════════════════════════════════════════════════════

class GroqProvider:
    name = "Groq"
    def __init__(self):
        from groq import Groq
        self._client = Groq(api_key=os.getenv("GROQ_API_KEY"))
        self._model  = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")

    def complete(self, prompt: str) -> str:
        resp = self._client.chat.completions.create(
            model=self._model,
            max_tokens=2000,
            messages=[{"role": "user", "content": prompt}],
        )
        return resp.choices[0].message.content.strip()

# ══════════════════════════════════════════════════════
# COLETA E CACHE
# ══════════════════════════════════════════════════════

@dataclass
class NewsItem:
    title: str
    url: str
    source: str
    summary: str = ""
    relevance_score: float = 0.0
    hash: str = field(init=False)

    def __post_init__(self):
        self.hash = hashlib.md5(self.url.encode()).hexdigest()

class SeenCache:
    def __init__(self, path: str = CACHE_FILE):
        self.path = path
        self.hashes = self._load()

    def _load(self):
        try:
            with open(self.path) as f:
                return set(json.load(f))
        except:
            return set()

    def save(self):
        with open(self.path, "w") as f:
            json.dump(list(self.hashes)[-1000:], f)

    def is_new(self, item: NewsItem):
        return item.hash not in self.hashes

    def mark_seen(self, item: NewsItem):
        self.hashes.add(item.hash)


async def collect_news():
    sources = [
        {"type": "rss",    "name": "The Verge AI", "url": "https://www.theverge.com/rss/ai-artificial-intelligence/index.xml"},
        {"type": "rss",    "name": "MIT Tech",      "url": "https://www.technologyreview.com/feed/"},
        {"type": "scrape", "name": "Hacker News",   "url": "https://news.ycombinator.com/", "selector": ".titleline > a"},
    ]
    keywords = ["ai", "claude", "gpt", "llm", "google", "meta", "nvidia", "openai"]
    items = []

    # FIX: aiohttp.ClientTimeout em vez de int — garante que o timeout é respeitado
    timeout = aiohttp.ClientTimeout(total=10)

    # FIX: force_close=True — fecha sockets imediatamente, sem keep-alive pendente
    connector = aiohttp.TCPConnector(ssl=False, force_close=True)

    async with aiohttp.ClientSession(connector=connector, timeout=timeout) as session:
        for src in sources:
            try:
                async with session.get(src["url"]) as r:
                    soup = BeautifulSoup(
                        await r.text(),
                        "xml" if src["type"] == "rss" else "html.parser"
                    )
                    raw = soup.find_all("item") if src["type"] == "rss" else soup.select(src["selector"])
                    for t in raw[:15]:
                        title = t.find("title").text if src["type"] == "rss" else t.text
                        link  = t.find("link").text  if src["type"] == "rss" else t.get("href")
                        if title and any(k in title.lower() for k in keywords):
                            items.append(NewsItem(title=title, url=link, source=src["name"]))
            except Exception as e:
                log.warning(f"Erro {src['name']}: {e}")

    # FIX: fecha o connector explicitamente após o uso
    await connector.close()
    return items


# ══════════════════════════════════════════════════════
# ENVIO TELEGRAM — sessão isolada com force_close
# ══════════════════════════════════════════════════════

async def send_telegram(msg: str):
    """Envia mensagem ao Telegram e fecha todos os sockets antes de retornar."""
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"

    # FIX: connector próprio com force_close=True para esta sessão
    connector = aiohttp.TCPConnector(force_close=True)
    timeout   = aiohttp.ClientTimeout(total=15)

    try:
        async with aiohttp.ClientSession(connector=connector, timeout=timeout) as session:
            async with session.post(url, json={
                "chat_id":    TELEGRAM_CHAT_ID,
                "text":       msg,
                "parse_mode": "Markdown",
            }) as resp:
                if resp.status != 200:
                    body = await resp.text()
                    log.error(f"Telegram retornou {resp.status}: {body}")
                else:
                    log.info("Mensagem enviada com sucesso!")
    finally:
        # FIX: garante fechamento mesmo em caso de exceção
        await connector.close()


# ══════════════════════════════════════════════════════
# PIPELINE PRINCIPAL
# ══════════════════════════════════════════════════════

async def run_digest():
    log.info(f"═══ Iniciando NewsAgent com {AI_PROVIDER} ═══")

    cache     = SeenCache()
    news      = await collect_news()
    new_items = [n for n in news if cache.is_new(n)]

    if not new_items:
        log.info("Nenhuma novidade encontrada.")
        return

    provider = GroqProvider()
    prompt = (
        "Resuma estas notícias de IA em 1 frase curta (PT-BR). "
        "Retorne APENAS JSON: [{\"index\": 1, \"summary\": \"...\", \"relevance\": 10}]. "
        "Notícias:\n"
        + "\n".join([f"{i+1}. {n.title}" for i, n in enumerate(new_items[:20])])
    )

    try:
        raw  = provider.complete(prompt).replace("```json", "").replace("```", "").strip()
        data = json.loads(raw)

        final_list = []
        for d in data:
            item = new_items[int(d["index"]) - 1]
            item.summary         = d["summary"]
            item.relevance_score = float(d.get("relevance", 5))
            final_list.append(item)
            cache.mark_seen(item)

        cache.save()

        msg = f"🤖 *IA Digest — {datetime.now().strftime('%d/%m/%Y')}*\n\n"
        for item in sorted(final_list, key=lambda x: x.relevance_score, reverse=True)[:MAX_NEWS]:
            msg += f"• *{item.title}*\n_{item.summary}_\n[Link]({item.url})\n\n"

        # FIX: função isolada com connector próprio — sem sockets órfãos
        await send_telegram(msg)

    except Exception as e:
        log.error(f"Falha no pipeline: {e}")


# ══════════════════════════════════════════════════════
# ENTRY POINT
# ══════════════════════════════════════════════════════

if __name__ == "__main__":
    try:
        # FIX: wait_for com timeout global — garante saída mesmo se algo travar
        asyncio.run(asyncio.wait_for(run_digest(), timeout=GLOBAL_TIMEOUT))
    except asyncio.TimeoutError:
        log.warning("Timeout global atingido — encerrando forçado.")
    except asyncio.CancelledError:
        log.warning("Tarefa cancelada — encerrando.")
    except Exception as e:
        log.error(f"Erro inesperado: {e}")
    finally:
        log.info("Processo finalizado. Saindo...")
        sys.exit(0)
