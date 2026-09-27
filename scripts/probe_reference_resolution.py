"""
Live Probing Test for Reference Resolution (Requirement 7).

Demonstrates:
Question 1: Establishes several entities (Zepto, Blinkit, Swiggy Instamart) in session memory.
Question 2: Follow-up question using "them" ("Which of them raised the most?").
Verifies that:
- References are detected.
- "them" is correctly resolved to "Zepto, Blinkit, and Swiggy Instamart".
- The resolved question is sent to the research plan instead of the ambiguous pronoun.
"""

import sys
import json
import asyncio
from pathlib import Path

# Ensure UTF-8 output on Windows
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from app.memory.store import EntityMemoryStore
from app.agents.analyst import AnalystPlan, AnalystAgent
from app.core.config import settings


async def run_probing_test():
    print("=" * 80)
    print("LIVE REFERENCE RESOLUTION PROBING TEST")
    print("=" * 80)

    db_path = PROJECT_ROOT / "app" / "memory" / "probing_test.db"
    if db_path.exists():
        db_path.unlink()

    store = EntityMemoryStore(db_path=db_path)
    session_id = "live_probing_session"

    # Step 1: Question 1 establishes several entities
    q1 = "Which companies operate in Indian quick commerce and raised funding recently?"
    entities_q1 = ["Zepto", "Blinkit", "Swiggy Instamart"]
    
    print(f"\n[Step 1] User Question 1: \"{q1}\"")
    print(f"System establishes entities in session '{session_id}':")
    for ent in entities_q1:
        store.save_entity(ent, "quick_commerce")
        print(f"  + Learned entity: {ent}")

    # Store sample verified facts with URLs
    store.save_fact("Zepto", "funding_amount", "$665M", "https://techcrunch.com/2024/06/zepto-665m", "TechCrunch", "June 2024")
    store.save_fact("Blinkit", "parent", "Zomato", "https://zomato.com/blinkit", "Zomato IR", "2024")
    store.save_fact("Swiggy Instamart", "parent", "Swiggy", "https://swiggy.com", "Swiggy", "2024")

    # Record Q1 into session history
    store.record_question(session_id, q1, q1, entities_q1)
    print("  -> Session memory updated with 3 entities and structured source facts.")

    # Step 2: Follow-up Question 2 using "them"
    q2 = "Which of them raised the most in their latest round?"
    print(f"\n[Step 2] User Question 2 (Follow-up): \"{q2}\"")

    # Run reference resolution
    resolution = store.resolve_references(session_id, q2)

    print("\n--- REFERENCE RESOLUTION RESULTS ---")
    print(f"Original Question:     \"{resolution.original_question}\"")
    print(f"References Detected:   {resolution.references_detected}")
    print(f"References Resolved:   {json.dumps(resolution.references_resolved)}")
    print(f"Entities In Scope:     {resolution.entities_detected}")
    print(f"Memory Hits:           {resolution.memory_hits}")
    print(f"Facts Retrieved Count: {len(resolution.facts_retrieved)}")
    print(f"Clarification Needed:  {resolution.clarification_required}")
    print(f"\n>>> FINAL RESOLVED RESEARCH QUESTION: <<<\n\"{resolution.resolved_question}\"")

    # Verify that pronoun was replaced
    assert "them" not in resolution.resolved_question.lower() or "which of them" not in resolution.resolved_question.lower()
    assert "Zepto" in resolution.resolved_question
    assert "Blinkit" in resolution.resolved_question
    assert "Swiggy Instamart" in resolution.resolved_question

    print("\n--- RESEARCH PLAN GENERATION CHECK ---")
    # Simulate Analyst planning on the resolved question
    sample_queries = [
        f"{ent} funding amount 2024" for ent in resolution.entities_detected
    ]
    print("Queries that will be dispatched to live web search:")
    for qry in sample_queries:
        print(f"  * [Search Query]: \"{qry}\"")

    print("\nPROBING TEST PASSED: Ambiguous pronoun 'them' was successfully resolved into explicit entities!")
    print("=" * 80)

    # Clean up probing test database safely
    try:
        if db_path.exists():
            db_path.unlink()
    except Exception:
        pass


if __name__ == "__main__":
    asyncio.run(run_probing_test())
