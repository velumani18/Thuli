"""
Telemetry and Run Logging subsystem.

Captures complete execution traces, tool dispatches, HTTP failures,
epistemic verification audits, memory hits/misses, reference resolutions,
and token/rupee costs into /logs/runs/*.json.
"""

import json
import uuid
from datetime import datetime
from typing import Any, Optional, Literal
from pydantic import BaseModel, Field

from app.core.config import settings


class ToolInvocationLog(BaseModel):
    tool_name: str
    target: str  # URL or Search Query
    status: Literal["SUCCESS", "FAILED", "BLOCKED_403", "NOT_FOUND_404", "TIMEOUT", "FALLBACK_USED"]
    status_code: Optional[int] = None
    duration_ms: float = 0.0
    error_message: Optional[str] = None
    fallback_applied: Optional[str] = None


class ClaimAuditRecord(BaseModel):
    claim_id: str
    claim_text: str
    cited_url: Optional[str] = None
    analyst_evidence: Optional[str] = None
    analyst_extraction_status: Optional[str] = None
    auditor_source_status: Optional[str] = None
    auditor_evidence: Optional[str] = None
    verdict: Literal["SUPPORTED", "CONTRADICTED", "UNSUPPORTED", "NO_CITATION", "UNVERIFIABLE"]
    auditor_explanation: str
    source_snippet_extracted: Optional[str] = None
    correction_triggered: bool = False
    corrected_claim: Optional[str] = None
    final_verdict_after_correction: Optional[str] = None


class RunLogRecord(BaseModel):
    run_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    session_id: str = "default_session"
    timestamp: str = Field(default_factory=lambda: datetime.now().isoformat())
    original_question: str = ""
    question: str = ""  # Main question field
    category: Optional[str] = None

    # Performance & 120-Second Ceiling Telemetry Breakdown
    execution_time_seconds: float = 0.0
    planning_time_seconds: float = 0.0
    search_time_seconds: float = 0.0
    fetch_time_seconds: float = 0.0
    analyst_synthesis_time_seconds: float = 0.0
    auditor_time_seconds: float = 0.0
    correction_time_seconds: float = 0.0
    number_of_urls_searched: int = 0
    number_of_urls_fetched: int = 0
    number_of_usable_sources: int = 0
    failures_count: int = 0

    # Token & Cost Telemetry
    model_name: str = ""
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    cost_usd: float = 0.0
    cost_inr: float = 0.0

    # Memory & Conversation Reference Resolution Telemetry
    entities_detected: list[str] = Field(default_factory=list)
    references_detected: list[str] = Field(default_factory=list)
    references_resolved: dict[str, str] = Field(default_factory=dict)
    memory_hits: list[str] = Field(default_factory=list)
    memory_misses: list[str] = Field(default_factory=list)
    facts_retrieved_from_memory: list[dict[str, Any]] = Field(default_factory=list)
    clarification_required: bool = False
    clarification_message: Optional[str] = None
    resolved_research_question: str = ""
    new_facts_written_to_memory: list[dict[str, Any]] = Field(default_factory=list)

    entities_queried_from_memory: list[str] = Field(default_factory=list)
    entities_saved_to_memory: list[str] = Field(default_factory=list)
    memory_hit: bool = False

    # Candidate Fetching & Adaptive Threshold Telemetry
    number_of_candidates: int = 0
    number_of_successful_pages: int = 0
    number_of_blocked_pages: int = 0
    number_of_failed_pages: int = 0
    total_fetch_time_ms: float = 0.0
    minimum_evidence_threshold_reached: bool = False
    total_retries_performed: int = 0
    retry_telemetry: list[dict[str, Any]] = Field(default_factory=list)
    candidate_telemetry: list[dict[str, Any]] = Field(default_factory=list)

    # Trace steps
    research_plan: list[str] = Field(default_factory=list)
    search_queries: list[str] = Field(default_factory=list)
    tools_invoked: list[ToolInvocationLog] = Field(default_factory=list)

    # Analyst output
    analyst_draft_answer: str = ""
    analyst_citations: list[dict[str, str]] = Field(default_factory=list)
    claim_evidence_map: list[dict[str, Any]] = Field(default_factory=list)
    unverified_information_gaps: list[str] = Field(default_factory=list)

    # Auditor findings
    audit_records: list[ClaimAuditRecord] = Field(default_factory=list)
    audit_summary: dict[str, int] = Field(default_factory=dict)
    number_of_claims: int = 0
    claims_with_evidence: int = 0
    number_supported: int = 0
    number_contradicted: int = 0
    number_unsupported: int = 0
    number_unverifiable: int = 0
    number_without_citation: int = 0

    # Corrections & Final Verified Status
    correction_needed: bool = False
    correction_triggered: bool = False
    claims_corrected: int = 0
    final_verified_claims: int = 0
    analyst_amended_answer: Optional[str] = None
    final_verified_answer: str = ""

    def save_to_disk(self) -> str:
        """Serializes the run record to logs/runs/run_<timestamp>_<uuid>.json"""
        settings.runs_log_dir.mkdir(parents=True, exist_ok=True)
        safe_time = datetime.now().strftime("%Y%m%d_%H%M%S")
        slug_src = self.resolved_research_question or self.question
        slug = "".join(c for c in slug_src[:25] if c.isalnum() or c in ("-", "_")).strip()
        filename = f"run_{safe_time}_{self.run_id[:8]}_{slug}.json"
        filepath = settings.runs_log_dir / filename

        with open(filepath, "w", encoding="utf-8") as f:
            f.write(self.model_dump_json(indent=2))

        return str(filepath)
