"""
Live Component Capabilities Probe.
Tests each subsystem to verify actual operational status.
"""

import sys
import os
import asyncio
from pathlib import Path

# Ensure UTF-8 output on Windows
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from app.tools.search import SearchEngine
from app.tools.fetcher import ResilientFetcher
from app.memory.store import EntityMemoryStore
from app.core.telemetry import RunLogRecord, ToolInvocationLog, ClaimAuditRecord
from app.core.llm import LLMClient
from app.core.config import settings


async def run_live_tests():
    print("=" * 75)
    print("LIVE SUBSYSTEM FUNCTIONALITY PROBE")
    print("=" * 75)

    # 1. LIVE WEB SEARCH
    print("\n[1] Testing Live Web Search (DuckDuckGo fallback)...")
    searcher = SearchEngine()
    s_res = await searcher.search("Zepto quick commerce India", max_results=2)
    if s_res.items and len(s_res.items) > 0:
        print(f"  --> SUCCESS: Retrieved {len(s_res.items)} search results via {s_res.engine} in {s_res.duration_ms:.0f}ms")
        for it in s_res.items:
            print(f"      * Title: {it.title[:50]}... | URL: {it.url[:60]}")
    else:
        print(f"  --> FAILED: Error: {s_res.error}")

    # 2. LIVE PAGE FETCHING
    print("\n[2] Testing Live Page Fetching (httpx + trafilatura)...")
    fetcher = ResilientFetcher(timeout_seconds=6.0)
    test_url = "https://example.com"
    f_res = await fetcher.fetch_page(test_url)
    if f_res.status == "SUCCESS" and len(f_res.extracted_text) > 0:
        print(f"  --> SUCCESS: Fetched {test_url} in {f_res.duration_ms:.0f}ms (HTTP {f_res.status_code})")
        print(f"      Extracted Text: \"{f_res.extracted_text.strip()[:60]}...\"")
    else:
        print(f"  --> FAILED: Status: {f_res.status}, Error: {f_res.error_message}")

    # 3. SQLITE ENTITY MEMORY
    print("\n[3] Testing SQLite Entity Memory...")
    test_db = PROJECT_ROOT / "app" / "memory" / "test_probe.db"
    mem = EntityMemoryStore(db_path=test_db)
    mem.save_entity("Zepto", "quick_commerce", ["KiranaKart"])
    mem.save_fact("Zepto", "headquarters", "Mumbai, India", "https://example.com/zepto")
    retrieved = mem.get_facts_for_entity("Zepto")
    anaphora = mem.resolve_context("Which of those companies is based in Mumbai?")
    if len(retrieved) > 0 and anaphora["memory_hit"] is True:
        print(f"  --> SUCCESS: Saved entity, retrieved {len(retrieved)} fact(s), resolved anaphora successfully.")
    else:
        print(f"  --> FAILED: Memory query or anaphora resolution failed.")
    if test_db.exists():
        test_db.unlink()

    # 4. RUN LOGGING TO logs/runs/
    print("\n[4] Testing Run Logging to logs/runs/...")
    test_record = RunLogRecord(
        question="Smoke test question",
        model_name="probe-test",
        prompt_tokens=100,
        completion_tokens=50,
        total_tokens=150,
        cost_usd=0.0001,
        cost_inr=0.0087,
    )
    test_record.audit_records.append(
        ClaimAuditRecord(
            claim_id="claim_probe",
            claim_text="Probe claim verified",
            verdict="SUPPORTED",
            auditor_explanation="Smoke test audit",
        )
    )
    saved_path = test_record.save_to_disk()
    if Path(saved_path).exists():
        print(f"  --> SUCCESS: Created and verified run log file at:\n      {saved_path}")
        # Clean up test probe log file
        Path(saved_path).unlink()
    else:
        print("  --> FAILED: Run log file was not created.")

    # 5. LLM CLIENT API KEY STATUS
    print("\n[5] Testing LLM Client Key Configuration...")
    llm = LLMClient()
    has_gemini = bool(settings.gemini_api_key or os.getenv("GEMINI_API_KEY"))
    has_openai = bool(settings.openai_api_key or os.getenv("OPENAI_API_KEY"))
    print(f"  - Configured Model: {settings.llm_model}")
    print(f"  - GEMINI_API_KEY set: {'YES' if has_gemini else 'NO (Required for live LLM calls)'}")
    print(f"  - OPENAI_API_KEY set: {'YES' if has_openai else 'NO'}")

    print("\n" + "=" * 75)


if __name__ == "__main__":
    asyncio.run(run_live_tests())
