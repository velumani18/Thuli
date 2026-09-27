# Prompting Skills & Curated AI Session Log Index

**Problem 3: Analyst & Auditor ?? facTrack**  
*Curated Milestone Sessions for Prompting Skill & Architecture Evaluation*

---

## 🎯 Overview for Evaluators

Rather than dumping monolithic 2.5MB transcripts where reviewers must sift through thousands of lines of raw JSON, this directory organizes the pair programming trajectory into **8 clear engineering milestones** (`S01` to `S08`).

Each session record highlights the candidate's exact prompts, architectural directives, where the candidate caught the AI tool proposing naive patterns, and the measured engineering outcome.

### Evaluation Dimensions Highlighted:
1. **Directing the Tool:** Explicit architectural constraints, schema designs, and algorithmic boundaries.
2. **Overruling AI Hallucinations & Hype:** Rejecting external vector databases, refusing blind retry decorators, preventing confirmation bias in the Auditor.
3. **Root-Cause Performance Engineering:** Diagnosing 429 quota exhaustion and sub-phase latency bottlenecks, cutting wall-clock execution from 91.8s to 27.1s.
4. **User-Centric & Visual Excellence:** Converting raw data into an interactive 6-panel Auditor Evidence Dossier.

---

## 🗂️ Milestone Sessions Directory

| Session ID | Milestone Title | Step Range | Key Prompting Skills Evaluated | ADR Reference |
| :--- | :--- | :--- | :--- | :--- |
| [**S01**](file:///c:/Users/Velumani/Desktop/Thuli/logs/sessions/S01_project_scaffolding_and_requirements.md) | **Project Scaffolding, Architecture Requirements & Streamlit Stack Selection** | Steps 0-288 | Precise Requirements Breakdown against Assessment Rubric; Pragmatic Technology Selection (Streamlit vs React for <5 min Evaluator Setup) | [`None (Foundational Scaffolding)`](file:///c:/Users/Velumani/Desktop/Thuli/logs/decisions/) |
| [**S02**](file:///c:/Users/Velumani/Desktop/Thuli/logs/sessions/S02_sqlite_relational_memory_vs_vector.md) | **Rejecting Vector Database Complexity in Favor of Deterministic SQLite + BM25** | Steps 289-399 | Critical AI Overrule (Rejecting Vector DB Hype); Zero-Cost Architectural Constraint Specification | [`D001`](file:///c:/Users/Velumani/Desktop/Thuli/logs/decisions/) |
| [**S03**](file:///c:/Users/Velumani/Desktop/Thuli/logs/sessions/S03_resilient_parallel_fetcher_and_retry_policy.md) | **Resilient Parallel Web Fetching, Concurrency Semaphores & Strict Retry Policy** | Steps 400-583 | Hard Failure Mode Anticipation (Blocked Webpages); Two-Tier HTTP Status Code Policy Directives | [`D002`](file:///c:/Users/Velumani/Desktop/Thuli/logs/decisions/) |
| [**S04**](file:///c:/Users/Velumani/Desktop/Thuli/logs/sessions/S04_auditor_independence_and_adversarial_verification.md) | **Zero-Trust Auditor Independence & Multi-Model Architecture Analysis** | Steps 584-779 | Zero-Trust Adversarial Agent Design; Multi-Model Provider Trade-off Analysis (Gemini vs OpenAI vs Anthropic) | [`D003`](file:///c:/Users/Velumani/Desktop/Thuli/logs/decisions/) |
| [**S05**](file:///c:/Users/Velumani/Desktop/Thuli/logs/sessions/S05_facTrack_branding_and_ui_ux.md) | **facTrack Branding, High-Contrast Glassmorphic UI & Evidence Panel Accessibility** | Steps 780-1011 | Rapid Bug Diagnosis (Streamlit sys.path Bootstrapping); UI Readability & Contrast Engineering | [`D007`](file:///c:/Users/Velumani/Desktop/Thuli/logs/decisions/) |
| [**S06**](file:///c:/Users/Velumani/Desktop/Thuli/logs/sessions/S06_universal_scraping_and_table_extraction.md) | **Universal HTML Table Extraction, Schema.org JSON-LD & 5-Tier Search Stack** | Steps 1012-1362 | Generalization from Specific Edge Cases (Gold Rates & Pricing Tables); Deep HTML DOM Parsing Architecture Directives | [`D006`](file:///c:/Users/Velumani/Desktop/Thuli/logs/decisions/) |
| [**S07**](file:///c:/Users/Velumani/Desktop/Thuli/logs/sessions/S07_deep_synthesis_and_citation_contract.md) | **Multi-Paragraph Synthesis Contract, In-Text Citations & Rigorous Auditor Evaluations** | Steps 1363-1603 | Rejecting Superficial AI Output Quality; Contract-Driven Prompt Engineering (Exact Paragraph & Word Count Directives) | [`D007`](file:///c:/Users/Velumani/Desktop/Thuli/logs/decisions/) |
| [**S08**](file:///c:/Users/Velumani/Desktop/Thuli/logs/sessions/S08_latency_slashing_and_multipanel_dossier.md) | **Latency Root-Cause Diagnosis, Tavily Raw Crawl & 6-Panel Auditor Evidence Dossier** | Steps 1604-99999 | Telemetry & Root-Cause Latency Debugging (>60s Bottleneck Identification); API Quota Backoff vs. Model Switching Directive | [`D005`](file:///c:/Users/Velumani/Desktop/Thuli/logs/decisions/) |

---

## 🔗 Companion Resources

- **Architectural Decision Records (ADRs):** [`/logs/decisions/INDEX.md`](file:///c:/Users/Velumani/Desktop/Thuli/logs/decisions/INDEX.md)
- **Two-Page Architectural Write-Up:** [`/DECISIONS.md`](file:///c:/Users/Velumani/Desktop/Thuli/DECISIONS.md)
- **Raw Provenance Transcripts:** [`/logs/ai_sessions/`](file:///c:/Users/Velumani/Desktop/Thuli/logs/ai_sessions/)
- **Execution Telemetry Runs:** [`/logs/runs/`](file:///c:/Users/Velumani/Desktop/Thuli/logs/runs/)
