"""
Analyst Agent.

Orchestrates multi-step open research:
1. Plans search strategy (utilizing EntityMemory to avoid redundant queries).
2. Executes parallel web search and resilient page fetching.
3. Constructs an internal Claim-Evidence Map where every factual claim is grounded in structured evidence.
4. Plainly marks claims without adequate evidence as UNVERIFIED.
5. Synthesizes an evidence-grounded answer with strict claim citations.
6. Executes a single correction pass when flagged by the Auditor.
"""

import json
import asyncio
from typing import Optional, Literal, Any
from pydantic import BaseModel, Field

from app.core.config import settings
from app.core.llm import LLMClient
from app.core.telemetry import ToolInvocationLog
from app.tools.search import SearchEngine
from app.tools.fetcher import ResilientFetcher, FetchResult, AdaptiveFetchReport


class EvidenceObject(BaseModel):
    claim_id: str
    source_url: str
    source_title: Optional[str] = None
    quote: str
    evidence_date: Optional[str] = None


class StructuredClaim(BaseModel):
    claim_id: str  # e.g. "C1", "C2"
    claim: str
    evidence: list[EvidenceObject] = Field(default_factory=list)
    status: Literal["VERIFIED", "UNVERIFIED"] = "VERIFIED"


class AnalystPlan(BaseModel):
    reasoning: str
    search_queries: list[str]
    identified_entities: list[str]


class AnalystOutput(BaseModel):
    draft_answer: str
    claim_evidence_map: list[StructuredClaim] = Field(default_factory=list)
    citations: list[dict[str, str]] = Field(default_factory=list)  # [{"id": "[1]", "url": "https://..."}]
    atomic_claims: list[dict[str, Any]] = Field(default_factory=list)  # Backward compat for Auditor & Telemetry
    unverified_gaps: list[str] = Field(default_factory=list)
    discovered_entities: list[dict[str, str]] = Field(default_factory=list)  # [{"name": "...", "category": "..."}]
    discovered_facts: list[dict[str, str]] = Field(default_factory=list)
    tool_logs: list[ToolInvocationLog] = Field(default_factory=list)
    total_prompt_tokens: int = 0
    total_completion_tokens: int = 0
    cost_usd: float = 0.0
    cost_inr: float = 0.0


class AnalystAgent:
    def __init__(self, llm_client: Optional[LLMClient] = None):
        self.llm = llm_client or LLMClient()
        self.search_engine = SearchEngine()
        self.fetcher = ResilientFetcher()

    async def plan_research(self, question: str, memory_context: dict) -> tuple[AnalystPlan, int, int]:
        system_instruction = (
            "You are the Research Analyst planning an investigation. "
            "Inspect the question and any existing memory context. "
            "Output JSON with keys: 'reasoning', 'search_queries' (2-4 targeted search strings), "
            "and 'identified_entities' (list of company or person names identified)."
        )

        prompt = f"""Question: {question}

Existing Memory Context:
{json.dumps(memory_context, indent=2)}

Generate a research plan. If the memory already contains the entities, do NOT search for who they are;
instead, generate pinpoint queries targeting the specific facts needed."""

        resp = await self.llm.generate(prompt, system_instruction=system_instruction, json_mode=True)
        try:
            data = json.loads(resp.content)
            raw_queries = data.get("search_queries", [question])
            if isinstance(raw_queries, list):
                if question not in raw_queries:
                    raw_queries.append(question)
            else:
                raw_queries = [question]
            plan = AnalystPlan(
                reasoning=data.get("reasoning", ""),
                search_queries=raw_queries,
                identified_entities=data.get("identified_entities", []),
            )
        except Exception:
            plan = AnalystPlan(
                reasoning="Fallback plan",
                search_queries=[question],
                identified_entities=[],
            )

        return plan, resp.prompt_tokens, resp.completion_tokens

    async def gather_evidence(
        self, queries: list[str]
    ) -> tuple[dict[str, FetchResult], list[ToolInvocationLog], AdaptiveFetchReport]:
        tool_logs: list[ToolInvocationLog] = []
        candidate_urls: list[str] = []
        seen_urls: set[str] = set()

        # 1. Dispatch searches with concurrency control (avoid socket congestion)
        search_sem = asyncio.Semaphore(2)

        async def _run_search_controlled(q: str):
            async with search_sem:
                await asyncio.sleep(0.05)
                return await self.search_engine.search(q, max_results=settings.max_search_results)

        search_tasks = [_run_search_controlled(q) for q in queries]
        search_results = await asyncio.gather(*search_tasks)

        raw_content_map: dict[str, tuple[str, str, str]] = {}
        for sr in search_results:
            tool_logs.append(
                ToolInvocationLog(
                    tool_name=f"search_{sr.engine}",
                    target=sr.query,
                    status="SUCCESS" if not sr.error else "FAILED",
                    duration_ms=sr.duration_ms,
                    error_message=sr.error,
                )
            )
            for item in sr.items:
                if item.url and item.url.startswith("http"):
                    if item.url not in seen_urls:
                        seen_urls.add(item.url)
                        candidate_urls.append(item.url)
                    if item.raw_content or item.snippet:
                        raw_content_map[item.url] = (item.raw_content or "", item.snippet or "", item.title or "")

        # Cap candidates to max_candidate_urls
        candidates_to_evaluate = candidate_urls[: settings.max_candidate_urls]

        # 2. Fetch candidates concurrently with adaptive stopping rule
        fetch_report = await self.fetcher.fetch_with_adaptive_stopping(
            candidates_to_evaluate,
            min_usable=settings.min_usable_sources,
            max_concurrency=settings.max_concurrent_fetches,
        )

        usable_evidence: dict[str, FetchResult] = {}
        from app.tools.fetcher import UniversalContentExtractor

        for fr in fetch_report.all_results:
            # If local fetch was blocked or timed out, but Tavily pre-crawled content is available:
            if not fr.is_usable and fr.url in raw_content_map:
                raw_c, snip, t = raw_content_map[fr.url]
                if raw_c and len(raw_c) > 200:
                    title, text, _ = UniversalContentExtractor.extract_content(
                        html_content=raw_c,
                        url=fr.url,
                        max_characters=settings.max_extracted_characters_per_page,
                    )
                    if text and len(text) > 100:
                        fr.extracted_text = text
                        fr.title = title or t or fr.title
                        fr.status = "SUCCESS"
                        fr.is_usable = True
                        fr.character_count = len(text)
                        fr.rejection_reason = None

            status_mapping = {
                "SUCCESS": "SUCCESS" if fr.is_usable else "FALLBACK_USED",
                "BLOCKED_403": "BLOCKED_403",
                "NOT_FOUND_404": "NOT_FOUND_404",
                "TIMEOUT": "TIMEOUT",
                "EMPTY_CONTENT": "FALLBACK_USED",
                "RATE_LIMITED_429": "FAILED",
                "SERVER_ERROR": "FAILED",
                "ERROR": "FAILED",
            }
            tool_logs.append(
                ToolInvocationLog(
                    tool_name="http_fetch",
                    target=fr.url,
                    status=status_mapping.get(fr.status, "FAILED"),
                    status_code=fr.status_code,
                    duration_ms=fr.duration_ms,
                    error_message=fr.rejection_reason or fr.error_message,
                    fallback_applied="Switched to next candidate source" if not fr.is_usable else None,
                )
            )
            if fr.is_usable:
                usable_evidence[fr.url] = fr

        return usable_evidence, tool_logs, fetch_report

    async def synthesize(
        self, question: str, plan: AnalystPlan, evidence: dict[str, FetchResult], memory_context: dict
    ) -> tuple[AnalystOutput, int, int]:
        system_instruction = (
            "You are a senior, rigorous Research Analyst. Construct an exhaustive, objective, fact-based answer strictly from live evidence.\n"
            "Rules:\n"
            "1. You MUST generate an internal Claim-Evidence Map before drafting the final answer.\n"
            "2. MINIMUM 5 TO 6 DISTINCT EVIDENCE CLAIMS: You MUST formulate and generate AT LEAST 5 TO 6 DISTINCT ATOMIC CLAIMS (e.g., C1, C2, C3, C4, C5, C6) in 'claim_evidence_map'. "
            "Do NOT stop at 3 or 4 claims. Break down different facets of the findings (e.g. primary figures/rates, historical variations, macroeconomic drivers, commercial taxes/fees like GST and making charges, regulatory/hallmarking standards, and platform comparisons) across separate claims C1 through C6.\n"
            "3. Each evidence object MUST have: 'source_url', 'source_title', 'quote' (exact verbatim excerpt from evidence), and 'evidence_date'.\n"
            "4. If a factual claim has no adequate evidence, mark it as 'status': 'UNVERIFIED' with empty evidence; "
            "do NOT present it as established fact. Place it into 'unverified_gaps'.\n"
            "5. If two sources disagree on numbers or dates, explicitly state the conflict in the answer.\n"
            "6. COMPREHENSIVE MULTI-PARAGRAPH SYNTHESIS: In 'draft_answer', produce an exhaustive, high-depth synthesis of at least 4 to 6 detailed paragraphs (450 to 800 words). "
            "Structure with clear Markdown headings:\n"
            "   - '### 📌 Executive Summary & Live Findings'\n"
            "   - '### 📊 Detailed Numerical Breakdown & Rates' (including a Markdown table with purity, rates per gram / 8g sovereign, dates)\n"
            "   - '### 🌐 Market Drivers, Context & Influencing Factors'\n"
            "   - '### ⚖️ Source Attribution & Discrepancy Analysis'\n"
            "   - '### 💡 Commercial Considerations & Nuances' (making charges, 3% GST, hallmarking)\n"
            "Do NOT write a short 1-line or 2-line summary. Short answers are strictly prohibited.\n"
            "7. EXPLICIT IN-TEXT WEBSITE & SOURCE ATTRIBUTION: Every single factual assertion MUST explicitly state the website/source name and domain where it was taken "
            "(e.g., 'According to live market tracking by GoodReturns (goodreturns.in) [C1]...', 'LiveChennai (livechennai.com) [C2] reports that...', 'Data from Groww (groww.in) [C3] indicates...'). "
            "In addition, each 'claim' statement in 'claim_evidence_map' MUST also explicitly incorporate the source publication name.\n"
            "8. Output valid JSON matching the required schema."
        )

        # Strict Evidence-First Guard: If no usable evidence sources exist, do NOT hallucinate ungrounded claims
        usable_sources = [res for res in evidence.values() if res.is_usable]
        if not usable_sources:
            return (
                AnalystOutput(
                    draft_answer=(
                        f"### ⚠️ No Verifiable Primary Sources Found\n\n"
                        f"facTrack operates under a strict **evidence-first verification policy**. For the research query:\n\n"
                        f"> **\"{question}\"**\n\n"
                        f"No live primary web sources or verifiable citations could be successfully retrieved at this time. "
                        f"To maintain complete factual integrity and avoid hallucination, facTrack does not synthesize unverified statements without live source citations.\n\n"
                        f"**Recommendation:** Please refine your search terms or verify that primary web sources are reachable."
                    ),
                    claim_evidence_map=[],
                    citations=[],
                    unverified_gaps=[f"No primary live sources found with proper citations for: '{question}'"],
                    discovered_entities=[],
                    discovered_facts=[],
                ),
                0,
                0,
            )

        # Prepare evidence snippets with deep context (up to 7000 chars per source)
        evidence_text = ""
        for url, res in evidence.items():
            if res.status == "SUCCESS":
                title_line = f"Title: {res.title}\n" if res.title else ""
                snippet = res.extracted_text[:7000]
                evidence_text += f"\n--- SOURCE: {url} ---\n{title_line}{snippet}\n"
            else:
                evidence_text += f"\n--- SOURCE [FAILED: {res.status}]: {url} ---\nError: {res.error_message}\n"

        prompt = f"""Research Question: {question}

Research Plan:
{plan.reasoning}

Prior Memory Context:
{json.dumps(memory_context, indent=2)}

Gathered Evidence:
{evidence_text}

Output JSON with EXACTLY this structure:
{{
  "draft_answer": "Exhaustive 4-6 paragraph markdown synthesis (450-800 words) with section headers (Executive Summary, Detailed Numerical Breakdown with Markdown Table, Market Drivers, Source Attribution, Commercial Considerations), explicit website domain attribution ('According to GoodReturns (goodreturns.in) [C1]...'), rich in metrics, dates, and grounded claim tags [C1], [C2]...",
  "claim_evidence_map": [
    {{
      "claim_id": "C1",
      "claim": "Specific factual claim explicitly stating the source publication and figures (e.g. 'According to LiveChennai (livechennai.com), 22K gold rate is ₹14,000 per gram')",
      "status": "VERIFIED",
      "evidence": [
        {{
          "claim_id": "C1",
          "source_url": "https://...",
          "source_title": "Page Title",
          "quote": "Exact verbatim excerpt from source",
          "evidence_date": "2024"
        }}
      ]
    }},
    {{
      "claim_id": "C2",
      "claim": "Second distinct factual claim with source attribution",
      "status": "VERIFIED",
      "evidence": [ ... ]
    }}
    // Provide at least 5 to 6 distinct claims C1 through C6 covering all major facets
  ],
  "citations": [{{"id": "[C1]", "url": "https://...", "title": "Page Title"}}],
  "unverified_gaps": ["List of claims or gaps that could not be verified"],
  "discovered_entities": [{{"name": "...", "category": "..."}}],
  "discovered_facts": [{{"entity": "...", "attribute": "...", "value": "...", "source": "..."}}]
}}
"""

        resp = await self.llm.generate(prompt, system_instruction=system_instruction, json_mode=True)
        try:
            data = json.loads(resp.content)
            raw_map = data.get("claim_evidence_map", [])
            claims_list: list[StructuredClaim] = []

            for item in raw_map:
                if isinstance(item, dict):
                    c_id = item.get("claim_id", f"C{len(claims_list)+1}")
                    ev_list = [
                        EvidenceObject(
                            claim_id=c_id,
                            source_url=e.get("source_url", ""),
                            source_title=e.get("source_title"),
                            quote=e.get("quote", ""),
                            evidence_date=e.get("evidence_date"),
                        )
                        for e in item.get("evidence", [])
                        if isinstance(e, dict)
                    ]
                    claims_list.append(
                        StructuredClaim(
                            claim_id=c_id,
                            claim=item.get("claim", ""),
                            evidence=ev_list,
                            status=item.get("status", "VERIFIED"),
                        )
                    )

            # Build backward-compatible atomic_claims for auditor & telemetry
            atomic_claims: list[dict[str, Any]] = []
            for sc in claims_list:
                first_url = sc.evidence[0].source_url if sc.evidence else None
                first_quote = sc.evidence[0].quote if sc.evidence else ""
                atomic_claims.append(
                    {
                        "claim_id": sc.claim_id,
                        "claim": sc.claim,
                        "citation_id": f"[{sc.claim_id}]",
                        "url": first_url,
                        "quote": first_quote,
                        "status": sc.status,
                    }
                )

            # If atomic_claims was returned directly by LLM and claims_list was empty
            if not claims_list and "atomic_claims" in data:
                for idx, ac in enumerate(data.get("atomic_claims", [])):
                    c_id = ac.get("claim_id", f"C{idx+1}")
                    u = ac.get("url")
                    q = ac.get("quote", "")
                    ev = [EvidenceObject(claim_id=c_id, source_url=u, quote=q)] if u else []
                    sc = StructuredClaim(claim_id=c_id, claim=ac.get("claim", ""), evidence=ev)
                    claims_list.append(sc)
                    atomic_claims.append(ac)

            output = AnalystOutput(
                draft_answer=data.get("draft_answer", resp.content),
                claim_evidence_map=claims_list,
                citations=data.get("citations", []),
                atomic_claims=atomic_claims,
                unverified_gaps=data.get("unverified_gaps", []),
                discovered_entities=data.get("discovered_entities", []),
                discovered_facts=data.get("discovered_facts", []),
                tool_logs=[],
            )
        except Exception:
            output = AnalystOutput(
                draft_answer=resp.content,
                claim_evidence_map=[],
                citations=[],
                atomic_claims=[],
                unverified_gaps=["JSON parsing error in synthesis"],
                discovered_entities=[],
                discovered_facts=[],
                tool_logs=[],
            )

        return output, resp.prompt_tokens, resp.completion_tokens

    async def correct_draft(
        self,
        question: str,
        draft_answer: str,
        claim_evidence_map: list[StructuredClaim],
        flagged_issues: list[dict[str, Any]],
    ) -> tuple[str, list[StructuredClaim], int, int]:
        """
        Single correction pass triggered by the Auditor.
        Fixes contradicted statements, removes unsupported claims,
        and explicitly labels unverified details as UNVERIFIED.
        """
        system_instruction = (
            "You are the Research Analyst. The Auditor reviewed your draft and flagged specific factual issues.\n"
            "Rules for correction:\n"
            "1. For CONTRADICTED claims: correct the number, date, or detail to match the auditor's verified findings.\n"
            "2. For UNSUPPORTED, UNVERIFIABLE, or NO_CITATION claims: explicitly label them as UNVERIFIED or move them "
            "to an 'Unverified Information / Gaps' section instead of stating them as verified facts.\n"
            "3. Update the Claim-Evidence Map accordingly.\n"
            "4. Maintain comprehensive multi-paragraph depth (4-6 detailed paragraphs) with clear Markdown section headers and explicit website domain attribution (e.g. 'According to LiveChennai (livechennai.com) [C1]...'). Do NOT reduce the answer to a brief summary.\n"
            "Output JSON with keys: 'amended_answer', 'claim_evidence_map'."
        )

        prompt = f"""Question: {question}
Original Draft:
{draft_answer}

Current Claim-Evidence Map:
{json.dumps([c.model_dump() for c in claim_evidence_map], indent=2)}

Flagged Audit Issues:
{json.dumps(flagged_issues, indent=2)}

Produce the corrected answer and updated claim_evidence_map in JSON."""

        resp = await self.llm.generate(prompt, system_instruction=system_instruction, json_mode=True)
        try:
            data = json.loads(resp.content)
            amended_text = data.get("amended_answer", resp.content)
            raw_map = data.get("claim_evidence_map", [])
            corrected_map: list[StructuredClaim] = []
            for item in raw_map:
                if isinstance(item, dict):
                    c_id = item.get("claim_id", f"C{len(corrected_map)+1}")
                    ev_list = [
                        EvidenceObject(
                            claim_id=c_id,
                            source_url=e.get("source_url", ""),
                            source_title=e.get("source_title"),
                            quote=e.get("quote", ""),
                            evidence_date=e.get("evidence_date"),
                        )
                        for e in item.get("evidence", [])
                        if isinstance(e, dict)
                    ]
                    corrected_map.append(
                        StructuredClaim(
                            claim_id=c_id,
                            claim=item.get("claim", ""),
                            evidence=ev_list,
                            status=item.get("status", "VERIFIED"),
                        )
                    )
                elif isinstance(item, StructuredClaim):
                    corrected_map.append(item)
        except Exception:
            amended_text = resp.content
            corrected_map = claim_evidence_map

        return amended_text, corrected_map, resp.prompt_tokens, resp.completion_tokens
