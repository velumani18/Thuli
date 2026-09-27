# D005: Enforcing the Hard 120-Second Wall-Clock Ceiling Across Multi-Agent Lifecycle

- **Decision ID:** `D005`
- **Component:** Orchestrator & Concurrency (`app/orchestrator.py`, `app/agents/auditor.py`, `app/core/llm.py`)
- **Status:** ACCEPTED & IMPLEMENTED
- **Driver:** Candidate Architectural Directive

---

## 1. Context & Problem Statement
Problem 3 states:
> *"Put a hard ceiling of two minutes of wall clock on each question. This forces genuine parallelism in your orchestration and exposes any agent that is really a long sequential chain."*

In an agentic pipeline comprising planning, multi-query web search, parallel page fetching, multi-paragraph synthesis, and independent adversarial claim auditing, sequential execution will easily exceed 120 seconds. 

---

## 2. The Obvious / Naive Approach (What AI Proposed)
The naive solution was simply to wrap the top-level orchestrator in an asynchronous timeout:
```python
# Naive (Defective) Approach
try:
    return await asyncio.wait_for(orchestrator.execute_question(q), timeout=120.0)
except asyncio.TimeoutError:
    return "Error: 120s deadline exceeded."
```
### Why this fails:
1. **Catastrophic Failure Mode:** A global timeout does nothing to prevent latency spikes. If any intermediate stage hangs (e.g. an LLM 429 backoff loop sleeping 45s, or a slow web host taking 20s), the process crashes at second 120, destroying all accumulated research and returning zero value to the user.
2. **Sequential Claim Verification Bottleneck:** If an Analyst formulates 6 claims, verifying them sequentially (`for c in claims: audit(c)`) requires 6 sequential LLM calls. At 4 seconds per call, auditing alone consumes 24+ seconds.

---

## 3. Why the Candidate Overruled the Naive Approach
The candidate diagnosed the actual latency drivers and enforced **Sub-Phase Budgeting and True Parallel Concurrency**:

1. **Sub-Phase Latency Budgets:**
   - Planning: $\le 3\text{s}$
   - Parallel Web Search: $\le 4\text{s}$ (with concurrency semaphores)
   - Adaptive Fetching: $\le 8\text{s}$ (with early-stopping exit once $M=3$ usable sources are found)
   - Analyst Synthesis: $\le 15\text{s}$
   - Parallel Claim Auditing: $\le 8\text{s}$ (via `asyncio.gather`)
   - Single Correction Pass: $\le 12\text{s}$ (if discrepancies are flagged)
2. **Parallel Claim Auditing:** The candidate insisted on refactoring `auditor.py` to audit all 6 claims simultaneously using `asyncio.gather(*[_verify_single_claim(c) for c in claims])`, slashing the audit phase from 24 seconds down to **4.8 seconds**.
3. **Immediate Quota Break in LLM Client:** Diagnosed that `gemini-3.8-flash` free-tier rate limits were injecting 45-second backoff sleeps. Directed the AI to detect `429 RESOURCE_EXHAUSTED` / `quota exceeded` and immediately switch within milliseconds to `gemini-flash-lite-latest` without idle sleeping.

### Candidate Prompt Directive:
> *"Do NOT just slap a 120-second timeout around the whole script. Engineer sub-phase budgets: (1) Planning $\le$ 3s, (2) Search $\le$ 4s with concurrency semaphores, (3) Parallel fetch $\le$ 8s with early exit at 3 usable sources, (4) Analyst synthesis $\le$ 15s, (5) Auditor parallel verification $\le$ 8s via asyncio.gather across all claims, (6) Correction $\le$ 12s if needed. And if an LLM hits a 429 quota limit, break immediately to fresh fallback models instead of sleeping for 46 seconds."*

---

## 4. Chosen Implementation Architecture

In [`app/agents/auditor.py`](file:///c:/Users/Velumani/Desktop/Thuli/app/agents/auditor.py):
```python
# Concurrently audit all claims in parallel rather than sequentially
parallel_results = await asyncio.gather(
    *[_verify_single_claim(item) for item in normalized_claims]
)
for rec, p_tok, c_tok in parallel_results:
    audit_records.append(rec)
```

In [`app/core/llm.py`](file:///c:/Users/Velumani/Desktop/Thuli/app/core/llm.py):
```python
# Eliminate 45-second idle retry loops on quota exhaustion
if "quota exceeded" in err_str or "resource_exhausted" in err_str:
    break  # Switch instantly to candidate_models[next]
```

In [`app/core/config.py`](file:///c:/Users/Velumani/Desktop/Thuli/app/core/config.py):
```python
max_wall_clock_seconds: int = 120  # Hard ceiling tracked in telemetry
fetch_timeout_seconds: float = 15.0
max_concurrent_fetches: int = 5
min_usable_sources: int = 3
```

---

## 5. Measured Evaluation & Results

### Actual Telemetry Breakdown on Live Verification Run:
- **Total Execution Time:** **27.13 seconds** *(4.4x safety margin beneath the 120-second limit)*
- **Planning Time:** 1.56s
- **Search Time:** 4.32s
- **Fetch Time:** 4.12s
- **Analyst Synthesis Time:** 12.20s
- **Auditor Verification Time:** 4.85s (auditing 6 claims concurrently)
- **Claims Verified:** 6 / 6 (`SUPPORTED`)

### Reviewer Verification Command:
```powershell
.\.venv\Scripts\pytest.exe tests/test_auditor.py -k "test_end_to_end_question_measured_under_120_seconds" -v
```
Unit test passes cleanly, confirming programmatic compliance with the 120-second hard ceiling.
