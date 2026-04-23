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
from abc import ABC, abstractmethod
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

# ══════════════════════════════════════════════════════
# PROVIDER IA (Apenas Groq para simplificar, adicione outros se precisar)
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
            with open(self.path) as f: return set(json.load(f))
        except: return set()
    def save(self):
        with open(self.path, "w") as f: json.dump(list(self.hashes)[-1000:], f)
    def is_new(self, item: NewsItem): return item.hash not in self.hashes
    def mark_seen(self, item: NewsItem): self.hashes.add(item.hash)

async def collect_news():
    sources = [
        {"type": "rss", "name": "The Verge AI", "url": "https://www.theverge.com/rss/ai-artificial-intelligence/index.xml"},
        {"type": "rss", "name": "MIT Tech", "url": "https://www.technologyreview.com/feed/"},
        {"type": "scrape", "name": "Hacker News", "url": "https://news.ycombinator.com/", "selector": ".titleline > a"}
    ]
    keywords = ["ai", "claude", "gpt", "llm", "google", "meta", "nvidia", "openai"]
    items = []
    async with aiohttp.ClientSession(connector=aiohttp.TCPConnector(ssl=False)) as session:
        for src in sources:
            try:
                async with session.get(src["url"], timeout=10) as r:
                    soup = BeautifulSoup(await r.text(), "xml" if src["type"]=="rss" else "html.parser")
                    raw = soup.find_all("item") if src["type"]=="rss" else soup.select(src["selector"])
                    for t in raw[:15]:
                        title = t.find("title").text if src["type"]=="rss" else t.text
                        link = t.find("link").text if src["type"]=="rss" else t.get("href")
                        if title and any(k in title.lower() for k in keywords):
                            items.append(NewsItem(title=title, url=link, source=src["name"]))
            except Exception as e: log.warning(f"Erro {src['name']}: {e}")
    return items

# ══════════════════════════════════════════════════════
# PIPELINE E ENVIO
# ══════════════════════════════════════════════════════

async def run_digest():
    log.info(f"═══ Iniciando NewsAgent com {AI_PROVIDER} ═══")
    cache = SeenCache()
    news = await collect_news()
    new_items = [n for n in news if cache.is_new(n)]
    
    if not new_items:
        log.info("Nenhuma novidade encontrada.")
        return

    provider = GroqProvider()
    prompt = "Resuma estas notícias de IA em 1 frase curta (PT-BR). Retorne APENAS JSON: [{'index': 1, 'summary': '...', 'relevance': 10}]. Notícias:\n" + \
             "\n".join([f"{i+1}. {n.title}" for i, n in enumerate(new_items[:20])])
    
    try:
        raw = provider.complete(prompt).replace("```json", "").replace("```", "").strip()
        data = json.loads(raw)
        final_list = []
        for d in data:
            item = new_items[int(d["index"])-1]
            item.summary, item.relevance_score = d["summary"], float(d.get("relevance", 5))
            final_list.append(item)
            cache.mark_seen(item)
        cache.save()

        # Envio Telegram
        msg = f"🤖 *IA Digest — {datetime.now().strftime('%d/%m/%Y')}*\n\n"
        for i in sorted(final_list, key=lambda x: x.relevance_score, reverse=True)[:MAX_NEWS]:
            msg += f"• *{i.title}*\n_{i.summary}_\n[Link]({i.url})\n\n"
        
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        async with aiohttp.ClientSession() as session:
            await session.post(url, json={"chat_id": TELEGRAM_CHAT_ID, "text": msg, "parse_mode": "Markdown"})
        log.info("Mensagem enviada com sucesso!")
    except Exception as e:
        log.error(f"Falha no pipeline: {e}")

if __name__ == "__main__":
    # EXECUÇÃO E ENCERRAMENTO IMEDIATO
    asyncio.run(run_digest())
    log.info("Processo finalizado. Saindo...")
    sys.exit(0) # Força a saída para o GitHub Actions
