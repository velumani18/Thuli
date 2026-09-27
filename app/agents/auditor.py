"""
Auditor Agent.

Independently checks Analyst claims with adversarial rigor:
1. Re-fetches the cited sources directly from the live web (does NOT trust Analyst-supplied quotes).
2. Categorizes each claim strictly as:
   - SUPPORTED: Source directly confirms and entails the claim.
   - CONTRADICTED: Source directly contradicts the claim (e.g. conflicting numbers, dates, names).
   - UNSUPPORTED: Source does not mention or confirm the claim.
   - NO_CITATION: Factual assertion lacks a cited source URL.
   - UNVERIFIABLE: Cited source could not be accessed (403, 404, timeout, empty SPA).
3. Provides explanations and independently extracted quotes to catch hallucinations.
4. Claim-level verification across all structured claims.
"""

import json
import asyncio
from typing import Optional, Any
from pydantic import BaseModel, Field

from app.core.config import settings
from app.core.llm import LLMClient
from app.core.telemetry import ClaimAuditRecord, ToolInvocationLog
from app.tools.fetcher import ResilientFetcher, FetchResult


class AuditorReport(BaseModel):
    audit_records: list[ClaimAuditRecord]
    summary_counts: dict[str, int] = Field(default_factory=dict)
    passed_all: bool = False
    tool_logs: list[ToolInvocationLog] = Field(default_factory=list)
    total_prompt_tokens: int = 0
    total_completion_tokens: int = 0
    cost_usd: float = 0.0
    cost_inr: float = 0.0


class AuditorAgent:
    def __init__(self, llm_client: Optional[LLMClient] = None):
        self.llm = llm_client or LLMClient()
        self.fetcher = ResilientFetcher()

    async def audit_answer(
        self,
        draft_answer: str,
        claims: Optional[list[Any]] = None,
        atomic_claims: Optional[list[Any]] = None,
    ) -> AuditorReport:
        tool_logs: list[ToolInvocationLog] = []
        total_p_tokens = 0
        total_c_tokens = 0

        # Normalize claims input (supports both claims and legacy atomic_claims kwarg)
        raw_items = claims if claims is not None else (atomic_claims or [])

        # 1. Normalize claims list
        normalized_claims: list[dict[str, Any]] = []
        for idx, item in enumerate(raw_items):
            if hasattr(item, "model_dump"):
                d = item.model_dump()
            elif isinstance(item, dict):
                d = dict(item)
            else:
                d = {"claim": str(item)}

            claim_id = d.get("claim_id") or f"C{idx+1}"
            claim_text = d.get("claim") or d.get("claim_text", "")
            
            # Extract cited url and quote from evidence list or direct keys
            url = d.get("url")
            quote = d.get("quote", "")
            evidence_list = d.get("evidence", [])
            if not url and evidence_list and isinstance(evidence_list, list):
                first_ev = evidence_list[0]
                if isinstance(first_ev, dict):
                    url = first_ev.get("source_url")
                    quote = first_ev.get("quote", "")
                elif hasattr(first_ev, "source_url"):
                    url = first_ev.source_url
                    quote = getattr(first_ev, "quote", "")

            normalized_claims.append(
                {
                    "claim_id": claim_id,
                    "claim": claim_text,
                    "url": url,
                    "analyst_evidence": quote,
                    "status": d.get("status", "VERIFIED"),
                }
            )

        # 2. Collect unique cited URLs and independently fetch them
        urls_to_fetch = list({c["url"] for c in normalized_claims if c.get("url") and c["url"].startswith("http")})
        sources_map: dict[str, FetchResult] = {}

        if urls_to_fetch:
            fetch_results = await self.fetcher.fetch_multiple(urls_to_fetch)
            for fr in fetch_results:
                tool_logs.append(
                    ToolInvocationLog(
                        tool_name="auditor_independent_fetch",
                        target=fr.url,
                        status="SUCCESS" if fr.is_usable else "FAILED",
                        status_code=fr.status_code,
                        duration_ms=fr.duration_ms,
                        error_message=fr.rejection_reason or fr.error_message,
                    )
                )
                sources_map[fr.url] = fr

        # 3. Adversarial claim-by-claim verification
        audit_records: list[ClaimAuditRecord] = []

        system_instruction = (
            "You are an adversarial fact-checking Auditor. Conduct an exhaustive, rigorous, "
            "and in-depth audit of the Analyst's claim against the independently fetched live source text.\n"
            "Rules:\n"
            "1. Do NOT trust the Analyst's provided quote; verify solely against the provided source text.\n"
            "2. You MUST provide an in-depth, multi-sentence audit evaluation of AT LEAST 4 TO 6 DETAILED SENTENCES. "
            "Never output a brief 1 or 2 line response. Your comprehensive evaluation must cover:\n"
            "   a) Textual Alignment: Step-by-step cross-examination between the claim assertion and the specific clauses, figures, or tables in the source text.\n"
            "   b) Precision Verification: Exact check of numerical figures, currencies (INR/USD), dates, percentages, and units.\n"
            "   c) Caveats & Context: Note whether the source specifies exclusions (e.g. excluding GST, making charges, market session) or limitations.\n"
            "   d) Definitive Verdict Justification: Comprehensive explanation justifying why the verdict is SUPPORTED, CONTRADICTED, or UNSUPPORTED.\n"
            "3. SUPPORTED: The source explicitly confirms and entails all factual elements of the claim.\n"
            "4. CONTRADICTED: The source contradicts numbers, dates, entities, or assertions in the claim.\n"
            "5. UNSUPPORTED: The source text does not mention or confirm this specific claim.\n"
            "Output JSON with keys: 'verdict', 'explanation', 'snippet_quote'."
        )

        async def _verify_single_claim(item: dict) -> tuple[ClaimAuditRecord, int, int]:
            claim_id = item["claim_id"]
            claim_text = item["claim"]
            cited_url = item.get("url")
            analyst_quote = item.get("analyst_evidence")

            # Case A: No citation provided
            if not cited_url:
                return (
                    ClaimAuditRecord(
                        claim_id=claim_id,
                        claim_text=claim_text,
                        cited_url=None,
                        analyst_evidence=analyst_quote,
                        analyst_extraction_status="NO_URL",
                        auditor_source_status=None,
                        auditor_evidence=None,
                        verdict="NO_CITATION",
                        auditor_explanation=(
                            "No citation or source URL was attached to this factual assertion. "
                            "Under facTrack's evidence-first adversarial verification protocol, any assertion lacking an explicit, "
                            "traceable web hyperlink cannot be cross-referenced or corroborated against live ground truth. "
                            "Consequently, this assertion is flagged as ungrounded and rejected from the verified answer baseline."
                        ),
                    ),
                    0,
                    0,
                )

            fr = sources_map.get(cited_url)

            # Case B: Source blocked, missing, timed out, or empty (UNVERIFIABLE)
            if not fr or not fr.is_usable:
                fail_status = fr.status if fr else "NOT_FETCHED"
                fail_reason = (fr.rejection_reason or fr.error_message) if fr else "Source unreachable"
                return (
                    ClaimAuditRecord(
                        claim_id=claim_id,
                        claim_text=claim_text,
                        cited_url=cited_url,
                        analyst_evidence=analyst_quote,
                        analyst_extraction_status="CLAIMED_BY_ANALYST",
                        auditor_source_status=fail_status,
                        auditor_evidence=None,
                        verdict="UNVERIFIABLE",
                        auditor_explanation=(
                            f"Cited source cannot be accessed or verified ({fail_status}: {fail_reason}). "
                            f"The Auditor attempted independent retrieval from {cited_url}, but the host server failed to respond with usable content. "
                            "Under facTrack's strict adversarial verification safety rules, assertions cannot be accepted without independent web proof."
                        ),
                    ),
                    0,
                    0,
                )

            # Case C: Source loaded successfully -> Compare claim with independently fetched text
            prompt = f"""Claim ID: {claim_id}
Claim Text: "{claim_text}"
Cited URL: {cited_url}

Independently Fetched Source Content:
{fr.extracted_text[:6000]}

Conduct an adversarial, rigorous audit of the claim strictly against the independently fetched source content.
You MUST provide an extensive, detailed audit evaluation of 4 to 6 full sentences. Do NOT provide a brief 1 or 2 line summary.
Structure your detailed audit evaluation covering:
1. Textual Alignment: Exactly which table, paragraph, or clause in the source content discusses this claim.
2. Numerical & Temporal Precision: Compare specific figures (e.g. ₹/gram, currencies, percentages, dates) against the source.
3. Caveats & Exclusions: Note whether the source mentions taxes (e.g. 3% GST), making charges, market session timing, or purity benchmarks.
4. Comparative Rigor: Note any conflicting statements, historical shifts, or updates mentioned.
5. Final Verdict Justification: Conclude with a rigorous justification of why the verdict is SUPPORTED, CONTRADICTED, or UNSUPPORTED.

Output JSON:
{{
  "verdict": "SUPPORTED" | "CONTRADICTED" | "UNSUPPORTED",
  "explanation": "Detailed 4-6 sentence audit evaluation rigorously covering all 5 points above.",
  "snippet_quote": "Direct verbatim excerpt or table row from the source confirming or contradicting the claim"
}}
"""

            resp = await self.llm.generate(prompt, system_instruction=system_instruction, json_mode=True)
            p_tok = resp.prompt_tokens
            c_tok = resp.completion_tokens

            try:
                data = json.loads(resp.content)
                verdict = data.get("verdict", "UNSUPPORTED")
                if verdict not in ("SUPPORTED", "CONTRADICTED", "UNSUPPORTED"):
                    verdict = "UNSUPPORTED"

                return (
                    ClaimAuditRecord(
                        claim_id=claim_id,
                        claim_text=claim_text,
                        cited_url=cited_url,
                        analyst_evidence=analyst_quote,
                        analyst_extraction_status="SUCCESS",
                        auditor_source_status="SUCCESS",
                        auditor_evidence=data.get("snippet_quote"),
                        verdict=verdict,
                        auditor_explanation=data.get("explanation", ""),
                        source_snippet_extracted=data.get("snippet_quote"),
                    ),
                    p_tok,
                    c_tok,
                )
            except Exception:
                return (
                    ClaimAuditRecord(
                        claim_id=claim_id,
                        claim_text=claim_text,
                        cited_url=cited_url,
                        analyst_evidence=analyst_quote,
                        analyst_extraction_status="SUCCESS",
                        auditor_source_status="SUCCESS",
                        auditor_evidence=None,
                        verdict="UNSUPPORTED",
                        auditor_explanation="Auditor model verification failed to parse output JSON.",
                    ),
                    p_tok,
                    c_tok,
                )

        # Run all claim audits concurrently for fast parallel performance
        parallel_results = await asyncio.gather(*[_verify_single_claim(item) for item in normalized_claims])
        for rec, p_tok, c_tok in parallel_results:
            audit_records.append(rec)
            total_p_tokens += p_tok
            total_c_tokens += c_tok

        # 4. Summarize counts
        counts = {
            "SUPPORTED": 0,
            "CONTRADICTED": 0,
            "UNSUPPORTED": 0,
            "UNVERIFIABLE": 0,
            "NO_CITATION": 0,
        }
        for rec in audit_records:
            counts[rec.verdict] = counts.get(rec.verdict, 0) + 1

        passed_all = (
            counts["CONTRADICTED"] == 0
            and counts["UNSUPPORTED"] == 0
            and counts["UNVERIFIABLE"] == 0
            and counts["NO_CITATION"] == 0
        )
        cost_usd, cost_inr = settings.calculate_cost(settings.llm_model, total_p_tokens, total_c_tokens)

        return AuditorReport(
            audit_records=audit_records,
            summary_counts=counts,
            passed_all=passed_all,
            tool_logs=tool_logs,
            total_prompt_tokens=total_p_tokens,
            total_completion_tokens=total_c_tokens,
            cost_usd=cost_usd,
            cost_inr=cost_inr,
        )
