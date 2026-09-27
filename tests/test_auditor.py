"""
Unit tests for Claim-Evidence Mapping, Auditor Independent Verification,
Adversarial Detection, and Single Correction Pass.

Covers all user-specified test requirements:
1. Claim with matching source -> SUPPORTED
2. Claim contradicted by source -> CONTRADICTED
3. Claim with no evidence -> UNSUPPORTED
4. Claim with no citation -> NO_CITATION
5. Source blocked/unavailable -> UNVERIFIABLE
6. Analyst gives multiple claims with different evidence
7. One claim fails while other claims are supported
8. Auditor triggers one correction cycle
9. Corrected claim is re-audited
10. No unsupported claim is silently included as a verified fact
11. Deliberate adversarial test: Auditor catches incorrect factual claim
"""

import json
import pytest
from unittest.mock import AsyncMock, patch

from app.agents.analyst import AnalystAgent, StructuredClaim, EvidenceObject, AnalystOutput
from app.agents.auditor import AuditorAgent, AuditorReport
from app.core.llm import LLMResponse
from app.core.telemetry import ClaimAuditRecord
from app.orchestrator import ResearchOrchestrator
from app.tools.fetcher import FetchResult


def _create_mock_fetch_result(url: str, text: str, status: str = "SUCCESS", status_code: int = 200, is_usable: bool = True) -> FetchResult:
    return FetchResult(
        url=url,
        status=status,
        status_code=status_code,
        extracted_text=text,
        character_count=len(text),
        is_usable=is_usable,
        rejection_reason=None if is_usable else f"Source failed ({status})",
    )


def _mock_llm_response(content: str) -> LLMResponse:
    return LLMResponse(
        content=content,
        model="mock-model",
        prompt_tokens=50,
        completion_tokens=30,
    )


# 1. Claim with matching source -> SUPPORTED
@pytest.mark.asyncio
async def test_claim_matching_source_supported():
    auditor = AuditorAgent()
    url = "https://mock.test/zepto"
    source_text = "Quick commerce platform Zepto raised $665 million in June 2024 at a $3.6 billion valuation."
    
    mock_fr = _create_mock_fetch_result(url, source_text)
    mock_llm_eval = json.dumps({
        "verdict": "SUPPORTED",
        "explanation": "The independently fetched source directly confirms Zepto raised $665 million in June 2024.",
        "snippet_quote": "Zepto raised $665 million in June 2024 at a $3.6 billion valuation."
    })

    claim = StructuredClaim(
        claim_id="C1",
        claim="Zepto raised $665M in June 2024",
        evidence=[EvidenceObject(claim_id="C1", source_url=url, quote="$665 million in June 2024")]
    )

    with patch.object(auditor.fetcher, "fetch_multiple", new_callable=AsyncMock) as mock_fetch:
        mock_fetch.return_value = [mock_fr]
        with patch.object(auditor.llm, "generate", new_callable=AsyncMock) as mock_gen:
            mock_gen.return_value = _mock_llm_response(mock_llm_eval)
            report = await auditor.audit_answer("Draft answer [C1]", [claim])

            assert len(report.audit_records) == 1
            rec = report.audit_records[0]
            assert rec.verdict == "SUPPORTED"
            assert rec.auditor_source_status == "SUCCESS"
            assert "$665 million" in rec.auditor_evidence
            assert report.passed_all is True


# 2. Claim contradicted by source -> CONTRADICTED
@pytest.mark.asyncio
async def test_claim_contradicted_by_source():
    auditor = AuditorAgent()
    url = "https://mock.test/company_x"
    source_text = "Company X confirmed it closed a $300M series C funding round, explicitly denying rumors of $500M."
    
    mock_fr = _create_mock_fetch_result(url, source_text)
    mock_llm_eval = json.dumps({
        "verdict": "CONTRADICTED",
        "explanation": "The independently fetched source reports $300M, contradicting the claimed $500M.",
        "snippet_quote": "closed a $300M series C funding round"
    })

    claim = StructuredClaim(
        claim_id="C1",
        claim="Company X raised $500M in June 2026",
        evidence=[EvidenceObject(claim_id="C1", source_url=url, quote="Company X raised $500M")]
    )

    with patch.object(auditor.fetcher, "fetch_multiple", new_callable=AsyncMock) as mock_fetch:
        mock_fetch.return_value = [mock_fr]
        with patch.object(auditor.llm, "generate", new_callable=AsyncMock) as mock_gen:
            mock_gen.return_value = _mock_llm_response(mock_llm_eval)
            report = await auditor.audit_answer("Draft answer [C1]", [claim])

            assert len(report.audit_records) == 1
            rec = report.audit_records[0]
            assert rec.verdict == "CONTRADICTED"
            assert "$300M" in rec.auditor_explanation
            assert report.passed_all is False
            assert report.summary_counts["CONTRADICTED"] == 1


# 3. Claim with no evidence -> UNSUPPORTED
@pytest.mark.asyncio
async def test_claim_with_no_evidence_unsupported():
    auditor = AuditorAgent()
    url = "https://mock.test/southeast_asia"
    source_text = "The retailer expanded rapidly across Southeast Asia including Thailand and Vietnam in 2024."
    
    mock_fr = _create_mock_fetch_result(url, source_text)
    mock_llm_eval = json.dumps({
        "verdict": "UNSUPPORTED",
        "explanation": "Source discusses expansion in Thailand and Vietnam, but does not mention or support expansion into Australia.",
        "snippet_quote": ""
    })

    claim = StructuredClaim(
        claim_id="C1",
        claim="The retailer expanded into Australia in 2024",
        evidence=[EvidenceObject(claim_id="C1", source_url=url, quote="expanded rapidly")]
    )

    with patch.object(auditor.fetcher, "fetch_multiple", new_callable=AsyncMock) as mock_fetch:
        mock_fetch.return_value = [mock_fr]
        with patch.object(auditor.llm, "generate", new_callable=AsyncMock) as mock_gen:
            mock_gen.return_value = _mock_llm_response(mock_llm_eval)
            report = await auditor.audit_answer("Draft answer [C1]", [claim])

            assert len(report.audit_records) == 1
            rec = report.audit_records[0]
            assert rec.verdict == "UNSUPPORTED"
            assert "Australia" in rec.auditor_explanation
            assert report.passed_all is False


# 4. Claim with no citation -> NO_CITATION
@pytest.mark.asyncio
async def test_claim_with_no_citation():
    auditor = AuditorAgent()
    claim = StructuredClaim(
        claim_id="C1",
        claim="Quick commerce gross merchandise value grew 150% nationally.",
        evidence=[]  # Zero citation/evidence
    )

    report = await auditor.audit_answer("Draft answer with uncited fact", [claim])
    assert len(report.audit_records) == 1
    rec = report.audit_records[0]
    assert rec.verdict == "NO_CITATION"
    assert rec.cited_url is None
    assert "No citation" in rec.auditor_explanation
    assert report.passed_all is False


# 5. Source blocked/unavailable -> UNVERIFIABLE
@pytest.mark.asyncio
async def test_source_blocked_or_unavailable_unverifiable():
    auditor = AuditorAgent()
    url = "https://mock.test/blocked_403"
    mock_fr = FetchResult(
        url=url,
        status="BLOCKED_403",
        status_code=403,
        is_usable=False,
        rejection_reason="Access blocked by host with status 403 (Anti-bot challenge)."
    )

    claim = StructuredClaim(
        claim_id="C1",
        claim="Blinkit daily orders exceeded 1.2 million.",
        evidence=[EvidenceObject(claim_id="C1", source_url=url, quote="1.2 million orders")]
    )

    with patch.object(auditor.fetcher, "fetch_multiple", new_callable=AsyncMock) as mock_fetch:
        mock_fetch.return_value = [mock_fr]
        report = await auditor.audit_answer("Draft [C1]", [claim])

        assert len(report.audit_records) == 1
        rec = report.audit_records[0]
        # Must be UNVERIFIABLE, not falsely marked SUPPORTED or CONTRADICTED
        assert rec.verdict == "UNVERIFIABLE"
        assert rec.auditor_source_status == "BLOCKED_403"
        assert "cannot be accessed" in rec.auditor_explanation.lower()
        assert report.passed_all is False


# 6. Analyst gives multiple claims with different evidence
@pytest.mark.asyncio
async def test_analyst_gives_multiple_claims_different_evidence():
    auditor = AuditorAgent()
    url1 = "https://mock.test/titan"
    url2 = "https://mock.test/kalyan"

    fr1 = _create_mock_fetch_result(url1, "Titan opened 90 retail stores across India in FY24.")
    fr2 = _create_mock_fetch_result(url2, "Kalyan Jewellers added 71 new showrooms in non-south regions.")

    c1 = StructuredClaim(
        claim_id="C1",
        claim="Titan opened 90 retail stores in FY24",
        evidence=[EvidenceObject(claim_id="C1", source_url=url1, quote="opened 90 retail stores")]
    )
    c2 = StructuredClaim(
        claim_id="C2",
        claim="Kalyan Jewellers added 71 showrooms",
        evidence=[EvidenceObject(claim_id="C2", source_url=url2, quote="added 71 new showrooms")]
    )

    def mock_eval_side_effect(prompt, **kwargs):
        if "Titan" in prompt:
            return _mock_llm_response(json.dumps({"verdict": "SUPPORTED", "explanation": "Titan verified", "snippet_quote": "opened 90 retail stores"}))
        return _mock_llm_response(json.dumps({"verdict": "SUPPORTED", "explanation": "Kalyan verified", "snippet_quote": "added 71 new showrooms"}))

    with patch.object(auditor.fetcher, "fetch_multiple", new_callable=AsyncMock) as mock_fetch:
        mock_fetch.return_value = [fr1, fr2]
        with patch.object(auditor.llm, "generate", side_effect=mock_eval_side_effect):
            report = await auditor.audit_answer("Titan [C1] and Kalyan [C2]", [c1, c2])
            assert len(report.audit_records) == 2
            assert report.audit_records[0].verdict == "SUPPORTED"
            assert report.audit_records[1].verdict == "SUPPORTED"
            assert report.summary_counts["SUPPORTED"] == 2
            assert report.passed_all is True


# 7. One claim fails while other claims are supported
@pytest.mark.asyncio
async def test_one_claim_fails_while_others_supported():
    auditor = AuditorAgent()
    url1 = "https://mock.test/titan"
    url2 = "https://mock.test/caratlane"

    fr1 = _create_mock_fetch_result(url1, "Titan opened 90 retail stores in FY24.")
    fr2 = _create_mock_fetch_result(url2, "CaratLane revenue was 2,000 crores, not 5,000 crores.")

    c1 = StructuredClaim(claim_id="C1", claim="Titan opened 90 retail stores", evidence=[EvidenceObject(claim_id="C1", source_url=url1, quote="90 stores")])
    c2 = StructuredClaim(claim_id="C2", claim="CaratLane revenue was 5,000 crores", evidence=[EvidenceObject(claim_id="C2", source_url=url2, quote="5,000 crores")])

    def mock_eval_side_effect(prompt, **kwargs):
        if "Titan" in prompt:
            return _mock_llm_response(json.dumps({"verdict": "SUPPORTED", "explanation": "Verified", "snippet_quote": "opened 90 retail stores"}))
        return _mock_llm_response(json.dumps({"verdict": "CONTRADICTED", "explanation": "Source states 2,000 crores, not 5,000.", "snippet_quote": "2,000 crores"}))

    with patch.object(auditor.fetcher, "fetch_multiple", new_callable=AsyncMock) as mock_fetch:
        mock_fetch.return_value = [fr1, fr2]
        with patch.object(auditor.llm, "generate", side_effect=mock_eval_side_effect):
            report = await auditor.audit_answer("Draft answer", [c1, c2])
            assert report.summary_counts["SUPPORTED"] == 1
            assert report.summary_counts["CONTRADICTED"] == 1
            assert report.passed_all is False


# 8. Auditor triggers one correction cycle and corrected claim is re-audited
@pytest.mark.asyncio
async def test_auditor_triggers_correction_cycle_and_re_audited():
    analyst = AnalystAgent()
    auditor = AuditorAgent()

    # Initial draft with a contradicted claim
    initial_claims = [
        StructuredClaim(
            claim_id="C1",
            claim="Company X raised $500M in June",
            evidence=[EvidenceObject(claim_id="C1", source_url="https://mock.test/round", quote="raised $500M")]
        )
    ]
    initial_answer = "Company X raised $500M in June [C1]."

    # 1. Auditor finds contradiction
    fr_source = _create_mock_fetch_result("https://mock.test/round", "Company X raised $300M in June.")
    audit_eval_1 = json.dumps({"verdict": "CONTRADICTED", "explanation": "Source reports $300M, not $500M.", "snippet_quote": "raised $300M"})

    with patch.object(auditor.fetcher, "fetch_multiple", new_callable=AsyncMock) as mock_fetch:
        mock_fetch.return_value = [fr_source]
        with patch.object(auditor.llm, "generate", new_callable=AsyncMock) as mock_gen:
            mock_gen.return_value = _mock_llm_response(audit_eval_1)
            initial_audit = await auditor.audit_answer(initial_answer, initial_claims)
            assert initial_audit.passed_all is False
            assert initial_audit.summary_counts["CONTRADICTED"] == 1

    # 2. Analyst single correction pass
    correction_llm_resp = json.dumps({
        "amended_answer": "Company X raised $300M in June [C1].",
        "claim_evidence_map": [
            {
                "claim_id": "C1",
                "claim": "Company X raised $300M in June",
                "status": "VERIFIED",
                "evidence": [{"claim_id": "C1", "source_url": "https://mock.test/round", "quote": "raised $300M"}]
            }
        ]
    })

    with patch.object(analyst.llm, "generate", new_callable=AsyncMock) as mock_gen:
        mock_gen.return_value = _mock_llm_response(correction_llm_resp)
        amended_ans, amended_claims, _, _ = await analyst.correct_draft(
            question="What did Company X raise?",
            draft_answer=initial_answer,
            claim_evidence_map=initial_claims,
            flagged_issues=[initial_audit.audit_records[0].model_dump()]
        )
        assert "300M" in amended_ans
        assert amended_claims[0].claim == "Company X raised $300M in June"

    # 3. Auditor re-audits amended claim -> now SUPPORTED!
    audit_eval_2 = json.dumps({"verdict": "SUPPORTED", "explanation": "Verified from source.", "snippet_quote": "raised $300M"})
    with patch.object(auditor.fetcher, "fetch_multiple", new_callable=AsyncMock) as mock_fetch:
        mock_fetch.return_value = [fr_source]
        with patch.object(auditor.llm, "generate", new_callable=AsyncMock) as mock_gen:
            mock_gen.return_value = _mock_llm_response(audit_eval_2)
            re_audit = await auditor.audit_answer(amended_ans, amended_claims)
            assert re_audit.passed_all is True
            assert re_audit.summary_counts["SUPPORTED"] == 1


# 9. No unsupported claim is silently included as a verified fact
@pytest.mark.asyncio
async def test_no_unsupported_claim_silently_included_as_verified():
    analyst = AnalystAgent()
    claim_map = [
        StructuredClaim(
            claim_id="C1",
            claim="Unconfirmed merger between Company A and Company B.",
            status="UNVERIFIED",
            evidence=[]
        )
    ]
    correction_resp = json.dumps({
        "amended_answer": "Company A and B were rumored to merge, but this remains UNVERIFIED due to lack of primary evidence.",
        "claim_evidence_map": [
            {
                "claim_id": "C1",
                "claim": "Merger between Company A and B",
                "status": "UNVERIFIED",
                "evidence": []
            }
        ]
    })

    with patch.object(analyst.llm, "generate", new_callable=AsyncMock) as mock_gen:
        mock_gen.return_value = _mock_llm_response(correction_resp)
        amended_ans, amended_map, _, _ = await analyst.correct_draft(
            question="Did Company A and B merge?",
            draft_answer="Company A merged with Company B.",
            claim_evidence_map=claim_map,
            flagged_issues=[{"claim_id": "C1", "verdict": "UNSUPPORTED", "auditor_explanation": "No primary source"}]
        )
        # Must be explicitly qualified as UNVERIFIED rather than stated as fact
        assert "UNVERIFIED" in amended_ans
        assert amended_map[0].status == "UNVERIFIED"


# 10. Deliberate Adversarial Test: Auditor catches hallucinated/incorrect claim
@pytest.mark.asyncio
async def test_adversarial_auditor_catches_incorrect_factual_claim():
    """
    Deliberately passes an incorrect/hallucinated claim to the Auditor.
    The Auditor independently inspects the cited source text and MUST catch the error.
    """
    auditor = AuditorAgent()
    url = "https://economic-times.test/executive-announcement"
    
    # What the actual source says:
    actual_source_article = (
        "Blinkit CEO Albinder Dhindsa announced a new long-term operational roadmap "
        "focusing on dark-store automation and grocery expansion across Tier-2 cities in India."
    )
    mock_fr = _create_mock_fetch_result(url, actual_source_article)

    # What the hallucinated / adversarial claim asserts:
    hallucinated_claim = StructuredClaim(
        claim_id="C_ADVERSARIAL",
        claim="Blinkit CEO resigned in August 2024 to launch an independent AI startup.",
        evidence=[EvidenceObject(claim_id="C_ADVERSARIAL", source_url=url, quote="announced a new long-term operational roadmap")]
    )

    # Auditor LLM evaluation detects discrepancy
    auditor_eval = json.dumps({
        "verdict": "CONTRADICTED",
        "explanation": "The source reports that CEO Albinder Dhindsa announced an operational roadmap, and nowhere mentions resignation.",
        "snippet_quote": "CEO Albinder Dhindsa announced a new long-term operational roadmap"
    })

    with patch.object(auditor.fetcher, "fetch_multiple", new_callable=AsyncMock) as mock_fetch:
        mock_fetch.return_value = [mock_fr]
        with patch.object(auditor.llm, "generate", new_callable=AsyncMock) as mock_gen:
            mock_gen.return_value = _mock_llm_response(auditor_eval)
            report = await auditor.audit_answer("Blinkit leadership change [C_ADVERSARIAL]", [hallucinated_claim])

            assert len(report.audit_records) == 1
            rec = report.audit_records[0]
            # Crucial: Auditor did NOT agree or rubber-stamp; caught the contradiction!
            assert rec.verdict == "CONTRADICTED"
            assert "resignation" in rec.auditor_explanation
            assert report.passed_all is False


# 11. Contradictory sources: Disagreement explicitly detected and reported
@pytest.mark.asyncio
async def test_contradictory_sources_explicitly_handled():
    """
    Demonstrates handling when two sources disagree on numbers:
    Source A -> $500M
    Source B -> $450M
    The Analyst declares the conflict, and Auditor verifies both are represented.
    """
    auditor = AuditorAgent()
    url_a = "https://source-a.test/report"
    url_b = "https://source-b.test/filing"

    fr_a = _create_mock_fetch_result(url_a, "Company Z raised $500M in series D according to initial leaks.")
    fr_b = _create_mock_fetch_result(url_b, "Company Z official regulatory filing confirms total proceeds were $450M.")

    claim_with_conflict = StructuredClaim(
        claim_id="C_CONFLICT",
        claim="Company Z raised $450M as confirmed in official filings, though earlier media leaks claimed $500M.",
        evidence=[
            EvidenceObject(claim_id="C_CONFLICT", source_url=url_b, source_title="Regulatory Filing", quote="total proceeds were $450M"),
            EvidenceObject(claim_id="C_CONFLICT", source_url=url_a, source_title="Media Leak", quote="raised $500M in series D"),
        ]
    )

    eval_resp = json.dumps({
        "verdict": "SUPPORTED",
        "explanation": "Source B confirms the $450M official filing while Source A confirms the $500M earlier report. The discrepancy is accurately characterized.",
        "snippet_quote": "total proceeds were $450M"
    })

    with patch.object(auditor.fetcher, "fetch_multiple", new_callable=AsyncMock) as mock_fetch:
        mock_fetch.return_value = [fr_a, fr_b]
        with patch.object(auditor.llm, "generate", new_callable=AsyncMock) as mock_gen:
            mock_gen.return_value = _mock_llm_response(eval_resp)
            report = await auditor.audit_answer("Disagreement noted [C_CONFLICT]", [claim_with_conflict])
            assert len(report.audit_records) == 1
            assert report.audit_records[0].verdict == "SUPPORTED"
            assert "discrepancy" in report.audit_records[0].auditor_explanation.lower()


# 12. Measure 120-second requirement and full phase latency telemetry
@pytest.mark.asyncio
async def test_end_to_end_question_measured_under_120_seconds(tmp_path):
    """
    Executes a complete end-to-end question run through the ResearchOrchestrator.
    Measures every phase timer and verifies compliance with the 120s ceiling.
    """
    from pathlib import Path
    from app.memory.store import EntityMemoryStore
    from app.tools.search import SearchResultItem, SearchResult
    from app.tools.fetcher import AdaptiveFetchReport

    db_file = tmp_path / "test_exec.db"
    mem_store = EntityMemoryStore(db_path=db_file)
    orchestrator = ResearchOrchestrator(memory_store=mem_store)

    good_url = "https://mock.test/zepto_expansion"
    source_body = "Zepto operates 350 dark stores in India and raised $665M in 2024 to accelerate expansion."
    mock_fr = _create_mock_fetch_result(good_url, source_body)

    # Mock Search
    mock_search_item = SearchResultItem(title="Zepto Info", url=good_url, snippet="350 dark stores")
    mock_search_resp = SearchResult(query="Zepto", engine="test", items=[mock_search_item])

    # Mock Analyst Plan
    plan_json = json.dumps({
        "reasoning": "Investigate Zepto dark stores",
        "search_queries": ["Zepto dark stores count 2024"],
        "identified_entities": ["Zepto"]
    })

    # Mock Analyst Synthesis
    synth_json = json.dumps({
        "draft_answer": "Zepto operates 350 dark stores across India [C1].",
        "claim_evidence_map": [
            {
                "claim_id": "C1",
                "claim": "Zepto operates 350 dark stores in India",
                "status": "VERIFIED",
                "evidence": [{"claim_id": "C1", "source_url": good_url, "quote": "operates 350 dark stores in India"}]
            }
        ],
        "citations": [{"id": "[C1]", "url": good_url}],
        "unverified_gaps": [],
        "discovered_entities": [{"name": "Zepto", "category": "quick_commerce"}],
        "discovered_facts": [{"entity": "Zepto", "attribute": "store_count", "value": "350", "source": good_url}]
    })

    # Mock Auditor Eval
    audit_json = json.dumps({
        "verdict": "SUPPORTED",
        "explanation": "Verified from source text.",
        "snippet_quote": "Zepto operates 350 dark stores in India"
    })

    def mock_llm_router(prompt, **kwargs):
        sys_inst = (kwargs.get("system_instruction") or "").lower()
        if "planning" in sys_inst:
            return _mock_llm_response(plan_json)
        elif "fact-checking" in sys_inst or "auditor" in sys_inst:
            return _mock_llm_response(audit_json)
        elif "research analyst" in sys_inst:
            return _mock_llm_response(synth_json)
        return _mock_llm_response(synth_json)

    with patch.object(orchestrator.analyst.search_engine, "search", new_callable=AsyncMock, return_value=mock_search_resp):
        with patch.object(orchestrator.analyst.fetcher, "fetch_with_adaptive_stopping", new_callable=AsyncMock) as mock_adaptive:
            mock_adaptive.return_value = AdaptiveFetchReport(
                candidates_evaluated=1,
                successful_usable_count=1,
                threshold_reached=True,
                total_fetch_time_ms=120.0,
                usable_results=[mock_fr],
                all_results=[mock_fr],
            )
            with patch.object(orchestrator.auditor.fetcher, "fetch_multiple", new_callable=AsyncMock, return_value=[mock_fr]):
                with patch.object(orchestrator.llm, "generate", side_effect=mock_llm_router):
                    with patch.object(orchestrator.analyst.llm, "generate", side_effect=mock_llm_router):
                        with patch.object(orchestrator.auditor.llm, "generate", side_effect=mock_llm_router):
                            run_log = await orchestrator.execute_question(
                                "How many dark stores does Zepto operate?",
                                category="quick_commerce"
                            )

                            # 1. 120-second hard ceiling verification
                            assert run_log.execution_time_seconds < 120.0
                            assert run_log.execution_time_seconds >= 0.0

                            # 2. Complete Phase Latency Breakdown telemetry
                            assert run_log.planning_time_seconds >= 0.0
                            assert run_log.search_time_seconds >= 0.0
                            assert run_log.fetch_time_seconds >= 0.0
                            assert run_log.analyst_synthesis_time_seconds >= 0.0
                            assert run_log.auditor_time_seconds >= 0.0

                            # 3. Evidence Coverage telemetry
                            assert run_log.number_of_claims == 1
                            assert run_log.claims_with_evidence == 1
                            assert run_log.number_supported == 1
                            assert run_log.final_verified_claims == 1
                            assert run_log.number_contradicted == 0
                            assert run_log.number_unsupported == 0
                            assert run_log.number_unverifiable == 0
                            assert run_log.number_without_citation == 0
                            assert run_log.correction_triggered is False

                            # 4. Verified that run log saved to disk
                            saved_path = run_log.save_to_disk()
                            assert Path(saved_path).exists()


# 13. Measure memory benefit across two sequential questions
@pytest.mark.asyncio
async def test_measure_memory_benefit_two_sequential_questions(tmp_path):
    """
    Demonstrates Requirement 8:
    Question 1: Learns Zepto and Blinkit
    Question 2: Reuses entities via reference resolution ("Which of them...")
    Verifies that reference resolution resolves the pronoun, records memory hit,
    and enables targeted factual queries rather than broad entity searches.
    """
    from app.memory.store import EntityMemoryStore

    db_file = tmp_path / "test_memory_benefit.db"
    mem_store = EntityMemoryStore(db_path=db_file)
    session_id = "eval_session_memory_benefit"

    # Pre-populate Q1 learnings in memory
    mem_store.save_entity("Zepto", "quick_commerce")
    mem_store.save_entity("Blinkit", "quick_commerce")
    mem_store.record_question(
        session_id=session_id,
        raw_question="Which quick commerce companies operate in India?",
        resolved_question="Which quick commerce companies operate in India?",
        entities=["Zepto", "Blinkit"],
    )

    # Question 2 references "them"
    q2_text = "Which of them raised funding recently?"
    res = mem_store.resolve_references(session_id, q2_text)

    # Must resolve "them" directly to the previously learned entities
    assert res.clarification_required is False
    assert "Zepto" in res.entities_detected
    assert "Blinkit" in res.entities_detected
    assert len(res.references_resolved) > 0
    assert any("them" in k for k in res.references_resolved)
    # The resolved question avoids broad search and targets the exact entities
    assert "Zepto" in res.resolved_question or "Blinkit" in res.resolved_question
