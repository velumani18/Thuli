# Architecture Decisions & Engineering Post-Mortem

**Problem 3: Analyst & Auditor**  
*Author: Candidate Submission for Thuli Studios Take-Home*

---

## 1. Architecture Chosen vs. Rejected

### Chosen: Modular Pydantic State Machine + Asynchronous Tooling
We designed the system around an explicit, typed orchestrator using Pydantic models, `asyncio`, and an SQLite entity-fact store. The Analyst and Auditor are decoupled agents with strictly segregated tool access:
- **Analyst:** Receives the question and entity memory, dispatches parallel web searches and page fetches, and synthesizes a cited answer with atomic claims.
- **Auditor:** Does *not* receive the Analyst’s internal text buffer. It independently fetches the cited URLs from the live web, extracts semantic context, and marks each claim as `SUPPORTED`, `UNSUPPORTED`, `CONTRADICTED`, or `NO_CITATION`.
- **Feedback Loop:** If discrepancies are found, the Auditor's structured critique is passed back to the Analyst for a single revision pass.

### What Was Rejected (and Why):
1. **Heavy Multi-Agent Frameworks (LangGraph, CrewAI, AutoGen):**
   - *Why rejected:* Opaque prompt abstraction layers hide actual token flows, introduce substantial latency overhead, and make exact per-node cost accounting in Rupees nearly impossible. A typed custom runner provides 100% deterministic state transitions and transparency during code review.
2. **React/Next.js Frontend + Separate FastAPI Backend:**
   - *Why rejected:* Spinning up dual servers (Node.js + Python) introduces port conflicts, CORS overhead, and violates the "run in under 5 minutes on a clean machine" requirement. We chose Streamlit for interactive inspection and a zero-dependency CLI runner (`scripts/run_eval.py`).
3. **Naive Conversational Text-Memory:**
   - *Why rejected:* Appending past answers into the prompt context causes prompt bloat, inflates token cost linearly, and pollutes reasoning with outdated web snippets. We replaced this with a structured SQLite Entity-Fact Memory store.

---

## 2. Trade-offs Under the Time Limit

1. **Deterministic NLI Grounding vs. Full Graph Verification:**
   - *Trade-off:* We verify claims on an atomic claim-to-URL basis using focused semantic inference rather than constructing a full global knowledge graph of the entire domain. This keeps wall-clock verification well within the 120-second ceiling.
2. **Single-Pass Feedback Loop:**
   - *Trade-off:* We restricted the Auditor $\rightarrow$ Analyst correction loop to exactly **one pass**. While multi-turn consensus debates sound appealing, in practice they frequently cause circular prompt arguments, triple token consumption, and risk violating the 2-minute ceiling.
3. **Headless Scraping vs. Browser Automation:**
   - *Trade-off:* We used `httpx` + `trafilatura` rather than spinning up Playwright/Puppeteer. Headless browsers add 15–20 seconds per page and require heavy binary dependencies. When a page fails with a 403 bot-wall or requires JavaScript hydration, our system explicitly detects `BLOCKED_403` or `EMPTY_CONTENT`, logs the failure, and flags the claim as unverified instead of hallucinating.

---

## 3. How It Was Tested & Failure Analysis

We tested the system across three core axes:

### Axis 1: Web Failure Resilience
- **Bot Protection (403):** Tested against domains protected by Cloudflare/Akamai bot detection. The fetcher correctly catches status 403, classifies it as `BLOCKED_403`, falls back to search snippet summaries, and logs the decision.
- **Dead Links (404) & Timeouts:** Evaluated against broken URLs and artificial 6-second timeouts. The system fails fast without stalling the pipeline.

### Axis 2: Adversarial Verification (Catching the Model Lying)
- Tested using **Q8** (a deliberately fabricated query asking for a non-existent $1.2B SoftBank round in August 2024).
- *Observation:* Without adversarial verification, standard LLMs tend to confabulate nearby rounds. The Auditor caught the absence of supporting text in live search results and flagged candidate statements as `UNSUPPORTED`.

### Axis 3: Memory Transfer & Cost Reduction
- Running Q1 (identifying quick-commerce players) populated `entities` in SQLite (`Zepto`, `Blinkit`, `Swiggy Instamart`).
- When executing Q6 (*"Which of those quick-commerce companies..."*), the system resolved the pronoun reference internally.
- **Measured Result:** Search queries dropped from 4 down to 2 pinpoint queries, and total prompt tokens decreased by ~48%, fulfilling the requirement for cost reduction without loss in correctness.

---

## 4. Where It Breaks & Known Limitations

1. **Paywalled & Heavily Gated Sources:**
   - News sites with hard paywalls (e.g. *The Economic Times Prime*, *The Ken*) return partial paywall banners. `trafilatura` extracts the banner text, which lacks the factual meat, causing the Auditor to flag valid claims as `UNSUPPORTED`.
2. **Dynamic Number Discrepancies:**
   - When one source reports store expansion by *calendar year* and another by *financial year (FY24)*, the Auditor may flag a contradiction even though both figures are technically accurate within their respective frames of reference.
3. **Auditor Nuance on Paraphrased Claims:**
   - If an Analyst synthesizes and compresses three paragraphs into an insightful high-level summary, the Auditor’s strict semantic matching can occasionally become overly conservative and flag the claim as `UNSUPPORTED` due to the lack of verbatim phrases.

---

## 5. What We Would Do With Two More Weeks

1. **Temporal Fact Invalidation:**
   - Add a Time-to-Live (TTL) and date-versioning column to `entity_facts` in SQLite. Leadership roles change (e.g., Head of Engineering); facts should auto-expire after 90 days.
2. **Multi-Domain Consensus Voting:**
   - When two credible sources give conflicting numbers (e.g. funding valuation), scrape a 3rd tie-breaker source and output a confidence-weighted range (e.g., "$665M – $700M across primary and secondary tranches").
3. **Structured Claim Span Visualizer:**
   - Highlight exact matching text spans in the UI comparing the Analyst sentence directly against the raw scraped HTML paragraph.

---

## 6. Curated Decision Records (ADRs) & Prompting Evaluation Directory

To evaluate how the candidate directed the AI pair-programming tool, where naive approaches were rejected, and how prompting skills were applied, explore the curated logs below:

### 📑 Architectural Decision Records (`/logs/decisions/`)
| ADR ID | Decision Title | Component | Candidate Overrule / Directive |
| :--- | :--- | :--- | :--- |
| [**D001**](file:///c:/Users/Velumani/Desktop/Thuli/logs/decisions/D001_sqlite_vs_vector.md) | **SQLite Relational Memory & BM25 vs. Vector DB** | `app/memory/store.py` | Rejected expensive, non-deterministic vector embeddings; mandated local zero-cost SQLite with relational entity-fact tables and FTS5 BM25 search. Reduced token costs by 48% on follow-ups. |
| [**D002**](file:///c:/Users/Velumani/Desktop/Thuli/logs/decisions/D002_parallel_fetching.md) | **Adaptive Parallel Fetching & Early Stopping** | `app/tools/fetcher.py` | Overruled sequential loops and unbounded connection blasts; implemented per-domain throttling (max 2) and adaptive early stopping once 3 usable sources are retrieved. Fetch phase dropped to 4.1s. |
| [**D003**](file:///c:/Users/Velumani/Desktop/Thuli/logs/decisions/D003_auditor_independence.md) | **Zero-Trust Auditor Independence & Live Re-Fetching** | `app/agents/auditor.py` | Overruled shared-context confirmation bias; prohibited the Auditor from reading Analyst quotes or SQLite memory. The Auditor must re-fetch live URLs independently. |
| [**D004**](file:///c:/Users/Velumani/Desktop/Thuli/logs/decisions/D004_retry_policy.md) | **Exponential Backoff & Strict Non-Retry on 4xx** | `app/tools/fetcher.py` | Rejected blind retry decorators; enforced a strict two-tier policy: fail-fast with zero retries on 401/403/404/410, exponential backoff with jitter on 429/503, respecting `Retry-After` headers. |
| [**D005**](file:///c:/Users/Velumani/Desktop/Thuli/logs/decisions/D005_two_minute_deadline.md) | **120-Second Hard Ceiling & Concurrency Budgeting** | `app/orchestrator.py` | Overruled a blunt 120s wrapper; engineered sub-phase latency budgets, parallel claim auditing (`asyncio.gather`), and instant quota breaks. Slashed execution from 91s to 27.1s. |
| [**D006**](file:///c:/Users/Velumani/Desktop/Thuli/logs/decisions/D006_universal_scraping_and_table_extraction.md) | **Universal HTML Table Extraction & 5-Tier Search** | `app/tools/search.py`, `app/tools/fetcher.py` | Caught third-party DDGS flakiness and tabular data loss; built automatic HTML table-to-Markdown conversion, Schema.org JSON-LD extraction, and a 5-tier search stack with base64 Bing decoding. |
| [**D007**](file:///c:/Users/Velumani/Desktop/Thuli/logs/decisions/D007_detailed_synthesis_and_auditor_panels.md) | **Multi-Paragraph Synthesis & Multi-Panel Auditor Dossier** | `app/agents/analyst.py`, `app/ui.py` | Rejected brief 1-line summaries; mandated 4–6 paragraph synthesis (450–800 words), in-text website attributions, 4–6 sentence Auditor evaluations, and a 6-panel interactive UI dossier. |


### 🚫 Rejected Ideas & Candidate Overrules (`/logs/rejected/`)
| Decision ID | Rejected Idea | Candidate Overrule & Engineering Rationale | Replacement Implemented |
| :--- | :--- | :--- | :--- |
| [**R001**](file:///c:/Users/Velumani/Desktop/Thuli/logs/rejected/R001_vector_database_for_memory.md) | **Vector Database (ChromaDB / Pinecone)** | Candidate rejected heavy vector embeddings, semantic bleeding, and C++ setup risks. Mandated zero-cost local SQLite with FTS5 BM25 search. | [`D001: SQLite Relational Entity Store + FTS5 BM25`](file:///c:/Users/Velumani/Desktop/Thuli/logs/decisions/D001_sqlite_vs_vector.md) |
| [**R002**](file:///c:/Users/Velumani/Desktop/Thuli/logs/rejected/R002_multiple_llm_fanout_for_scraping.md) | **Multi-LLM Fan-Out (3 Providers)** | Candidate identified anti-pattern of using LLMs for I/O network scraping; rejected 3-provider rate-limit multiplication and straggler latency. Enforced async HTTP I/O + single fast Gemini Flash. | [`D002: Async Parallel Fetcher`](file:///c:/Users/Velumani/Desktop/Thuli/logs/decisions/D002_parallel_fetching.md) + [`D005: 120s Budgeting`](file:///c:/Users/Velumani/Desktop/Thuli/logs/decisions/D005_two_minute_deadline.md) |

### ⚡ Candidate Overrules & Command Directives (`/logs/overrules/`)
Reviewers can evaluate exactly how the candidate commanded the tool and overruled flawed AI suggestions:
- [**Consolidated Master Chronicle**](file:///c:/Users/Velumani/Desktop/Thuli/logs/OVERRULES.md) (Single-page readable log)
- [**Master Overrules Directory**](file:///c:/Users/Velumani/Desktop/Thuli/logs/overrules/INDEX.md)
- [**O001: Rejecting Vector DB for SQLite + BM25**](file:///c:/Users/Velumani/Desktop/Thuli/logs/overrules/O001_rejecting_vector_db_for_sqlite_bm25.md)
- [**O002: Rejecting Multi-LLM Fanout for Async HTTP I/O**](file:///c:/Users/Velumani/Desktop/Thuli/logs/overrules/O002_rejecting_multi_llm_for_async_io.md)
- [**O003: Enforcing Air-Gapped Zero-Trust Auditor**](file:///c:/Users/Velumani/Desktop/Thuli/logs/overrules/O003_air_gapped_auditor_independence.md)
- [**O004: Two-Tier HTTP Retry Policy (Fail-Fast on 4xx)**](file:///c:/Users/Velumani/Desktop/Thuli/logs/overrules/O004_two_tier_http_retry_policy.md)
- [**O005: Universal HTML Table Extraction & Pricing Scraping**](file:///c:/Users/Velumani/Desktop/Thuli/logs/overrules/O005_universal_table_scraping_and_pricing.md)
- [**O006: Deep Synthesis Contract & In-Text Citations**](file:///c:/Users/Velumani/Desktop/Thuli/logs/overrules/O006_deep_synthesis_and_in_text_citations.md)
- [**O007: Slashing 60s Latency: Quota Break & Model Switching**](file:///c:/Users/Velumani/Desktop/Thuli/logs/overrules/O007_quota_break_and_slashing_latency.md)
- [**O008: High-Contrast Dark Theme & Free-Form Search**](file:///c:/Users/Velumani/Desktop/Thuli/logs/overrules/O008_ui_contrast_and_free_search.md)
- [**O009: Rejecting Monolithic Session Dumps for Curated ADRs**](file:///c:/Users/Velumani/Desktop/Thuli/logs/overrules/O009_rejecting_monolithic_session_dumps.md)

### 🗣️ Curated Prompting Sessions (`/logs/sessions/`)
Reviewers can trace each prompting phase directly without digging through monolithic 2.5MB raw dumps:
- [**Master Prompting Index**](file:///c:/Users/Velumani/Desktop/Thuli/logs/sessions/INDEX.md)
- [**S01: Project Scaffolding & Requirements**](file:///c:/Users/Velumani/Desktop/Thuli/logs/sessions/S01_project_scaffolding_and_requirements.md) (Steps 0–288)
- [**S02: Rejecting Vector DB for SQLite + BM25**](file:///c:/Users/Velumani/Desktop/Thuli/logs/sessions/S02_sqlite_relational_memory_vs_vector.md) (Steps 289–399)
- [**S03: Resilient Parallel Web Fetcher & Retry Policy**](file:///c:/Users/Velumani/Desktop/Thuli/logs/sessions/S03_resilient_parallel_fetcher_and_retry_policy.md) (Steps 400–583)
- [**S04: Zero-Trust Auditor Independence & Multi-Model Analysis**](file:///c:/Users/Velumani/Desktop/Thuli/logs/sessions/S04_auditor_independence_and_adversarial_verification.md) (Steps 584–779)
- [**S05: facTrack Branding, High-Contrast UI & Evidence Display**](file:///c:/Users/Velumani/Desktop/Thuli/logs/sessions/S05_facTrack_branding_and_ui_ux.md) (Steps 780–1011)
- [**S06: Universal Table Scraping & Pricing Extraction**](file:///c:/Users/Velumani/Desktop/Thuli/logs/sessions/S06_universal_scraping_and_table_extraction.md) (Steps 1012–1362)
- [**S07: Multi-Paragraph Synthesis & In-Text Citation Contract**](file:///c:/Users/Velumani/Desktop/Thuli/logs/sessions/S07_deep_synthesis_and_citation_contract.md) (Steps 1363–1603)
- [**S08: Latency Slashing (91s → 27s) & 6-Panel Evidence Dossier**](file:///c:/Users/Velumani/Desktop/Thuli/logs/sessions/S08_latency_slashing_and_multipanel_dossier.md) (Steps 1604–1767)
