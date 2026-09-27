"""
Unit tests for EntityMemoryStore and Reference Resolution.
Covers all requirements from Thuli Studios problem specification:
1. Existing entity/fact persistence.
2. Entity remembered across two questions in a session.
3. 'them' resolves to previously mentioned entities.
4. 'that company' resolves correctly when unambiguous.
5. Person/entity relationship can be followed ("he" -> person name).
6. Unknown pronoun/reference does not cause a hallucinated entity (triggers clarification).
7. A new session does not accidentally inherit another session's context.
8. Memory facts retain their source URL and metadata.
9. Auditor does not treat SQLite memory as independent evidence.
"""

import pytest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from app.memory.store import EntityMemoryStore
from app.agents.auditor import AuditorAgent
from app.tools.fetcher import FetchResult


@pytest.fixture
def temp_memory_store(tmp_path: Path):
    db_file = tmp_path / "test_entities.db"
    return EntityMemoryStore(db_path=db_file)


# 1. Base entity persistence
def test_save_and_retrieve_entity(temp_memory_store: EntityMemoryStore):
    ent_id = temp_memory_store.save_entity(
        name="Zepto", category="quick_commerce", aliases=["KiranaKart"]
    )
    assert ent_id == "zepto"

    entities = temp_memory_store.get_all_entities()
    assert len(entities) == 1
    assert entities[0].name == "Zepto"
    assert entities[0].category == "quick_commerce"


# 2. Base fact persistence
def test_save_and_retrieve_facts(temp_memory_store: EntityMemoryStore):
    temp_memory_store.save_entity("Blinkit", "quick_commerce")
    fact_id = temp_memory_store.save_fact(
        entity_name="Blinkit",
        attribute="cto",
        value="Sajid Rahman",
        source_url="https://example.com/blinkit-cto",
    )
    assert fact_id is not None

    facts = temp_memory_store.get_facts_for_entity("Blinkit")
    assert len(facts) == 1
    assert facts[0].attribute == "cto"
    assert facts[0].value == "Sajid Rahman"


# 3. Base context resolution
def test_resolve_context_anaphora(temp_memory_store: EntityMemoryStore):
    temp_memory_store.save_entity("Zepto", "quick_commerce")
    temp_memory_store.save_entity("Blinkit", "quick_commerce")

    res = temp_memory_store.resolve_context("Which of those companies raised funding?")
    assert res["memory_hit"] is True
    assert "Zepto" in res["matched_entities"]
    assert "Blinkit" in res["matched_entities"]


# 4. Entity is remembered across two questions in a session
def test_entity_remembered_across_two_questions(temp_memory_store: EntityMemoryStore):
    session_id = "session_test_cross_q"
    # Question 1: establishes entity
    temp_memory_store.record_question(
        session_id=session_id,
        raw_question="Who are the quick commerce players?",
        resolved_question="Who are the quick commerce players?",
        entities=["Zepto", "Blinkit"],
    )

    # Question 2: checks session entities
    recent = temp_memory_store.get_session_recent_entities(session_id)
    assert "Zepto" in recent
    assert "Blinkit" in recent


# 5. 'them' resolves to previously mentioned entities
def test_them_resolves_to_previously_mentioned_entities(temp_memory_store: EntityMemoryStore):
    session_id = "session_them_test"
    temp_memory_store.save_entity("Zepto", "quick_commerce")
    temp_memory_store.save_entity("Blinkit", "quick_commerce")
    temp_memory_store.save_entity("Swiggy Instamart", "quick_commerce")

    temp_memory_store.record_question(
        session_id=session_id,
        raw_question="Which companies raised funding?",
        resolved_question="Which companies raised funding?",
        entities=["Zepto", "Blinkit", "Swiggy Instamart"],
    )

    res = temp_memory_store.resolve_references(session_id, "Which of them raised the most?")
    assert res.clarification_required is False
    assert "Zepto, Blinkit, and Swiggy Instamart" in res.resolved_question
    assert "Which of Zepto, Blinkit, and Swiggy Instamart raised the most?" == res.resolved_question


# 6. 'that company' resolves correctly when unambiguous
def test_that_company_resolves_correctly(temp_memory_store: EntityMemoryStore):
    session_id = "session_single_company"
    temp_memory_store.save_entity("CaratLane", "jewellery_retail")

    temp_memory_store.record_question(
        session_id=session_id,
        raw_question="Tell me about CaratLane",
        resolved_question="Tell me about CaratLane",
        entities=["CaratLane"],
    )

    res = temp_memory_store.resolve_references(session_id, "When was that company founded?")
    assert res.clarification_required is False
    assert res.resolved_question == "When was CaratLane founded?"


# 7. Person/entity relationship can be followed
def test_person_entity_relationship_followed(temp_memory_store: EntityMemoryStore):
    session_id = "session_relationship"
    temp_memory_store.save_entity("Blinkit", "quick_commerce")
    temp_memory_store.save_relationship(
        subject_entity="Sajid Rahman",
        relation="head_of_engineering_at",
        object_entity="Blinkit",
        source_url="https://example.com/blinkit-team",
    )

    temp_memory_store.record_question(
        session_id=session_id,
        raw_question="Who is leading tech at Blinkit?",
        resolved_question="Who is leading tech at Blinkit?",
        entities=["Blinkit"],
    )

    res = temp_memory_store.resolve_references(session_id, "Where did he work before?")
    assert res.clarification_required is False
    assert "Sajid Rahman" in res.resolved_question


# 8. Unknown pronoun/reference does not cause a hallucinated entity
def test_unknown_pronoun_reference_does_not_hallucinate(temp_memory_store: EntityMemoryStore):
    empty_session = "fresh_empty_session"
    res = temp_memory_store.resolve_references(empty_session, "Which of them raised funding?")
    # Must NOT guess or inject random entities
    assert res.clarification_required is True
    assert res.clarification_message is not None
    assert len(res.entities_detected) == 0


# 9. A new session does not accidentally inherit another session's context
def test_new_session_isolated_context(temp_memory_store: EntityMemoryStore):
    session_a = "session_A"
    session_b = "session_B"

    # Populate session A
    temp_memory_store.record_question(session_a, "Who runs Zepto?", "Who runs Zepto?", ["Zepto"])

    # Query session B with anaphoric reference
    res_b = temp_memory_store.resolve_references(session_b, "What did that company raise?")
    assert res_b.clarification_required is True
    assert "Zepto" not in res_b.entities_detected


# 10. Memory facts retain their source URL and metadata
def test_memory_facts_retain_source_url(temp_memory_store: EntityMemoryStore):
    url = "https://techcrunch.com/2024/06/zepto-funding"
    temp_memory_store.save_fact(
        entity_name="Zepto",
        attribute="funding_amount",
        value="$665M",
        source_url=url,
        source_title="Zepto raises $665M",
        fact_date="June 2024",
    )

    facts = temp_memory_store.get_facts_for_entity("Zepto")
    assert len(facts) == 1
    assert facts[0].source_url == url
    assert facts[0].source_title == "Zepto raises $665M"
    assert facts[0].fact_date == "June 2024"
    assert facts[0].discovered_at != ""


# 11. Auditor does not treat SQLite memory as independent evidence
@pytest.mark.asyncio
async def test_auditor_does_not_treat_sqlite_as_evidence(temp_memory_store: EntityMemoryStore):
    # Setup memory with a fact
    temp_memory_store.save_fact("Zepto", "funding", "$665M", "https://example.com/dead-link")

    auditor = AuditorAgent()

    # Mock fetcher returning 404 (inaccessible source)
    mock_404 = FetchResult(
        url="https://example.com/dead-link",
        status="NOT_FOUND_404",
        status_code=404,
        error_message="Page not found",
    )

    with patch.object(auditor.fetcher, "fetch_multiple", new_callable=AsyncMock) as mock_fetch:
        mock_fetch.return_value = [mock_404]

        # Auditor checks claim citing the dead link
        report = await auditor.audit_answer(
            draft_answer="Zepto raised $665M [1]",
            atomic_claims=[{"claim": "Zepto raised $665M", "url": "https://example.com/dead-link"}],
        )

        # The claim MUST be marked UNVERIFIABLE (not SUPPORTED by SQLite memory)
        assert len(report.audit_records) == 1
        assert report.audit_records[0].verdict in ("UNVERIFIABLE", "UNSUPPORTED")
        assert "cannot be accessed" in report.audit_records[0].auditor_explanation or "failed to load" in report.audit_records[0].auditor_explanation


# 12. SQLite FTS5 BM25 topic search and ranking
def test_fts5_knowledge_insertion_and_bm25_search(temp_memory_store: EntityMemoryStore):
    temp_memory_store.save_knowledge_snippet(
        session_id="test_fts_session",
        topic_or_entity="Blinkit",
        finding_snippet="Blinkit expanded 100 new dark stores in southern India focusing on fresh grocery delivery",
        source_url="https://example.com/blinkit-darkstores",
        source_title="Blinkit Dark Stores Expansion",
        fact_date="2024",
    )
    temp_memory_store.save_knowledge_snippet(
        session_id="test_fts_session",
        topic_or_entity="Zepto",
        finding_snippet="Zepto piloted delivery of electronics and smartphone accessories in 10 minutes",
        source_url="https://example.com/zepto-electronics",
        source_title="Zepto Electronics Pilot",
        fact_date="2024",
    )

    # BM25 Search for dark stores
    results = temp_memory_store.search_knowledge_fts("dark stores grocery", session_id="test_fts_session")
    assert len(results) >= 1
    assert results[0].topic_or_entity == "Blinkit"
    assert "grocery" in results[0].finding_snippet
    assert results[0].source_url == "https://example.com/blinkit-darkstores"
    assert results[0].score is not None


# 13. SQLite FTS5 Porter Stemming (e.g. 'regulatory' -> 'regulations')
def test_fts5_porter_stemming(temp_memory_store: EntityMemoryStore):
    temp_memory_store.save_knowledge_snippet(
        session_id="stemming_session",
        topic_or_entity="Quick Commerce Regulations",
        finding_snippet="Quick commerce startups are navigating municipal regulations regarding commercial vehicle parking",
        source_url="https://example.com/regulations",
    )

    # Query with morphological variations ('regulatory vehicles')
    results = temp_memory_store.search_knowledge_fts("regulatory vehicles", session_id="stemming_session")
    assert len(results) >= 1
    assert "regulations" in results[0].finding_snippet


# 14. FTS5 integration with resolve_references for conceptual follow-ups
def test_fts5_integration_with_resolve_references(temp_memory_store: EntityMemoryStore):
    session_id = "session_topic_followup"
    temp_memory_store.save_knowledge_snippet(
        session_id=session_id,
        topic_or_entity="Zoning Laws",
        finding_snippet="Municipal authorities issued zoning restrictions for dark store warehouses in Bengaluru",
        source_url="https://example.com/bengaluru-zoning",
        fact_date="August 2024",
    )

    # Conceptual follow-up without explicit company names
    res = temp_memory_store.resolve_references(session_id, "What did we learn about dark store zoning restrictions?")
    assert len(res.facts_retrieved) >= 1
    fts_fact = next((f for f in res.facts_retrieved if f.get("attribute") == "fts5_knowledge_snippet"), None)
    assert fts_fact is not None
    assert fts_fact["source_url"] == "https://example.com/bengaluru-zoning"
    assert "zoning restrictions" in fts_fact["value"]

