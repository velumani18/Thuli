"""
Diagnostic and Verification Utility for API Keys and Environment Setup.
"""

import os
import sys
import asyncio
from pathlib import Path
from dotenv import load_dotenv

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
load_dotenv(PROJECT_ROOT / ".env")

from app.core.config import settings
from app.core.llm import LLMClient
from app.memory.store import EntityMemoryStore


async def verify():
    print("=" * 75)
    print("ANALYST & AUDITOR: API KEY & SYSTEM VERIFICATION")
    print("=" * 75)

    # 1. Database
    print("\n[1] Database Status (SQLite Relational + FTS5 BM25):")
    db_file = settings.db_path
    print(f"  - Location: {db_file}")
    try:
        mem = EntityMemoryStore(db_path=db_file)
        count = len(mem.get_all_entities())
        print("  --> STATUS: ACTIVE & READY (No external API key or cloud DB needed).")
        print(f"      Currently tracked entities in SQLite: {count}")
    except Exception as e:
        print(f"  --> STATUS: ERROR: {e}")

    # 2. LLM Keys
    print("\n[2] LLM API Keys & Provider Configuration:")
    print(f"  - Active LLM Model: {settings.llm_model}")

    gemini_key = os.getenv("GEMINI_API_KEY", "").strip()
    openai_key = os.getenv("OPENAI_API_KEY", "").strip()
    anthropic_key = os.getenv("ANTHROPIC_API_KEY", "").strip()

    def mask(k):
        return f"{k[:6]}...{k[-4:]}" if len(k) > 10 else ("PRESENT" if k else "NOT CONFIGURED")

    print(f"  - GEMINI_API_KEY:    {mask(gemini_key)}")
    print(f"  - OPENAI_API_KEY:    {mask(openai_key)}")
    print(f"  - ANTHROPIC_API_KEY: {mask(anthropic_key)}")

    active_key = gemini_key if "gemini" in settings.llm_model.lower() else openai_key
    if not active_key:
        print(f"  --> STATUS: No active API key set for {settings.llm_model}.")
        print(f"      To run live web research, add your key to {PROJECT_ROOT / '.env'}")
    else:
        print(f"  --> Testing live connection to {settings.llm_model}...")
        try:
            llm = LLMClient()
            resp = await llm.generate("Respond with exactly: LLM_CONNECTION_OK")
            print(f"  --> SUCCESS! Response: \"{resp.content.strip()}\"")
            print(f"      Tokens: {resp.total_tokens} | Cost: ${resp.cost_usd:.6f} (Rs. {resp.cost_inr:.4f})")
        except Exception as e:
            print(f"  --> FAILED: {str(e)}")

    # 3. Web Search
    print("\n[3] Web Search Provider Status:")
    tavily_key = os.getenv("TAVILY_API_KEY", "").strip()
    print(f"  - TAVILY_API_KEY:    {mask(tavily_key)}")
    if tavily_key:
        print("  - Mode: Primary Tavily Search Engine")
    else:
        print("  - Mode: Built-in DuckDuckGo Search (Free fallback, no API key required)")

    print("\n" + "=" * 75)


if __name__ == "__main__":
    asyncio.run(verify())
