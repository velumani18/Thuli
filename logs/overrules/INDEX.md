# Candidate Overrules & Command Directives Log

**Problem 3: Analyst & Auditor — facTrack**  
*Comprehensive Chronicle of Where the Candidate Overruled the AI and Commanded the Architecture*

---

## 🎯 Reviewer's Guide: Prompting Leadership & Tool Governance

Page 7 of the Thuli Studios Take-Home Assessment brief specifically highlights:
> *'The session logs tell us how you work. The write-up tells us how you think. The code tells us what you can build. We weigh all three... We are looking at how you direct the tool, where you caught it being wrong, and which decisions were yours. A place where the obvious approach was tried, measured, rejected with evidence, and replaced. Session logs where the candidate overrules the tool and is right to.'*

This directory compiles **9 explicit instances** where the candidate rejected default, naive, or superficial proposals from the AI pair-programming tool, diagnosed the root engineering flaw, and commanded the exact architectural pattern to implement.

---

## 🗂️ Master Directory of Candidate Overrules

| ID | Overrule Title | Component | What Candidate Overruled | Key Prompt Command | Replacement Record |
| :--- | :--- | :--- | :--- | :--- | :--- |
| [**O001**](file:///c:/Users/Velumani/Desktop/Thuli/logs/overrules/O001_rejecting_vector_db_for_sqlite_bm25.md) | **Rejecting Vector Database Complexity in Favor of Deterministic SQLite + Native BM25** | `Memory` | Proposed integrating ChromaDB/FAISS vector embeddings with text chunki... | *"i dont want to complicate the system with loclal vector data..."* | [`D001 / R001`](file:///c:/Users/Velumani/Desktop/Thuli/logs/decisions/) |
| [**O002**](file:///c:/Users/Velumani/Desktop/Thuli/logs/overrules/O002_rejecting_multi_llm_for_async_io.md) | **Rejecting Multi-LLM Provider Fan-Out for Web Page Scraping** | `Concurrency` | Explored allocating 6 candidate URLs across 3 LLM providers (Gemini, O... | *"but what if rate limiting error occurs which differs and als..."* | [`D002 / R002`](file:///c:/Users/Velumani/Desktop/Thuli/logs/decisions/) |
| [**O003**](file:///c:/Users/Velumani/Desktop/Thuli/logs/overrules/O003_air_gapped_auditor_independence.md) | **Enforcing Zero-Trust Air-Gapped Auditor Independence** | `Auditor` | Shared the Analyst's internal text buffer, extracted snippets, and SQL... | *"i dont want to add any unwanted vector database or any archi..."* | [`D003`](file:///c:/Users/Velumani/Desktop/Thuli/logs/decisions/) |
| [**O004**](file:///c:/Users/Velumani/Desktop/Thuli/logs/overrules/O004_two_tier_http_retry_policy.md) | **Overruling Blind Retries: Enforcing Two-Tier Fail-Fast HTTP Retry Policy** | `HTTP` | Used generic retry decorators that retried 3 times with fixed delays o... | *"I want to work on the next important failure mode..."* | [`D004`](file:///c:/Users/Velumani/Desktop/Thuli/logs/decisions/) |
| [**O005**](file:///c:/Users/Velumani/Desktop/Thuli/logs/overrules/O005_universal_table_scraping_and_pricing.md) | **Overruling Plain-Text Extraction for Universal DOM Table Parsing** | `Web` | Relied solely on naive text scrapers that stripped HTML table tags, ca... | *"web scraping can be easily done to search for gold rate righ..."* | [`D006`](file:///c:/Users/Velumani/Desktop/Thuli/logs/decisions/) |
| [**O006**](file:///c:/Users/Velumani/Desktop/Thuli/logs/overrules/O006_deep_synthesis_and_in_text_citations.md) | **Rejecting Superficial AI Output: Enforcing Deep Synthesis & In-Text Citations** | `Analyst` | Generated terse 1-2 sentence answers with generic footnotes and 1-line... | *"answer is okay but i need more detailed answer and also i ne..."* | [`D007`](file:///c:/Users/Velumani/Desktop/Thuli/logs/decisions/) |
| [**O007**](file:///c:/Users/Velumani/Desktop/Thuli/logs/overrules/O007_quota_break_and_slashing_latency.md) | **Root-Cause Latency Debugging & Overruling 45s Quota Backoff Sleep** | `LLM` | Blamed search engine latency and blindly slept for 45s when Gemini 3.8... | *"why every query taking more that 60 seconds to execute is it..."* | [`D005`](file:///c:/Users/Velumani/Desktop/Thuli/logs/decisions/) |
| [**O008**](file:///c:/Users/Velumani/Desktop/Thuli/logs/overrules/O008_ui_contrast_and_free_search.md) | **Overruling Restrictive Topic Pills & Poor Contrast for Open Evidence UI** | `Streamlit` | Rendered low-contrast dark themes with illegible text and restricted u... | *"the ui shows some kindof error in front end, and also the fr..."* | [`D007`](file:///c:/Users/Velumani/Desktop/Thuli/logs/decisions/) |
| [**O009**](file:///c:/Users/Velumani/Desktop/Thuli/logs/overrules/O009_rejecting_monolithic_session_dumps.md) | **Overruling Monolithic Session Dumps: Mandating Curated, Named Decision Records** | `Session` | Dumped raw 2.5MB cumulative JSONL/Markdown files with opaque timestamp... | *"i want you to verify that all the discussions we have made a..."* | [`INDEX.md / DECISIONS.md`](file:///c:/Users/Velumani/Desktop/Thuli/logs/decisions/) |

---

## 🔗 Companion Evaluation Directories

- **Accepted Decisions (ADRs):** [`/logs/decisions/INDEX.md`](file:///c:/Users/Velumani/Desktop/Thuli/logs/decisions/INDEX.md)
- **Rejected Architectural Ideas:** [`/logs/rejected/INDEX.md`](file:///c:/Users/Velumani/Desktop/Thuli/logs/rejected/INDEX.md)
- **Curated Milestone Sessions:** [`/logs/sessions/INDEX.md`](file:///c:/Users/Velumani/Desktop/Thuli/logs/sessions/INDEX.md)
- **Architectural Write-Up:** [`/DECISIONS.md`](file:///c:/Users/Velumani/Desktop/Thuli/DECISIONS.md)
