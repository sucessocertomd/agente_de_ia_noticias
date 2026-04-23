"""
NewsAgent v2 — Agente autônomo de notícias de IA para Telegram
Provider de IA intercambiável via .env: anthropic | groq | openai | ollama | openrouter
Autor: Sucesso | Stack: Python 3.11+, APScheduler, aiohttp, BeautifulSoup
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

# Qual provider usar — definido no .env
AI_PROVIDER = os.getenv("AI_PROVIDER", "anthropic").lower()


# ══════════════════════════════════════════════════════
# CAMADA DE PROVIDERS — adicione novos aqui
# ══════════════════════════════════════════════════════

class AIProvider(ABC):
    """Interface base. Todo provider implementa apenas `complete(prompt) -> str`."""

    @abstractmethod
    def complete(self, prompt: str) -> str: ...

    @property
    @abstractmethod
    def name(self) -> str: ...


# ── Anthropic (Claude) ──────────────────────────────
class AnthropicProvider(AIProvider):
    name = "Anthropic (Claude)"

    def __init__(self):
        from anthropic import Anthropic
        self._client = Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
        self._model  = os.getenv("ANTHROPIC_MODEL", "claude-opus-4-5")

    def complete(self, prompt: str) -> str:
        resp = self._client.messages.create(
            model=self._model,
            max_tokens=2000,
            messages=[{"role": "user", "content": prompt}],
        )
        return resp.content[0].text.strip()


# ── Groq ────────────────────────────────────────────
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


# ── OpenAI (GPT) ─────────────────────────────────────
class OpenAIProvider(AIProvider):
    name = "OpenAI (GPT)"

    def __init__(self):
        from openai import OpenAI
        self._client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
        self._model  = os.getenv("OPENAI_MODEL", "gpt-4o-mini")

    def complete(self, prompt: str) -> str:
        resp = self._client.chat.completions.create(
            model=self._model,
            max_tokens=2000,
            messages=[{"role": "user", "content": prompt}],
        )
        return resp.choices[0].message.content.strip()


# ── OpenRouter (acesso a dezenas de modelos) ─────────
class OpenRouterProvider(AIProvider):
    name = "OpenRouter"

    def __init__(self):
        from openai import OpenAI
        self._client = OpenAI(
            api_key=os.getenv("OPENROUTER_API_KEY"),
            base_url="https://openrouter.ai/api/v1",
        )
        # Exemplos: "google/gemini-flash-1.5", "mistralai/mistral-7b-instruct"
        self._model = os.getenv("OPENROUTER_MODEL", "google/gemini-flash-1.5")

    def complete(self, prompt: str) -> str:
        resp = self._client.chat.completions.create(
            model=self._model,
            max_tokens=2000,
            messages=[{"role": "user", "content": prompt}],
        )
        return resp.choices[0].message.content.strip()


# ── Ollama (modelos locais) ───────────────────────────
class OllamaProvider(AIProvider):
    name = "Ollama (local)"

    def __init__(self):
        import requests as _req
        self._requests = _req
        self._base_url = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
        self._model    = os.getenv("OLLAMA_MODEL", "llama3.2")

    def complete(self, prompt: str) -> str:
        resp = self._requests.post(
            f"{self._base_url}/api/chat",
            json={
                "model": self._model,
                "stream": False,
                "messages": [{"role": "user", "content": prompt}],
            },
            timeout=120,
        )
        resp.raise_for_status()
        return resp.json()["message"]["content"].strip()


# ── Google Gemini ─────────────────────────────────────
class GeminiProvider(AIProvider):
    name = "Google Gemini"

    def __init__(self):
        import google.generativeai as genai
        genai.configure(api_key=os.getenv("GEMINI_API_KEY"))
        model_name   = os.getenv("GEMINI_MODEL", "gemini-1.5-flash")
        self._model  = genai.GenerativeModel(model_name)

    def complete(self, prompt: str) -> str:
        resp = self._model.generate_content(prompt)
        return resp.text.strip()


# ── Mistral AI ────────────────────────────────────────
class MistralProvider(AIProvider):
    name = "Mistral AI"

    def __init__(self):
        from mistralai import Mistral
        self._client = Mistral(api_key=os.getenv("MISTRAL_API_KEY"))
        self._model  = os.getenv("MISTRAL_MODEL", "mistral-small-latest")

    def complete(self, prompt: str) -> str:
        resp = self._client.chat.complete(
            model=self._model,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=2000,
        )
        return resp.choices[0].message.content.strip()


# ── Fábrica de providers ──────────────────────────────
PROVIDER_MAP = {
    "anthropic":  AnthropicProvider,
    "groq":       GroqProvider,
    "openai":     OpenAIProvider,
    "openrouter": OpenRouterProvider,
    "ollama":     OllamaProvider,
    "gemini":     GeminiProvider,
    "mistral":    MistralProvider,
}

def build_provider() -> AIProvider:
    cls = PROVIDER_MAP.get(AI_PROVIDER)
    if not cls:
        available = ", ".join(PROVIDER_MAP.keys())
        raise ValueError(f"AI_PROVIDER='{AI_PROVIDER}' inválido. Disponíveis: {available}")
    provider = cls()
    log.info(f"Provider ativo: {provider.name}")
    return provider


# ══════════════════════════════════════════════════════
# FONTES DE NOTÍCIAS
# ══════════════════════════════════════════════════════

SOURCES = [
    {"type": "rss",    "name": "Anthropic Blog",  "url": "https://www.anthropic.com/rss.xml"},
    {"type": "rss",    "name": "The Verge AI",     "url": "https://www.theverge.com/rss/ai-artificial-intelligence/index.xml"},
    {"type": "rss",    "name": "MIT Tech Review",  "url": "https://www.technologyreview.com/feed/"},
    {"type": "rss",    "name": "VentureBeat AI",   "url": "https://venturebeat.com/category/ai/feed/"},
    {"type": "rss",    "name": "Ars Technica",     "url": "https://feeds.arstechnica.com/arstechnica/technology-lab"},
    {"type": "rss",    "name": "Google DeepMind",  "url": "https://deepmind.google/blog/rss.xml"},
    {"type": "rss",    "name": "OpenAI Blog",      "url": "https://openai.com/blog/rss.xml"},
    {"type": "rss",    "name": "TechCrunch AI",    "url": "https://techcrunch.com/category/artificial-intelligence/feed/"},
    {"type": "rss",    "name": "InfoQ AI",         "url": "https://feed.infoq.com/"},
    {"type": "scrape", "name": "Hacker News",      "url": "https://news.ycombinator.com/", "selector": ".titleline > a"},
]

KEYWORDS = [
    "claude", "anthropic", "gemini", "google ai", "openai", "chatgpt",
    "kimi", "moonshot", "llm", "large language model", "artificial intelligence",
    "machine learning", "gpt", "mistral", "llama", "deepseek", "grok", "perplexity",
    "ai agent", "rag", "multimodal", "reasoning model", "foundation model",
    "generative ai", "ai safety", "alignment", "transformer",
]


# ══════════════════════════════════════════════════════
# ESTRUTURA DE DADOS
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


# ══════════════════════════════════════════════════════
# CACHE ANTI-DUPLICATAS
# ══════════════════════════════════════════════════════

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
        except FileNotFoundError:
            self.hashes = set()

    def save(self):
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        with open(self.path, "w") as f:
            json.dump(list(self.hashes)[-1000:], f)

    def is_new(self, item: NewsItem) -> bool:
        return item.hash not in self.hashes

    def mark_seen(self, item: NewsItem):
        self.hashes.add(item.hash)


# ══════════════════════════════════════════════════════
# COLETA DE NOTÍCIAS
# ══════════════════════════════════════════════════════

async def fetch_rss(session: aiohttp.ClientSession, source: dict) -> list[NewsItem]:
    items = []
    try:
        async with session.get(source["url"], timeout=aiohttp.ClientTimeout(total=15)) as r:
            text = await r.text()
        soup = BeautifulSoup(text, "xml")
        entries = soup.find_all("item") or soup.find_all("entry")
        for entry in entries[:20]:
            title = (entry.find("title") or {}).get_text(strip=True)
            link  = (entry.find("link")  or {}).get_text(strip=True)
            if not link and entry.find("link"):
                link = entry.find("link").get("href", "")
            if title and link:
                items.append(NewsItem(title=title, url=link, source=source["name"]))
    except Exception as e:
        log.warning(f"RSS {source['name']} falhou: {e}")
    return items


async def fetch_scrape(session: aiohttp.ClientSession, source: dict) -> list[NewsItem]:
    items = []
    try:
        async with session.get(source["url"], timeout=aiohttp.ClientTimeout(total=15)) as r:
            text = await r.text()
        soup = BeautifulSoup(text, "html.parser")
        for tag in soup.select(source["selector"])[:20]:
            title = tag.get_text(strip=True)
            href  = tag.get("href", "")
            if href and not href.startswith("http"):
                href = source["url"].rstrip("/") + "/" + href.lstrip("/")
            if title and href:
                items.append(NewsItem(title=title, url=href, source=source["name"]))
    except Exception as e:
        log.warning(f"Scrape {source['name']} falhou: {e}")
    return items


def is_relevant(item: NewsItem) -> bool:
    text = (item.title + " " + item.url).lower()
    return any(kw in text for kw in KEYWORDS)


async def collect_all_news() -> list[NewsItem]:
    log.info("Coletando notícias de todas as fontes...")
    connector = aiohttp.TCPConnector(ssl=False)
    async with aiohttp.ClientSession(connector=connector) as session:
        tasks = [
            fetch_rss(session, src) if src["type"] == "rss" else fetch_scrape(session, src)
            for src in SOURCES
        ]
        results = await asyncio.gather(*tasks)

    all_items = [item for sub in results for item in sub]
    relevant  = [item for item in all_items if is_relevant(item)]
    log.info(f"Total coletadas: {len(all_items)} | Relevantes: {len(relevant)}")
    return relevant


# ══════════════════════════════════════════════════════
# CURADORIA COM IA (provider agnóstico)
# ══════════════════════════════════════════════════════

def curate_and_summarize(items: list[NewsItem], provider: AIProvider) -> list[NewsItem]:
    if not items:
        return []

    news_list = "\n".join(
        f"{i+1}. [{item.source}] {item.title} — {item.url}"
        for i, item in enumerate(items[:40])
    )
    today = datetime.now().strftime("%d/%m/%Y")

    prompt = f"""Você é um curador especialista em IA e tecnologia.
Data de hoje: {today}
Provider ativo: {provider.name}

Abaixo estão até 40 manchetes coletadas de diversas fontes. Sua tarefa:

1. Selecione as {MAX_NEWS} mais importantes e relevantes para um leitor técnico brasileiro.
2. Priorize novidades sobre: Claude/Anthropic, Gemini, Kimi IA, modelos open-source, agentes de IA, benchmarks e lançamentos.
3. Para cada notícia selecionada, escreva um resumo CURTO em português (1-2 frases, máx 200 caracteres).
4. Atribua uma nota de relevância de 0 a 10.

Responda APENAS com JSON válido, sem markdown, sem texto antes ou depois, no formato:
[
  {{
    "index": <número original da lista>,
    "summary": "<resumo em pt-BR>",
    "relevance": <0-10>
  }}
]

MANCHETES:
{news_list}
"""

    try:
        raw = provider.complete(prompt)
        raw = raw.replace("```json", "").replace("```", "").strip()
        selections = json.loads(raw)

        result = []
        for sel in selections:
            idx = int(sel["index"]) - 1
            if 0 <= idx < len(items):
                item = items[idx]
                item.summary         = sel.get("summary", "")
                item.relevance_score = float(sel.get("relevance", 0))
                result.append(item)

        result.sort(key=lambda x: x.relevance_score, reverse=True)
        log.info(f"Curadoria concluída com {provider.name}: {len(result)} notícias selecionadas")
        return result

    except Exception as e:
        log.error(f"Erro na curadoria com {provider.name}: {e}")
        return items[:MAX_NEWS]


# ══════════════════════════════════════════════════════
# FORMATAÇÃO E ENVIO TELEGRAM
# ══════════════════════════════════════════════════════

def escape_md(text: str) -> str:
    for ch in r"\_*[]()~`>#+-=|{}.!":
        text = text.replace(ch, f"\\{ch}")
    return text


def format_telegram_message(items: list[NewsItem], provider_name: str) -> str:
    now    = datetime.now().strftime("%d/%m/%Y")
    emojis = ["🔥", "⚡", "🧠", "🚀", "💡", "🌐", "📊", "🔬", "🎯", "✨"]
    lines  = [
        f"🤖 *Bom dia\\! Notícias de IA — {escape_md(now)}*",
        f"_Curadoria autônoma de {len(items)} destaques_\n",
    ]
    for i, item in enumerate(items):
        emoji     = emojis[i % len(emojis)]
        score_bar = "★" * round(item.relevance_score / 2)
        lines.append(
            f"{emoji} *{escape_md(item.title)}*\n"
            f"_{escape_md(item.summary)}_\n"
            f"Fonte: {escape_md(item.source)} {score_bar}\n"
            f"[Ler matéria]({item.url})\n"
        )
    lines.append("—")
    lines.append(f"_NewsAgent v2\\.0 — via {escape_md(provider_name)}_")
    return "\n".join(lines)


async def send_telegram(message: str):
    url     = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    chunks  = [message[i:i+4000] for i in range(0, len(message), 4000)]
    payload = {"chat_id": TELEGRAM_CHAT_ID, "parse_mode": "MarkdownV2", "disable_web_page_preview": False}

    async with aiohttp.ClientSession() as session:
        for chunk in chunks:
            payload["text"] = chunk
            async with session.post(url, json=payload) as r:
                resp = await r.json()
                if not resp.get("ok"):
                    log.error(f"Telegram erro: {resp}")
                else:
                    log.info("Mensagem enviada ao Telegram com sucesso")


# ══════════════════════════════════════════════════════
# PIPELINE PRINCIPAL
# ══════════════════════════════════════════════════════

cache    = SeenCache()
provider = build_provider()   # instância única, reutilizada a cada digest


async def run_daily_digest():
    log.info(f"═══ NewsAgent — pipeline diário [{provider.name}] ═══")

    raw_items = await collect_all_news()
    new_items = [item for item in raw_items if cache.is_new(item)]
    log.info(f"Itens novos (sem duplicatas): {len(new_items)}")

    if not new_items:
        log.info("Nenhuma notícia nova. Sem envio.")
        return

    curated = curate_and_summarize(new_items, provider)

    for item in curated:
        cache.mark_seen(item)
    cache.save()

    message = format_telegram_message(curated, provider.name)
    await send_telegram(message)

    log.info("═══ Pipeline concluído ═══")


# ══════════════════════════════════════════════════════
# ENTRY POINT
# ══════════════════════════════════════════════════════

async def main():
    os.makedirs("logs", exist_ok=True)
    os.makedirs("data", exist_ok=True)

    scheduler = AsyncIOScheduler(timezone="America/Sao_Paulo")
    scheduler.add_job(
        run_daily_digest,
        trigger=CronTrigger(hour=SEND_HOUR, minute=SEND_MINUTE),
        id="daily_digest",
        name="Digest diário de IA",
        misfire_grace_time=300,
        replace_existing=True,
    )
    scheduler.start()
    log.info(f"Scheduler ativo — {SEND_HOUR:02d}:{SEND_MINUTE:02d} BRT | Provider: {provider.name}")

    if "--now" in sys.argv:
        log.info("Modo --now: executando imediatamente")
        await run_daily_digest()

    try:
        while True:
            await asyncio.sleep(60)
    except (KeyboardInterrupt, SystemExit):
        scheduler.shutdown()
        log.info("NewsAgent encerrado.")


if __name__ == "__main__":
    asyncio.run(main())
