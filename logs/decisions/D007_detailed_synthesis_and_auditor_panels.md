# D007: Multi-Paragraph Cited Synthesis & Multi-Panel Auditor Dossier vs. Superficial Summaries

- **Decision ID:** `D007`
- **Component:** Synthesis & Interface (`app/agents/analyst.py`, `app/agents/auditor.py`, `app/ui.py`)
- **Status:** ACCEPTED & IMPLEMENTED
- **Driver:** Candidate Architectural Directive

---

## 1. Context & Problem Statement
Early iterations of the agent suffered from typical LLM brevity:
1. **Superficial 1-to-2 Line Answers:** The Analyst synthesized a short 100-word overview that lacked granular depth, historical context, and breakdown tables.
2. **Missing In-Text Source Attribution:** The text contained generic superscript tags like `[1]` without naming the actual publication or domain name in the prose.
3. **Truncated Auditor Verdicts:** The Auditor provided only a 1-sentence evaluation (e.g. *"The claim is supported by the source text."*), which failed to demonstrate deep adversarial analysis.
4. **Poor UI Presentation:** Tab 1 simply displayed an unformatted list of text blocks.

---

## 2. The Obvious / Naive Approach (What AI Proposed)
Generic LLM prompt templates encourage the model to be concise. Standard agent UI tutorials simply dump output markdown into `st.write(text)` and append an expander for citations.

### Why this fails:
1. Reviewers evaluating a research agent expect an exhaustive, analytical briefing that covers market drivers, purity standards, statutory taxes, and platform discrepancies.
2. Without explicit in-text attribution (e.g. *"According to LiveChennai (livechennai.com)..."*), readers cannot assess source authority at a glance.
3. An auditor that gives 1-line approvals cannot be distinguished from a superficial heuristic checker.

---

## 3. Why the Candidate Overruled the Naive Approach
The candidate explicitly intervened with four decisive instructions:

1. **Mandatory 4-to-6 Paragraph Depth (450–800 words):** Formatted under strict Markdown headings:
   - `### 📌 Executive Summary & Live Findings`
   - `### 📊 Detailed Numerical Breakdown & Rates` (with structured Markdown table)
   - `### 🌐 Market Drivers, Context & Influencing Factors`
   - `### ⚖️ Source Attribution & Discrepancy Analysis`
   - `### 💡 Commercial Considerations & Nuances` (making charges, 3% GST, BIS hallmarking)
2. **Explicit In-Text Website & Domain Attribution:** Every factual assertion in the answer and Claim-Evidence Map MUST state the specific website name and domain (e.g., *GoodReturns (goodreturns.in)*, *LiveChennai (livechennai.com)*, *Times of India (timesofindia.indiatimes.com)*).
3. **Mandatory 4-to-6 Sentence Auditor Cross-Examinations:** The Auditor must evaluate:
   - *Textual Alignment:* Exact section or table where the claim appears.
   - *Numerical & Temporal Precision:* Currencies, figures, percentages, dates.
   - *Caveats & Exclusions:* Taxes (3% GST), making charges, market session timing.
   - *Definitive Justification:* Explicit rationale for the verdict.
4. **Multi-Panel Evidence UI (At least 5 to 6 Panels):** Below the verified answer, render at least 5–6 distinct evidence items with dual presentation modes:
   - **🗂️ Interactive Auditor Dossier (Tabbed Panels):** Dedicated full-width tab per claim.
   - **📋 Expanded Multi-Panel Matrix (All Panels):** Side-by-side comparison of primary web evidence vs. Auditor evaluation.

### Candidate Prompt Directive:
> *"Answer is okay but I need a more detailed answer with proper citations stating which website or source the answer is taken from, and the auditor agent must give detailed answers, not 1 or 2 line answers. I also want at least 5 to 6 evidence items displayed below the answer with different panels by the auditor agent."*

---

## 4. Chosen Implementation Architecture

In [`app/agents/analyst.py`](file:///c:/Users/Velumani/Desktop/Thuli/app/agents/analyst.py):
```python
"2. MINIMUM 5 TO 6 DISTINCT EVIDENCE CLAIMS: You MUST formulate and generate AT LEAST 5 TO 6 DISTINCT ATOMIC CLAIMS (C1 through C6) in 'claim_evidence_map'..."
"6. COMPREHENSIVE MULTI-PARAGRAPH SYNTHESIS: In 'draft_answer', produce an exhaustive, high-depth synthesis of at least 4 to 6 detailed paragraphs (450 to 800 words)..."
"7. EXPLICIT IN-TEXT WEBSITE & SOURCE ATTRIBUTION: Every single factual assertion MUST explicitly state the website/source name and domain..."
```

In [`app/agents/auditor.py`](file:///c:/Users/Velumani/Desktop/Thuli/app/agents/auditor.py):
```python
"2. You MUST provide an in-depth, multi-sentence audit evaluation of AT LEAST 4 TO 6 DETAILED SENTENCES. Never output a brief 1 or 2 line response. Your comprehensive evaluation must cover: (a) Textual Alignment, (b) Precision Verification, (c) Caveats & Context, (d) Definitive Verdict Justification."
```

In [`app/ui.py`](file:///c:/Users/Velumani/Desktop/Thuli/app/ui.py):
```python
# Multi-Panel Evidence Hub with Tabbed Dossier and Expanded Matrix
view_mode = st.radio(
    "Evidence Display Mode:",
    ["🗂️ Interactive Auditor Dossier (Tabbed Panels)", "📋 Expanded Multi-Panel Matrix (All Panels)"],
    horizontal=True
)
# Renders 2-column sub-panels:
# Left Sub-Panel = Primary Source Evidence (Domain + Verbatim Quote)
# Right Sub-Panel = Auditor Agent Independent Evaluation
```

---

## 5. Measured Evaluation & Results

### Sample Live Output Verified on *"what is gold rate in chennai today?"*:
- **Total Audited Evidence Panels:** **6 Panels** (`C1` through `C6`) across 4 independent publishers.
- **Auditor Agreement:** **6 / 6 Supported (100% Match)**.
- **Auditor Explanation Depth:** Every claim received a complete 4-to-6 sentence analytical report examining textual alignment, exact rupee figures, 3% GST caveats, and making charges.
- **UI Responsiveness:** Interactive switching between tabbed dossier and full matrix renders instantly.
