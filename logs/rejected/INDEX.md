# Rejected Architectural Decisions & Prompting Leadership Log

**Problem 3: Analyst & Auditor — facTrack**  
*Curated Directory of Architectural Ideas Overruled & Rejected by the Candidate*

---

## 🎯 Evaluator's Guide: Why This Directory Exists

Page 7 of the Thuli Studios Assessment Brief sets the core evaluation rubric:
> *"The session logs tell us how you work. The write-up tells us how you think. The code tells us what you can build. We weigh all three... We are looking at how you direct the tool, where you caught it being wrong, and which decisions were yours. A place where the obvious approach was tried, measured, rejected with evidence, and replaced. Session logs where the candidate overrules the tool and is right to."*

This directory explicitly documents the two major architectural concepts that were explored during the AI pair programming session, **where the candidate identified fatal engineering flaws, caught the AI tool proposing anti-patterns, and overruled them with rigorous systems principles**:

1. **[R001: Rejection of Vector Database (ChromaDB / Pinecone)](file:///c:/Users/Velumani/Desktop/Thuli/logs/rejected/R001_vector_database_for_memory.md)**
   - *Candidate Overrule:* Rejected heavy vector databases, embedding API costs, and semantic bleeding. Mandated local zero-cost SQLite Relational Entity Store with Native FTS5 BM25 Search.
   - *Impact:* Zero build dependencies, 100% clean-machine pass, deterministic pronoun resolution, and 48% token reduction on follow-up questions.

2. **[R002: Rejection of Multi-LLM Provider Fan-Out for Scraping](file:///c:/Users/Velumani/Desktop/Thuli/logs/rejected/R002_multiple_llm_fanout_for_scraping.md)**
   - *Candidate Overrule:* Rejected distributing candidate web pages across three different LLM providers (Gemini, OpenAI, Anthropic). Enforced separation of I/O network operations (`httpx` + `asyncio.gather`) from cognitive reasoning (single fast Gemini Flash model).
   - *Impact:* Eliminated triple failure surfaces, avoided straggler latency spikes, preserved schema consistency, and maintained transparent per-question INR cost accounting.

---

## 🗂️ Rejected Decisions Directory

| ID | Rejected Idea | Proposed By | Reason for Candidate Overrule | Implemented Replacement |
| :--- | :--- | :--- | :--- | :--- |
| [**R001**](file:///c:/Users/Velumani/Desktop/Thuli/logs/rejected/R001_vector_database_for_memory.md) | **Local Vector Database (ChromaDB)** for follow-up memory | AI Tool / Exploration | Fails on pronoun resolution ("them"); causes semantic bleeding across entity facts; requires C++ build tools on clean machines; adds token and latency overhead. | [`D001: SQLite Relational Entity Store + FTS5 BM25 Engine`](file:///c:/Users/Velumani/Desktop/Thuli/logs/decisions/D001_sqlite_vs_vector.md) |
| [**R002**](file:///c:/Users/Velumani/Desktop/Thuli/logs/rejected/R002_multiple_llm_fanout_for_scraping.md) | **Multi-LLM Fan-Out (3 Providers)** to process 6 pages | AI Tool / Exploration | Conflates I/O network fetching with cognitive reasoning; triples rate-limit failure surface; suffers straggler latency under 120s ceiling; creates disjointed output schemas. | [`D002: Async HTTP I/O Parallel Fetcher`](file:///c:/Users/Velumani/Desktop/Thuli/logs/decisions/D002_parallel_fetching.md) + [`D005: 120s Budgeting`](file:///c:/Users/Velumani/Desktop/Thuli/logs/decisions/D005_two_minute_deadline.md) |

---

## 🔗 Complete Documentation Map

- **Accepted Decisions (ADRs):** [`/logs/decisions/INDEX.md`](file:///c:/Users/Velumani/Desktop/Thuli/logs/decisions/INDEX.md)
- **Curated Prompting Sessions:** [`/logs/sessions/INDEX.md`](file:///c:/Users/Velumani/Desktop/Thuli/logs/sessions/INDEX.md)
- **Architectural Write-Up:** [`/DECISIONS.md`](file:///c:/Users/Velumani/Desktop/Thuli/DECISIONS.md)
- **Raw Transcripts Archive:** [`/logs/ai_sessions/`](file:///c:/Users/Velumani/Desktop/Thuli/logs/ai_sessions/)
