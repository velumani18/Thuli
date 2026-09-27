# Architectural Decision Records (ADRs) & Prompting Evaluation Index

**Problem 3: Analyst & Auditor — facTrack**  
*Curated Architectural Decisions & Prompting Directives Log*

---

## 📖 Evaluator's Guide: How to Read These Decision Records

The Thuli Studios Take-Home Assessment brief specifically states:
> *"The session logs tell us how you work. The write-up tells us how you think. The code tells us what you can build. We weigh all three... We are looking at how you direct the tool, where you caught it being wrong, and which decisions were yours. A place where the obvious approach was tried, measured, rejected with evidence, and replaced. Session logs where the candidate overrules the tool and is right to."*

Rather than requiring reviewers to sift through thousands of lines of raw IDE transcripts in [`/logs/ai_sessions/`](file:///c:/Users/Velumani/Desktop/Thuli/logs/ai_sessions/), this directory compiles **7 key architectural decision records (ADRs)** detailing:
1. The **initial naive approach** commonly proposed by AI tools.
2. The **exact point where the candidate caught the tool being wrong** and overruled it.
3. The **specific engineering directive and prompt** issued by the candidate.
4. The **trade-offs, implementation architecture, and measured evaluation**.

---

## 🗂️ Architectural Decision Records Index

| ADR ID | Decision Title | Component | Summary of Candidate Overrule |
| :--- | :--- | :--- | :--- |
| [**D001**](file:///c:/Users/Velumani/Desktop/Thuli/logs/decisions/D001_sqlite_vs_vector.md) | **SQLite Relational Memory & BM25 vs. Vector DB** | `app/memory/store.py` | Rejected expensive, non-deterministic vector embeddings; mandated local zero-cost SQLite with relational entity-fact tables and FTS5 BM25 search. Reduced token costs by 48% on follow-ups. |
| [**D002**](file:///c:/Users/Velumani/Desktop/Thuli/logs/decisions/D002_parallel_fetching.md) | **Adaptive Parallel Fetching & Early Stopping** | `app/tools/fetcher.py` | Overruled sequential loops and unbounded connection blasts; implemented per-domain throttling (max 2) and adaptive early stopping once 3 usable sources are retrieved. Fetch phase dropped to 4.1s. |
| [**D003**](file:///c:/Users/Velumani/Desktop/Thuli/logs/decisions/D003_auditor_independence.md) | **Zero-Trust Auditor Independence & Live Re-Fetching** | `app/agents/auditor.py` | Overruled shared-context confirmation bias; prohibited the Auditor from reading Analyst quotes or SQLite memory. The Auditor must re-fetch live URLs independently. |
| [**D004**](file:///c:/Users/Velumani/Desktop/Thuli/logs/decisions/D004_retry_policy.md) | **Exponential Backoff & Strict Non-Retry on 4xx** | `app/tools/fetcher.py` | Rejected blind retry decorators; enforced a strict two-tier policy: fail-fast with zero retries on 401/403/404/410, exponential backoff with jitter on 429/503, respecting `Retry-After` headers. |
| [**D005**](file:///c:/Users/Velumani/Desktop/Thuli/logs/decisions/D005_two_minute_deadline.md) | **120-Second Hard Ceiling & Concurrency Budgeting** | `app/orchestrator.py` | Overruled a blunt 120s wrapper; engineered sub-phase latency budgets, parallel claim auditing (`asyncio.gather`), and instant quota breaks. Slashed execution from 91s to 27.1s. |
| [**D006**](file:///c:/Users/Velumani/Desktop/Thuli/logs/decisions/D006_universal_scraping_and_table_extraction.md) | **Universal HTML Table Extraction & 5-Tier Search** | `app/tools/search.py`, `app/tools/fetcher.py` | Caught third-party DDGS flakiness and tabular data loss; built automatic HTML table-to-Markdown conversion, Schema.org JSON-LD extraction, and a 5-tier search stack with base64 Bing decoding. |
| [**D007**](file:///c:/Users/Velumani/Desktop/Thuli/logs/decisions/D007_detailed_synthesis_and_auditor_panels.md) | **Multi-Paragraph Synthesis & Multi-Panel Auditor Dossier** | `app/agents/analyst.py`, `app/ui.py` | Rejected brief 1-line summaries; mandated 4–6 paragraph synthesis (450–800 words), in-text website attributions, 4–6 sentence Auditor evaluations, and a 6-panel interactive UI dossier. |

---

---

## 🚫 Rejected Architectural Decisions (`/logs/rejected/`)

The assessment specifically rewards *"session logs where the candidate overrules the tool and is right to"*. Review the dedicated rejected decision records below:

| ID | Rejected Concept | Proposed In | Why Candidate Overruled It | Implemented Replacement |
| :--- | :--- | :--- | :--- | :--- |
| [**R001**](file:///c:/Users/Velumani/Desktop/Thuli/logs/rejected/R001_vector_database_for_memory.md) | **Vector DB (ChromaDB / Pinecone)** | Step 350 | Fails on pronoun resolution ("them"); semantic bleeding across entity facts; heavy C++ compilation dependencies; token & latency overhead. | [`D001: SQLite Relational Entity Store + FTS5 BM25`](file:///c:/Users/Velumani/Desktop/Thuli/logs/decisions/D001_sqlite_vs_vector.md) |
| [**R002**](file:///c:/Users/Velumani/Desktop/Thuli/logs/rejected/R002_multiple_llm_fanout_for_scraping.md) | **Multi-LLM Fan-Out (3 Providers)** | Step 768 | Conflates I/O network scraping with LLM reasoning; triples rate-limit failure surface; straggler latency violates 120s limit; breaks schema consistency. | [`D002: Async Parallel Fetcher`](file:///c:/Users/Velumani/Desktop/Thuli/logs/decisions/D002_parallel_fetching.md) + [`D005: 120s Budgeting`](file:///c:/Users/Velumani/Desktop/Thuli/logs/decisions/D005_two_minute_deadline.md) |

---

---

## ⚡ Candidate Overrules & Command Directives (`/logs/overrules/`)

To review the exact moments where the candidate overruled the AI tool, made independent engineering choices, and commanded what to build:
- 📖 [**Consolidated Master Chronicle**](file:///c:/Users/Velumani/Desktop/Thuli/logs/OVERRULES.md): Single-page readable log of all 9 overrules.
- 🗂️ [**Master Overrules Index**](file:///c:/Users/Velumani/Desktop/Thuli/logs/overrules/INDEX.md): Directory of records `O001` through `O009`.

---

## 🧪 Quick Verification Commands for Reviewers

```powershell
# 1. Run Complete Automated Test Suite (51 Unit Tests in < 3.0s)
.\.venv\Scripts\pytest.exe -v

# 2. Run the 8-Question Benchmark Suite (Evaluates memory transfer, cost reduction, adversarial checks)
.\.venv\Scripts\python.exe scripts/run_eval.py

# 3. Launch Interactive Streamlit Dashboard
.\.venv\Scripts\streamlit.exe run app/ui.py
```

---

## 📁 Repository Structure

```text
logs/
├── decisions/                                # Curated Architectural Decision Records (ADRs)
│   ├── INDEX.md                              # This file (Reviewer Guide)
│   ├── D001_sqlite_vs_vector.md              # SQLite Relational Memory vs. Vector Embeddings
│   ├── D002_parallel_fetching.md             # Adaptive Parallel Fetching & Early Stopping
│   ├── D003_auditor_independence.md          # Zero-Trust Auditor Independence
│   ├── D004_retry_policy.md                  # Exponential Backoff & Non-Retry on 4xx
│   ├── D005_two_minute_deadline.md           # 120-Second Ceiling & Concurrency Budgeting
│   ├── D006_universal_scraping_and_table_extraction.md # Universal Tables & 5-Tier Search
│   └── D007_detailed_synthesis_and_auditor_panels.md   # Multi-Paragraph & Multi-Panel UI
├── ai_sessions/                              # Complete interaction session transcripts (Markdown + JSONL)
└── runs/                                     # Per-question structured execution telemetry (JSON)
```
