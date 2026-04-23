"""
NewsAgent v2 — Agente autônomo de notícias de IA para Telegram
Otimizado para GitHub Actions (Execução Efêmera)
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
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
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
# CONFIGURAÇÃO GERAL
# ══════════════════════════════════════════════════════

TELEGRAM_TOKEN   = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
SEND_HOUR        = int(os.getenv("SEND_HOUR", "6"))
SEND_MINUTE      = int(os.getenv("SEND_MINUTE", "0"))
MAX_NEWS         = int(os.getenv("MAX_NEWS", "10"))
CACHE_FILE       = "data/seen_hashes.json"

AI_PROVIDER = os.getenv("AI_PROVIDER", "anthropic").lower()


# ══════════════════════════════════════════════════════
# CAMADA DE PROVIDERS
# ══════════════════════════════════════════════════════

class AIProvider(ABC):
    @abstractmethod
    def complete(self, prompt: str) -> str: ...
    @property
    @abstractmethod
    def name(self) -> str: ...

class GroqProvider(AIProvider):
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

# (Outros providers omitidos para brevidade, mas o sistema de fábrica permanece)
PROVIDER_MAP = {
    "groq": GroqProvider,
    # Adicione outros aqui se necessário
}

def build_provider() -> AIProvider:
    cls = PROVIDER_MAP.get(AI_PROVIDER, GroqProvider)
    provider = cls()
    log.info(f"Provider ativo: {provider.name}")
    return provider


# ══════════════════════════════════════════════════════
# FONTES E LÓGICA DE COLETA
# ══════════════════════════════════════════════════════

SOURCES = [
    {"type": "rss",    "name": "Anthropic Blog",  "url": "https://www.anthropic.com/rss.xml"},
    {"type": "rss",    "name": "The Verge AI",     "url": "https://www.theverge.com/rss/ai-artificial-intelligence/index.xml"},
    {"type": "rss",    "name": "MIT Tech Review",  "url": "https://www.technologyreview.com/feed/"},
    {"type": "rss",    "name": "VentureBeat AI",   "url": "https://venturebeat.com/category/ai/feed/"},
    {"type": "scrape", "name": "Hacker News",      "url": "https://news.ycombinator.com/", "selector": ".titleline > a"},
]

KEYWORDS = ["claude", "anthropic", "gemini", "openai", "chatgpt", "llm", "ai agent", "deepseek"]

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
        self.hashes: set[str] = set()
        self._load()
    def _load(self):
        try:
            with open(self.path) as f:
                data = json.load(f)
            self.hashes = set(data[-1000:])
        except: self.hashes = set()
    def save(self):
        with open(self.path, "w") as f:
            json.dump(list(self.hashes)[-1000:], f)
    def is_new(self, item: NewsItem) -> bool: return item.hash not in self.hashes
    def mark_seen(self, item: NewsItem): self.hashes.add(item.hash)

async def collect_all_news() -> list[NewsItem]:
    log.info("Coletando notícias...")
    connector = aiohttp.TCPConnector(ssl=False)
    async with aiohttp.ClientSession(connector=connector) as session:
        items = []
        for src in SOURCES:
            try:
                async with session.get(src["url"], timeout=15) as r:
                    soup = BeautifulSoup(await r.text(), "xml" if src["type"]=="rss" else "html.parser")
                    # Lógica simplificada de extração
                    tags = soup.find_all("item") if src["type"]=="rss" else soup.select(src.get("selector",""))
                    for t in tags[:15]:
                        title = t.find("title").text if src["type"]=="rss" else t.text
                        link = t.find("link").text if src["type"]=="rss" else t.get("href")
                        if title and link: items.append(NewsItem(title=title, url=link, source=src["name"]))
            except Exception as e: log.warning(f"Erro em {src['name']}: {e}")
    return [i for i in items if any(kw in (i.title).lower() for kw in KEYWORDS)]

def curate_and_summarize(items: list[NewsItem], provider: AIProvider) -> list[NewsItem]:
    if not items: return []
    prompt = f"Selecione as {MAX_NEWS} notícias mais importantes desta lista e resuma cada uma em 1 frase curta em Português. Retorne APENAS um JSON: [{{'index': 1, 'summary': '...', 'relevance': 10}}]. Lista: " + "\n".join([f"{idx+1}. {i.title}" for idx, i in enumerate(items[:30])])
    try:
        raw = provider.complete(prompt).replace("```json", "").replace("```", "").strip()
        selections = json.loads(raw)
        res = []
        for s in selections:
            item = items[int(s["index"])-1]
            item.summary, item.relevance_score = s["summary"], float(s["relevance"])
            res.append(item)
        return sorted(res, key=lambda x: x.relevance_score, reverse=True)
    except: return items[:MAX_NEWS]

async def send_telegram(message: str):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    async with aiohttp.ClientSession() as session:
        await session.post(url, json={"chat_id": TELEGRAM_CHAT_ID, "text": message, "parse_mode": "MarkdownV2"})

# ══════════════════════════════════════════════════════
# PIPELINE E EXECUÇÃO
# ══════════════════════════════════════════════════════

cache = SeenCache()
provider = build_provider()

async def run_daily_digest():
    log.info("═══ Iniciando Pipeline ═══")
    news = await collect_all_news()
    new_news = [n for n in news if cache.is_new(n)]
    if not new_news:
        log.info("Sem novidades.")
        return
    
    curated = curate_and_summarize(new_news, provider)
    for i in curated: cache.mark_seen(i)
    cache.save()
    
    # Formatação simplificada para exemplo
    msg = f"🤖 *Notícias de IA — {datetime.now().strftime('%d/%m/%Y')}*\n\n"
    for i in curated:
        msg += f"• *{i.title}*\n_{i.summary}_\n[Link]({i.url})\n\n"
    
    await send_telegram(msg.replace(".", "\\.").replace("-", "\\-").replace("!", "\\!"))
    log.info("═══ Pipeline Concluído ═══")

async def main():
    # MODO GITHUB ACTIONS (Executa e encerra)
    if "--now" in sys.argv:
        log.info("Execução única iniciada...")
        await run_daily_digest()
        log.info("Trabalho feito. Encerrando processo para poupar recursos.")
        return 

    # MODO SERVIDOR (Para rodar localmente ou em VPS)
    scheduler = AsyncIOScheduler(timezone="America/Sao_Paulo")
    scheduler.add_job(run_daily_digest, CronTrigger(hour=SEND_HOUR, minute=SEND_MINUTE))
    scheduler.start()
    log.info(f"Servidor aguardando próximo envio às {SEND_HOUR:02d}:{SEND_MINUTE:02d}")
    try:
        while True: await asyncio.sleep(3600)
    except (KeyboardInterrupt, SystemExit): pass

if __name__ == "__main__":
    asyncio.run(main())
