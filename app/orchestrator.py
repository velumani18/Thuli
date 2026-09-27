"""
Research Orchestrator.

Coordinates the end-to-end Analyst and Auditor lifecycle:
1. Loads session context and resolves conversation references ("them", "that company", "he").
2. Flags clarification if references are ambiguous instead of guessing.
3. Directs Analyst to research and draft cited response based on resolved question.
4. Dispatches Auditor to independently verify claims directly from cited URLs (never trusting memory).
5. Implements the Auditor -> Analyst correction feedback loop.
6. Persists verified facts and session history into EntityMemory.
7. Serializes complete telemetry into /logs/runs/*.json.
"""

import time
import json
import asyncio
from typing import Optional

from app.core.config import settings
from app.core.llm import LLMClient
from app.core.telemetry import RunLogRecord
from app.memory.store import EntityMemoryStore, ReferenceResolutionResult
from app.agents.analyst import AnalystAgent, AnalystOutput
from app.agents.auditor import AuditorAgent, AuditorReport


class ResearchOrchestrator:
    def __init__(self, memory_store: Optional[EntityMemoryStore] = None):
        self.memory = memory_store or EntityMemoryStore()
        self.llm = LLMClient()
        self.analyst = AnalystAgent(self.llm)
        self.auditor = AuditorAgent(self.llm)

    async def execute_question(
        self, question: str, category: Optional[str] = None, session_id: Optional[str] = None
    ) -> RunLogRecord:
        start_time = time.time()
        active_session = session_id or "default_session"
        self.memory.create_session(active_session)

        run_record = RunLogRecord(
            session_id=active_session,
            original_question=question,
            question=question,
            category=category,
            model_name=settings.llm_model,
        )

        # Step 1: Session Context & Reference Resolution
        res: ReferenceResolutionResult = self.memory.resolve_references(active_session, question)
        run_record.entities_detected = res.entities_detected
        run_record.references_detected = res.references_detected
        run_record.references_resolved = res.references_resolved
        run_record.memory_hits = res.memory_hits
        run_record.memory_misses = res.memory_misses
        run_record.facts_retrieved_from_memory = res.facts_retrieved
        run_record.clarification_required = res.clarification_required
        run_record.clarification_message = res.clarification_message
        run_record.resolved_research_question = res.resolved_question
        run_record.question = res.resolved_question
        run_record.memory_hit = len(res.memory_hits) > 0
        run_record.entities_queried_from_memory = res.entities_detected

        # If reference is ambiguous or unknown, request clarification instead of guessing
        if res.clarification_required:
            run_record.final_verified_answer = res.clarification_message or "Clarification required."
            run_record.execution_time_seconds = round(time.time() - start_time, 2)
            self.memory.record_question(active_session, question, res.resolved_question, res.entities_detected)
            run_record.save_to_disk()
            return run_record

        memory_ctx = {
            "memory_hit": run_record.memory_hit,
            "matched_entities": res.entities_detected,
            "known_facts": res.facts_retrieved,
            "note": "Facts from memory are provided for context only and should be verified against live web evidence if freshness is critical.",
        }

        # Step 2: Analyst Planning on RESOLVED question (no raw ambiguous pronouns sent)
        t_plan_start = time.time()
        plan, p1, c1 = await self.analyst.plan_research(res.resolved_question, memory_ctx)
        run_record.planning_time_seconds = round(time.time() - t_plan_start, 3)
        run_record.research_plan = [plan.reasoning]
        run_record.search_queries = plan.search_queries
        run_record.number_of_urls_searched = len(plan.search_queries)
        prompt_tokens = p1
        comp_tokens = c1

        # Step 3: Evidence Gathering (Parallel Search & Adaptive Fetch)
        t_gather_start = time.time()
        evidence, tool_logs, fetch_report = await self.analyst.gather_evidence(plan.search_queries)
        t_gather_end = time.time()
        run_record.tools_invoked.extend(tool_logs)
        run_record.number_of_candidates = fetch_report.candidates_evaluated
        run_record.number_of_urls_fetched = fetch_report.candidates_evaluated
        run_record.number_of_successful_pages = fetch_report.successful_usable_count
        run_record.number_of_usable_sources = fetch_report.successful_usable_count
        run_record.number_of_blocked_pages = fetch_report.blocked_count
        run_record.number_of_failed_pages = fetch_report.failed_count
        run_record.failures_count = fetch_report.failed_count + fetch_report.blocked_count
        run_record.total_fetch_time_ms = fetch_report.total_fetch_time_ms
        run_record.fetch_time_seconds = round(fetch_report.total_fetch_time_ms / 1000.0, 3)
        run_record.search_time_seconds = round(max(0.0, (t_gather_end - t_gather_start) - run_record.fetch_time_seconds), 3)
        run_record.minimum_evidence_threshold_reached = fetch_report.threshold_reached
        run_record.total_retries_performed = fetch_report.total_retries_performed
        run_record.retry_telemetry = [
            attempt.model_dump() for attempt in fetch_report.retry_logs
        ]
        run_record.candidate_telemetry = [
            {
                "url": fr.url,
                "domain": fr.domain,
                "start_time_iso": fr.start_time_iso,
                "end_time_iso": fr.end_time_iso,
                "duration_ms": fr.duration_ms,
                "status": fr.status,
                "status_code": fr.status_code,
                "is_usable": fr.is_usable,
                "character_count": fr.character_count,
                "rejection_reason": fr.rejection_reason or fr.error_message,
                "total_retries": fr.total_retries,
                "retry_attempts": [ra.model_dump() for ra in fr.retry_attempts],
            }
            for fr in fetch_report.all_results
        ]

        # Step 4: Analyst Synthesis & Claim-Evidence Map
        t_synth_start = time.time()
        analyst_out, p2, c2 = await self.analyst.synthesize(res.resolved_question, plan, evidence, memory_ctx)
        run_record.analyst_synthesis_time_seconds = round(time.time() - t_synth_start, 3)
        prompt_tokens += p2
        comp_tokens += c2

        run_record.analyst_draft_answer = analyst_out.draft_answer
        run_record.analyst_citations = analyst_out.citations
        run_record.claim_evidence_map = [c.model_dump() for c in analyst_out.claim_evidence_map]
        run_record.unverified_information_gaps = analyst_out.unverified_gaps
        run_record.claims_with_evidence = sum(
            1 for c in analyst_out.claim_evidence_map if c.evidence and c.status == "VERIFIED"
        )

        # Step 5: Independent Auditor Verification (Claim-Level)
        # Critical constraint: Auditor does NOT receive or trust SQLite memory or Analyst quotes.
        # It verifies claims solely against independently fetched cited URLs.
        if not (analyst_out.claim_evidence_map or analyst_out.atomic_claims):
            run_record.auditor_time_seconds = 0.0
            run_record.audit_records = []
            run_record.audit_summary = {
                "SUPPORTED": 0, "CONTRADICTED": 0, "UNSUPPORTED": 0, "UNVERIFIABLE": 0, "NO_CITATION": 0
            }
            run_record.number_of_claims = 0
            run_record.claims_with_evidence = 0
            run_record.final_verified_claims = 0
            run_record.final_verified_answer = analyst_out.draft_answer
            final_answer = analyst_out.draft_answer
        else:
            t_audit_start = time.time()
            audit_rep = await self.auditor.audit_answer(
                analyst_out.draft_answer,
                analyst_out.claim_evidence_map or analyst_out.atomic_claims,
            )
            run_record.auditor_time_seconds = round(time.time() - t_audit_start, 3)
            run_record.tools_invoked.extend(audit_rep.tool_logs)
            run_record.audit_records = audit_rep.audit_records
            run_record.audit_summary = audit_rep.summary_counts
            run_record.number_of_claims = len(audit_rep.audit_records)
            run_record.number_supported = audit_rep.summary_counts.get("SUPPORTED", 0)
            run_record.number_contradicted = audit_rep.summary_counts.get("CONTRADICTED", 0)
            run_record.number_unsupported = audit_rep.summary_counts.get("UNSUPPORTED", 0)
            run_record.number_unverifiable = audit_rep.summary_counts.get("UNVERIFIABLE", 0)
            run_record.number_without_citation = audit_rep.summary_counts.get("NO_CITATION", 0)
            run_record.final_verified_claims = audit_rep.summary_counts.get("SUPPORTED", 0)
            prompt_tokens += audit_rep.total_prompt_tokens
            comp_tokens += audit_rep.total_completion_tokens

            # Step 6: Single Correction Pass (If Discrepancies Found)
            final_answer = analyst_out.draft_answer
            discrepancies = [
                r for r in audit_rep.audit_records
                if r.verdict in ("CONTRADICTED", "UNSUPPORTED", "UNVERIFIABLE", "NO_CITATION")
            ]

            if discrepancies:
                t_corr_start = time.time()
                run_record.correction_needed = True
                run_record.correction_triggered = True
                run_record.claims_corrected = len(discrepancies)

                corr_answer, corr_claims, p3, c3 = await self.analyst.correct_draft(
                    question=res.resolved_question,
                    draft_answer=analyst_out.draft_answer,
                    claim_evidence_map=analyst_out.claim_evidence_map,
                    flagged_issues=[r.model_dump() for r in discrepancies],
                )
                prompt_tokens += p3
                comp_tokens += c3
                final_answer = corr_answer
                run_record.analyst_amended_answer = final_answer

                # Re-audit corrected claims
                re_audit = await self.auditor.audit_answer(final_answer, corr_claims)
                run_record.tools_invoked.extend(re_audit.tool_logs)
                prompt_tokens += re_audit.total_prompt_tokens
                comp_tokens += re_audit.total_completion_tokens
                run_record.correction_time_seconds = round(time.time() - t_corr_start, 3)

                # Synchronize final verdicts in audit_records
                re_audit_map = {r.claim_id: r for r in re_audit.audit_records}
                for rec in run_record.audit_records:
                    rec.correction_triggered = True
                    if rec.claim_id in re_audit_map:
                        corr_rec = re_audit_map[rec.claim_id]
                        rec.corrected_claim = corr_rec.claim_text
                        rec.final_verdict_after_correction = corr_rec.verdict
                    else:
                        rec.final_verdict_after_correction = rec.verdict

                # Update final summaries
                run_record.audit_summary = re_audit.summary_counts
                run_record.number_supported = re_audit.summary_counts.get("SUPPORTED", 0)
                run_record.number_contradicted = re_audit.summary_counts.get("CONTRADICTED", 0)
                run_record.number_unsupported = re_audit.summary_counts.get("UNSUPPORTED", 0)
                run_record.number_unverifiable = re_audit.summary_counts.get("UNVERIFIABLE", 0)
                run_record.number_without_citation = re_audit.summary_counts.get("NO_CITATION", 0)
                run_record.final_verified_claims = re_audit.summary_counts.get("SUPPORTED", 0)

        run_record.final_verified_answer = final_answer

        # Step 7: Update Memory with Discovered Entities & Facts
        saved_entities = []
        new_facts_written = []

        for ent in analyst_out.discovered_entities:
            name = ent.get("name", "")
            cat = ent.get("category", category or "general")
            if name:
                self.memory.save_entity(name, cat)
                saved_entities.append(name)

        for fact in analyst_out.discovered_facts:
            e_name = fact.get("entity", "")
            attr = fact.get("attribute", "")
            val = fact.get("value", "")
            src = fact.get("source", "")
            title = fact.get("title")
            f_date = fact.get("date")
            if e_name and attr and val:
                self.memory.save_fact(
                    entity_name=e_name,
                    attribute=attr,
                    value=val,
                    source_url=src,
                    source_title=title,
                    fact_date=f_date,
                )
                self.memory.save_knowledge_snippet(
                    session_id=active_session,
                    topic_or_entity=e_name,
                    finding_snippet=f"{e_name} {attr}: {val}",
                    source_url=src,
                    source_title=title,
                    fact_date=f_date,
                )
                new_facts_written.append({
                    "entity": e_name,
                    "attribute": attr,
                    "value": val,
                    "source_url": src,
                    "fact_date": f_date,
                })

        run_record.entities_saved_to_memory = saved_entities
        run_record.new_facts_written_to_memory = new_facts_written

        # Record this question into session history for future reference resolution
        all_involved_entities = list(set(res.entities_detected + saved_entities))
        self.memory.record_question(
            session_id=active_session,
            raw_question=question,
            resolved_question=res.resolved_question,
            entities=all_involved_entities,
        )

        # Step 8: Telemetry & Pricing Finalization
        elapsed = time.time() - start_time
        run_record.execution_time_seconds = round(elapsed, 2)
        run_record.prompt_tokens = prompt_tokens
        run_record.completion_tokens = comp_tokens
        run_record.total_tokens = prompt_tokens + comp_tokens
        cost_usd, cost_inr = settings.calculate_cost(settings.llm_model, prompt_tokens, comp_tokens)
        run_record.cost_usd = round(cost_usd, 6)
        run_record.cost_inr = round(cost_inr, 4)

        # Save to disk
        run_record.save_to_disk()
        return run_record
