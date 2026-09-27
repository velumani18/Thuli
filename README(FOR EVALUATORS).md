# 📩 Note to Readers & Evaluators

**Problem 3: Analyst & Auditor — facTrack**  
*Author: Candidate Submission for Thuli Studios Take-Home Assessment*

---

Welcome! This note provides a concise, high-impact guide for evaluators to study how I work, how I think, and how I directed the AI pair-programming tool during this assessment.

---

## 💬 A Transparent Note on Prompt Sizing & AI-Refined Prompts

When evaluating how I built facTrack, it may appear that a few of my prompts are oversized, highly structured, or artificial.

> **Yes, I agree that a few of my prompts were refined and extended with AI assistance.**

If the session logs are read completely, you can clearly see how I work alongside AI to build complex, production-grade systems. I firmly believe that AI models cannot understand real-world engineering environments or constraints on their own. Therefore, these kinds of deeply explained, structured prompts are absolutely necessary to direct the AI efficiently.

Throughout my journey building complex systems with AI pair-programming, I discovered that **ideas must be clearly, deeply, and comprehensively explained to the AI to build something truly valuable**:

1. **Short, Casual Prompts Produce Fragile Prototypes:** Vague prompts lead LLMs to choose the easiest, most generic shortcuts—such as adding unnecessary technologies, and superficial 1-sentence answers.
2. **Explicit Engineering Directives Prevent Hallucinations:** To build a robust research agent operating under strict constraints (such as the 120-second hard ceiling, zero-trust auditor independence, and deterministic SQLite relational memory), I had to articulate the exact schemas, state machines, and edge cases.
3. **Prompting as an Intentional Design Tool:** Refining and structuring my prompts was an active engineering strategy. It allowed me to command the AI with precision, eliminate ambiguity, catch flawed assumptions before code was written, and maintain high standards across all 51 automated tests.

---

## 🗂️ 1. How to Navigate the Project Log Files

Rather than forcing you to wade through unorganized transcripts, the project's interaction history has been structured into purposeful directories:

- **[`/logs/ai_sessions/`](file:///c:/Users/Velumani/Desktop/Thuli/logs/ai_sessions/) (Raw Provenance Transcripts):**
  Contains the complete, authentic session transcripts in both raw JSONL and readable Markdown formats. Every prompt I issued, agent response, tool call, and file edit is preserved here for 100% provenance and verification.

- **[`/logs/decisions/`](file:///c:/Users/Velumani/Desktop/Thuli/logs/decisions/INDEX.md) (Architectural Decision Records):**
  Compiles 7 formal ADRs ([`D001` to `D007`](file:///c:/Users/Velumani/Desktop/Thuli/logs/decisions/INDEX.md)) detailing the architectural decisions I made, the trade-offs evaluated, database schemas chosen, and the measured outcomes under the 120-second deadline.

- **[`/logs/rejected/`](file:///c:/Users/Velumani/Desktop/Thuli/logs/rejected/INDEX.md) (Rejected AI Proposals):**
  Documents where I critically analyzed and rejected AI-proposed solutions—such as local Vector Databases ([`R001`](file:///c:/Users/Velumani/Desktop/Thuli/logs/rejected/R001_vector_database_for_memory.md)) and Multi-LLM provider fan-out for scraping ([`R002`](file:///c:/Users/Velumani/Desktop/Thuli/logs/rejected/R002_multiple_llm_fanout_for_scraping.md))—complete with verbatim conversation logs and technical proofs of why they fail.

- **[`/logs/overrules/`](file:///c:/Users/Velumani/Desktop/Thuli/logs/overrules/INDEX.md) & [`/logs/OVERRULES.md`](file:///c:/Users/Velumani/Desktop/Thuli/logs/OVERRULES.md) (Candidate Command Directives):**
  A dedicated chronicle detailing **9 explicit instances where I caught the AI tool being wrong, made my own independent decisions, and commanded the LLM on what to build** ([`O001` to `O009`](file:///c:/Users/Velumani/Desktop/Thuli/logs/overrules/INDEX.md)).

- **[`/logs/sessions/`](file:///c:/Users/Velumani/Desktop/Thuli/logs/sessions/INDEX.md) (Curated Milestone Sessions):**
  Organizes the entire 1,767 interaction steps into 8 coherent engineering milestones ([`S01` to `S08`](file:///c:/Users/Velumani/Desktop/Thuli/logs/sessions/INDEX.md)), allowing you to evaluate my prompting progression and engineering discipline across distinct phases.

---

## 🛠️ 2. Key Weaknesses Explicitly Identified & How I Solved Them

During pair programming, I actively inspected system bottlenecks, rejected naive defaults, and engineered robust solutions:

- **Weakness 1: Scraping 1 Page is Too Fragile → Adaptive $K$-Page Fetcher (`D002`, `O004`):**
  - *Identified Flaw:* Scraping a single webpage is brittle. If that single page returns a Cloudflare bot-wall (`403`), is down (`404`), or lacks content, the entire research pipeline fails.
  - *My Solution:* I commanded an **adaptive parallel fetcher** that queries $K$ candidate URLs concurrently, enforces **per-domain concurrency semaphores (max 2)** to prevent bot triggers, and uses **adaptive early stopping** to halt immediately once 3 usable sources are secured (slashing fetch time to 2.8s–4.1s).

- **Weakness 2: Rate Limiting & Blind Retries → Two-Tier Exponential Backoff (`D004`, `O004`):**
  - *Identified Flaw:* Naive retry decorators waste 15–20 seconds retrying client errors that will never succeed on immediate retries (e.g., 401, 403, 404).
  - *My Solution:* I enforced a strict two-tier status code strategy: immediate **fail-fast with 0 retries on 4xx client errors**, and **exponential backoff with full jitter on 429 / 503 errors** while strictly respecting HTTP `Retry-After` headers.

- **Weakness 3: High Latency (>60s) → Tavily Raw Crawl & Instant Quota Break (`D005`, `O007`):**
  - *Identified Flaw:* Queries were taking >60 seconds. When I probed the execution telemetry, I discovered that `gemini-3.8-flash` free tier was hitting a 20 req/min quota limit, and the naive sleep loop was waiting 45 seconds per turn.
  - *My Solution:* I commanded an **instant quota break** on 429 exhaustion, added Tavily search with pre-crawled HTML (`include_raw_content=True`) for instant fallback, and switched to the high-throughput `gemini-flash-lite-latest` (1.07s latency). Total query execution dropped from **91.8s down to 27.13s** (a 4.4x safety margin beneath the 120s limit).

- **Weakness 4: Confirmation Bias in Multi-Agent Verification → Air-Gapped Zero-Trust Auditor (`D003`, `O003`):**
  - *Identified Flaw:* Passing the Analyst's internal text buffer and selected quotes to the Auditor creates severe confirmation bias—the Auditor rubber-stamps whatever the Analyst hallucinates.
  - *My Solution:* I strictly **air-gapped the Auditor**. The Auditor is forbidden from reading Analyst thoughts or SQLite memory. It receives only the synthesized claim statement and URL, independently re-fetches the live web page, and verifies claims using strict natural language inference. It successfully caught adversarial fabricated claims (such as Q8's fake $1.2B SoftBank round).

- **Weakness 5: Hidden Evidence in UI → Panel-Wise Dual Evidence Dossier (`D007`, `O008`):**
  - *Identified Flaw:* Default UI designs hid evidence inside nested expanders or presented plain text without clear attribution.
  - *My Solution:* In the Streamlit UI, I engineered an interactive **Auditor Evidence Dossier** featuring side-by-side panels for every claim:
    - **Panel 1 (Left):** Primary Web Evidence extracted directly from the live source.
    - **Panel 2 (Right):** Auditor Evaluation, detailed 4–6 sentence justification, and color-coded verification verdict (`SUPPORTED`, `UNSUPPORTED`, `CONTRADICTED`, `UNVERIFIABLE`).

---

## 🚀 Quick Verification Commands

```powershell
# 1. Run Automated Test Suite (51 Unit Tests in < 5s)
.\.venv\Scripts\pytest.exe -v

# 2. Run the 8-Question Benchmark Evaluation Suite
.\.venv\Scripts\python.exe scripts/run_eval.py

# 3. Launch Interactive Streamlit Research Terminal
.\.venv\Scripts\streamlit.exe run app/ui.py
```

---

## 🔗 Related Documentation
- 📖 [**Two-Page Architectural Write-Up (`DECISIONS.md`)**](file:///c:/Users/Velumani/Desktop/Thuli/DECISIONS.md)
- ⚡ [**Master Candidate Overrules Log (`logs/OVERRULES.md`)**](file:///c:/Users/Velumani/Desktop/Thuli/logs/OVERRULES.md)
- 📑 [**Architectural Decision Records (`logs/decisions/INDEX.md`)**](file:///c:/Users/Velumani/Desktop/Thuli/logs/decisions/INDEX.md)
- 🚫 [**Rejected Decisions Directory (`logs/rejected/INDEX.md`)**](file:///c:/Users/Velumani/Desktop/Thuli/logs/rejected/INDEX.md)
- 🗣️ [**Curated Milestone Sessions (`logs/sessions/INDEX.md`)**](file:///c:/Users/Velumani/Desktop/Thuli/logs/sessions/INDEX.md)
- 💻 [**Full Project README (`README.md`)**](file:///c:/Users/Velumani/Desktop/Thuli/README.md)
