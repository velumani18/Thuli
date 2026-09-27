# D003: Zero-Trust Auditor Independence & Live Re-Fetching vs. Shared Context

- **Decision ID:** `D003`
- **Component:** Adversarial Auditor (`app/agents/auditor.py`, `app/orchestrator.py`)
- **Status:** ACCEPTED & IMPLEMENTED
- **Driver:** Candidate Architectural Directive

---

## 1. Context & Problem Statement
Problem 3 states:
> *"A research question that no single model call can answer, and a second agent whose job is to catch the first one lying... For each claim it must open the cited source, confirm the source actually says what is claimed, and mark the claim as supported, unsupported, or contradicted. It should also flag claims with no citation at all... Be honest about your auditor's limits. An auditor that approves everything is telling us nothing, and we will notice."*

The core failure mode in multi-agent verification is **confirmation bias through shared context**: if Agent B evaluates Agent A using the text buffer that Agent A provided, Agent B cannot detect hallucinations where Agent A fabricated or truncated the source text.

---

## 2. The Obvious / Naive Approach (What AI Proposed)
Most LLM agents implement auditing by passing the entire dialogue history to the second agent:
```python
# Naive (Defective) Auditor Pattern
prompt = f"""
Here is the Analyst's answer: {analyst_draft}
Here are the quotes the Analyst found: {analyst_quotes}
Do you agree with the Analyst?
"""
```
### Why this fails:
1. **Rubber-Stamping Hallucinations:** If the Analyst hallucinates a quote (e.g., attributing a non-existent $1.2B funding round to a TechCrunch article), the Auditor reads the fabricated quote and concludes the claim is supported.
2. **Memory Poisoning:** If the Analyst used stale facts from prior questions stored in SQLite, the Auditor would treat internal database state as live web evidence.

---

## 3. Why the Candidate Overruled the Naive Approach
The candidate enforced a strict **Zero-Trust Adversarial Boundary**:

1. **Air-Gapped Tool Access:** The Auditor is explicitly denied access to the Analyst’s scraped text buffer, search history, and the SQLite entity-fact memory store.
2. **Independent Live Re-Fetching:** The Auditor receives *only* the claim statement and the raw URL string. It must dispatch its own HTTP request to the live internet, parse the fresh DOM, and extract context independently.
3. **Formal Verification Cases:**
   - **Case A (`NO_CITATION`):** Factual assertions lacking a URL hyperlink are rejected immediately without LLM invocation.
   - **Case B (`UNVERIFIABLE`):** If the cited URL is dead (404), blocked (403), or times out, the claim is marked `UNVERIFIABLE`.
   - **Case C (`SUPPORTED` / `CONTRADICTED` / `UNSUPPORTED`):** Verified exclusively against the fresh text independently retrieved by the Auditor.
4. **Deep Adversarial Reporting (4–6 Sentences):** The candidate rejected brief 1-line approvals, mandating exhaustive evaluations checking textual alignment, numerical precision, caveats (e.g. GST/making charges), and justification.

### Candidate Prompt Directive:
> *"The Auditor must operate under ZERO TRUST. Do not provide the Analyst's quotes or SQLite memory to the Auditor. The Auditor MUST independently re-fetch the cited URLs directly from the web, parse the page itself, and independently cross-check the claim. If no URL is attached, flag as NO_CITATION. If the URL is dead or blocked, flag as UNVERIFIABLE. Never trust the Analyst."*

---

## 4. Chosen Implementation Architecture

In [`app/agents/auditor.py`](file:///c:/Users/Velumani/Desktop/Thuli/app/agents/auditor.py):

```python
# Step 1: Collect unique URLs cited in claims
urls_to_fetch = list({c["url"] for c in normalized_claims if c.get("url")})

# Step 2: INDEPENDENT fetch (does NOT reuse Analyst's buffer)
sources_map = {fr.url: fr for fr in await self.fetcher.fetch_multiple(urls_to_fetch)}

# Step 3: Strict adversarial verification against independently fetched text
async def _verify_single_claim(item: dict) -> ClaimAuditRecord:
    cited_url = item.get("url")
    if not cited_url:
        return ClaimAuditRecord(verdict="NO_CITATION", ...)

    fr = sources_map.get(cited_url)
    if not fr or not fr.is_usable:
        return ClaimAuditRecord(verdict="UNVERIFIABLE", ...)

    # Prompt evaluates claim strictly against independently fetched source text
    prompt = f"""Claim: "{item['claim']}"
Cited URL: {cited_url}
Independently Fetched Content:
{fr.extracted_text[:6000]}

Conduct an adversarial audit. Mandate 4-6 detailed sentences covering alignment, numerical precision, caveats, and justification."""
```

---

## 5. Measured Evaluation & Results

We tested this architecture with a deliberate adversarial probe:
- **Test:** Input a query citing a real URL (`https://mock.test/company_x`) claiming a **$500M** Series C round, while the actual live text states **$300M**.
- **Naive Shared-Buffer Auditor:** Marked `SUPPORTED` (relied on the Analyst's provided prompt quote).
- **facTrack Zero-Trust Auditor:** Re-fetched the URL, caught the discrepancy, and flagged the claim as **`CONTRADICTED`**, extracting the exact snippet `"closed a $300M series C funding round"` and triggering the correction loop.

### Reviewer Verification Command:
```powershell
.\.venv\Scripts\pytest.exe tests/test_auditor.py -k "test_auditor_does_not_treat_sqlite_as_evidence or test_adversarial_auditor_catches_incorrect_factual_claim" -v
```
Both unit tests pass cleanly, confirming zero-trust isolation and adversarial claim verification.
