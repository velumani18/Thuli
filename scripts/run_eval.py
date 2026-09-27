"""
Automated 8-Question Evaluation Runner for Thuli Studios Assessment.

Executes 8 curated questions of increasing difficulty, tracks memory hits,
measures latency against the 2-minute ceiling, and generates the
cost & token learning-curve table in USD and INR.
"""

import asyncio
import json
import time
from pathlib import Path

from app.orchestrator import ResearchOrchestrator
from app.core.config import settings

EVAL_QUESTIONS = [
    {
        "id": "Q1",
        "question": "Which quick-commerce companies currently operate in India, and what are their primary operating models?",
        "category": "quick_commerce",
        "notes": "Baseline entity discovery. Populates Zepto, Blinkit, Swiggy Instamart into memory.",
    },
    {
        "id": "Q2",
        "question": "List every funding round raised by Zepto since January 2024, including dates, round sizes, and lead investors.",
        "category": "quick_commerce",
        "notes": "Specific funding & date constraint cross-check.",
    },
    {
        "id": "Q3",
        "question": "Who is the current Chief Technology Officer or Head of Engineering at Blinkit, when did they take the role, and where did they work previously?",
        "category": "quick_commerce",
        "notes": "Personnel verification; checks corporate profiles & anti-scraping resilience.",
    },
    {
        "id": "Q4",
        "question": "Which Indian jewellery retailers opened the most physical stores between FY23 and FY24, and what is the reported store count for each?",
        "category": "jewellery_retail",
        "notes": "Disagreement resolution: compares Titan/Tanishq, Kalyan, and Malabar annual reports.",
    },
    {
        "id": "Q5",
        "question": "What was the acquisition valuation and date when Swiggy acquired LYNK Logistics?",
        "category": "quick_commerce",
        "notes": "Obscure corporate deal verification under potential paywalled news sources.",
    },
    {
        "id": "Q6",
        "question": "Which of those quick-commerce companies from earlier have recently piloted 10-minute electronics delivery, and what categories do they stock?",
        "category": "quick_commerce",
        "notes": "Entity memory transfer 1: Reuses entities from Q1/Q2, cutting broad search queries.",
    },
    {
        "id": "Q7",
        "question": "Compare the total capital raised by Zepto against the retail store expansion capex of Titan over the past two years.",
        "category": "cross_domain",
        "notes": "Entity memory transfer 2: Cross-synthesizes quick-commerce and jewellery retail memory.",
    },
    {
        "id": "Q8",
        "question": "Which Indian quick-commerce company raised a $1.2B funding round led by SoftBank in August 2024?",
        "category": "adversarial",
        "notes": "Adversarial negative trap: No such round occurred. Verifies epistemic refusal vs hallucination.",
    },
]


async def run_evaluation():
    orchestrator = ResearchOrchestrator()
    results = []

    print("\n" + "=" * 80)
    print("THULI STUDIOS TAKE-HOME — PROBLEM 3: ANALYST AND AUDITOR EVALUATION SUITE")
    print(f"Model: {settings.llm_model} | Concurrency ceiling: {settings.max_wall_clock_seconds}s")
    print("=" * 80 + "\n")

    for q in EVAL_QUESTIONS:
        qid = q["id"]
        q_text = q["question"]
        print(f"[{qid}] Executing: {q_text[:70]}...")
        t0 = time.time()

        try:
            record = await orchestrator.execute_question(q_text, category=q["category"])
            t_taken = time.time() - t0

            # Summarize audit findings
            audit_str = f"S:{record.audit_summary.get('SUPPORTED', 0)} | U:{record.audit_summary.get('UNSUPPORTED', 0)} | C:{record.audit_summary.get('CONTRADICTED', 0)}"

            results.append({
                "ID": qid,
                "Question": q_text[:40] + "...",
                "Memory Hit": "YES" if record.memory_hit else "NO",
                "Queries": len(record.search_queries),
                "Tools": len(record.tools_invoked),
                "Audit": audit_str,
                "Tokens": record.total_tokens,
                "Cost (INR)": f"Rs. {record.cost_inr:.3f}",
                "Time (s)": f"{record.execution_time_seconds:.1f}s",
            })

            print(f"    --> Done in {t_taken:.1f}s | Tokens: {record.total_tokens} | Cost: Rs. {record.cost_inr:.3f} | Memory Hit: {record.memory_hit}")
        except Exception as e:
            print(f"    [!] Error on {qid}: {str(e)}")

    print("\n" + "=" * 80)
    print("EVALUATION BENCHMARK SUMMARY TABLE")
    print("=" * 80)

    header = f"{'ID':<4} | {'Memory':<7} | {'Queries':<7} | {'Tools':<5} | {'Audit':<16} | {'Tokens':<7} | {'Cost (INR)':<11} | {'Time':<6}"
    print(header)
    print("-" * len(header))
    for r in results:
        print(f"{r['ID']:<4} | {r['Memory Hit']:<7} | {r['Queries']:<7} | {r['Tools']:<5} | {r['Audit']:<16} | {r['Tokens']:<7} | {r['Cost (INR)']:<11} | {r['Time']:<6}")
    print("=" * 80 + "\n")


if __name__ == "__main__":
    asyncio.run(run_evaluation())
