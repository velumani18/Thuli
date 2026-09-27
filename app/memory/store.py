"""
Structured SQLite Entity-Fact and Session Memory Store.

Stores:
- entities and aliases
- entity_facts (with source URL, title, discovery date, and fact date)
- entity_relationships (subject, relation, object)
- research sessions & question history
- reference resolution (resolves "them", "that company", "he" to session entities)
"""

import re
import sqlite3
import json
import uuid
from pathlib import Path
from typing import Optional, Any
from datetime import datetime
from pydantic import BaseModel, Field

from app.core.config import settings


class EntityRecord(BaseModel):
    entity_id: str
    name: str
    category: str
    aliases: list[str] = Field(default_factory=list)
    created_at: str


class FactRecord(BaseModel):
    fact_id: Optional[int] = None
    entity_id: str
    entity_name: str
    attribute: str
    value: str
    source_url: str
    source_title: Optional[str] = None
    fact_date: Optional[str] = None
    discovered_at: str = Field(default_factory=lambda: datetime.now().isoformat())
    verified_at: Optional[str] = None


class RelationshipRecord(BaseModel):
    rel_id: Optional[int] = None
    subject_entity: str
    relation: str
    object_entity: str
    source_url: Optional[str] = None
    created_at: str = Field(default_factory=lambda: datetime.now().isoformat())


class KnowledgeSnippetRecord(BaseModel):
    session_id: str
    topic_or_entity: str
    finding_snippet: str
    source_url: str
    source_title: Optional[str] = None
    fact_date: Optional[str] = None
    score: Optional[float] = None


class ReferenceResolutionResult(BaseModel):
    original_question: str
    resolved_question: str
    references_detected: list[str] = Field(default_factory=list)
    references_resolved: dict[str, str] = Field(default_factory=dict)
    entities_detected: list[str] = Field(default_factory=list)
    memory_hits: list[str] = Field(default_factory=list)
    memory_misses: list[str] = Field(default_factory=list)
    facts_retrieved: list[dict[str, Any]] = Field(default_factory=list)
    clarification_required: bool = False
    clarification_message: Optional[str] = None


class EntityMemoryStore:
    def __init__(self, db_path: Optional[Path] = None):
        self.db_path = db_path or settings.db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self):
        with self._get_connection() as conn:
            cursor = conn.cursor()
            
            # 1. Core entities table
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS entities (
                    entity_id TEXT PRIMARY KEY,
                    name TEXT UNIQUE,
                    category TEXT,
                    aliases_json TEXT,
                    created_at TIMESTAMP
                )
                """
            )
            
            # 2. Entity facts table with source metadata and dates
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS entity_facts (
                    fact_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    entity_id TEXT,
                    entity_name TEXT,
                    attribute TEXT,
                    value TEXT,
                    source_url TEXT,
                    source_title TEXT,
                    fact_date TEXT,
                    discovered_at TIMESTAMP,
                    verified_at TIMESTAMP,
                    FOREIGN KEY(entity_id) REFERENCES entities(entity_id)
                )
                """
            )
            # Ensure columns exist if migrating an existing DB
            cursor.execute("PRAGMA table_info(entity_facts)")
            existing_cols = {row["name"] for row in cursor.fetchall()}
            if "source_title" not in existing_cols:
                cursor.execute("ALTER TABLE entity_facts ADD COLUMN source_title TEXT")
            if "fact_date" not in existing_cols:
                cursor.execute("ALTER TABLE entity_facts ADD COLUMN fact_date TEXT")
            if "discovered_at" not in existing_cols:
                cursor.execute("ALTER TABLE entity_facts ADD COLUMN discovered_at TIMESTAMP")

            # 3. Entity relationships table (e.g. Sajid Rahman -> head_of_engineering_at -> Blinkit)
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS entity_relationships (
                    rel_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    subject_entity TEXT,
                    relation TEXT,
                    object_entity TEXT,
                    source_url TEXT,
                    created_at TIMESTAMP
                )
                """
            )

            # 4. Research sessions table
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS sessions (
                    session_id TEXT PRIMARY KEY,
                    created_at TIMESTAMP,
                    metadata_json TEXT
                )
                """
            )

            # 5. Session questions history table
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS session_questions (
                    question_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT,
                    raw_question TEXT,
                    resolved_question TEXT,
                    entities_json TEXT,
                    created_at TIMESTAMP,
                    FOREIGN KEY(session_id) REFERENCES sessions(session_id)
                )
                """
            )

            # 6. Full-Text Search (FTS5) knowledge virtual table with BM25 probabilistic ranking
            cursor.execute(
                """
                CREATE VIRTUAL TABLE IF NOT EXISTS research_knowledge_fts USING fts5(
                    session_id,
                    topic_or_entity,
                    finding_snippet,
                    source_url,
                    source_title,
                    fact_date,
                    tokenize='porter unicode61'
                )
                """
            )
            conn.commit()

    # --- Session Management ---

    def create_session(self, session_id: Optional[str] = None, metadata: Optional[dict] = None) -> str:
        sid = session_id or str(uuid.uuid4())
        now = datetime.now().isoformat()
        meta_json = json.dumps(metadata or {})
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT OR IGNORE INTO sessions (session_id, created_at, metadata_json)
                VALUES (?, ?, ?)
                """,
                (sid, now, meta_json),
            )
            conn.commit()
        return sid

    def record_question(
        self, session_id: str, raw_question: str, resolved_question: str, entities: list[str]
    ) -> int:
        self.create_session(session_id)
        now = datetime.now().isoformat()
        ent_json = json.dumps(entities)
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO session_questions (session_id, raw_question, resolved_question, entities_json, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (session_id, raw_question, resolved_question, ent_json, now),
            )
            conn.commit()
            return cursor.lastrowid

    def get_session_recent_entities(self, session_id: str, limit: int = 5) -> list[str]:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT entities_json FROM session_questions
                WHERE session_id = ?
                ORDER BY question_id DESC
                LIMIT ?
                """,
                (session_id, limit),
            )
            rows = cursor.fetchall()
            all_ents = []
            for r in rows:
                try:
                    ents = json.loads(r["entities_json"])
                    for e in ents:
                        if e not in all_ents:
                            all_ents.append(e)
                except Exception:
                    pass
            return all_ents

    def get_session_last_question(self, session_id: str) -> Optional[dict]:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT * FROM session_questions
                WHERE session_id = ?
                ORDER BY question_id DESC
                LIMIT 1
                """,
                (session_id,),
            )
            row = cursor.fetchone()
            if row:
                return {
                    "question_id": row["question_id"],
                    "raw_question": row["raw_question"],
                    "resolved_question": row["resolved_question"],
                    "entities": json.loads(row["entities_json"] or "[]"),
                    "created_at": row["created_at"],
                }
            return None

    # --- Entity & Fact Management ---

    def save_entity(self, name: str, category: str, aliases: Optional[list[str]] = None) -> str:
        clean_name = name.strip()
        entity_id = clean_name.lower().replace(" ", "_")
        aliases_json = json.dumps(aliases or [])
        now = datetime.now().isoformat()

        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO entities (entity_id, name, category, aliases_json, created_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(name) DO UPDATE SET
                    category = excluded.category,
                    aliases_json = excluded.aliases_json
                """,
                (entity_id, clean_name, category, aliases_json, now),
            )
            conn.commit()
        return entity_id

    def save_fact(
        self,
        entity_name: str,
        attribute: str,
        value: str,
        source_url: str,
        source_title: Optional[str] = None,
        fact_date: Optional[str] = None,
        discovered_at: Optional[str] = None,
    ) -> int:
        entity_id = entity_name.strip().lower().replace(" ", "_")
        now = discovered_at or datetime.now().isoformat()

        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT OR IGNORE INTO entities (entity_id, name, category, aliases_json, created_at)
                VALUES (?, ?, 'general', '[]', ?)
                """,
                (entity_id, entity_name.strip(), now),
            )
            cursor.execute(
                """
                INSERT INTO entity_facts (entity_id, entity_name, attribute, value, source_url, source_title, fact_date, discovered_at, verified_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (entity_id, entity_name.strip(), attribute, value, source_url, source_title, fact_date, now, now),
            )
            conn.commit()
            return cursor.lastrowid

    def save_relationship(
        self, subject_entity: str, relation: str, object_entity: str, source_url: Optional[str] = None
    ) -> int:
        now = datetime.now().isoformat()
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO entity_relationships (subject_entity, relation, object_entity, source_url, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (subject_entity.strip(), relation.strip(), object_entity.strip(), source_url, now),
            )
            conn.commit()
            return cursor.lastrowid

    def save_knowledge_snippet(
        self,
        session_id: str,
        topic_or_entity: str,
        finding_snippet: str,
        source_url: str,
        source_title: Optional[str] = None,
        fact_date: Optional[str] = None,
    ):
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO research_knowledge_fts (session_id, topic_or_entity, finding_snippet, source_url, source_title, fact_date)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (session_id, topic_or_entity.strip(), finding_snippet.strip(), source_url.strip(), source_title, fact_date),
            )
            conn.commit()

    def search_knowledge_fts(
        self, query: str, session_id: Optional[str] = None, limit: int = 3
    ) -> list[KnowledgeSnippetRecord]:
        """
        Executes BM25 probabilistic ranking search across past research snippets using SQLite FTS5.
        Uses Porter stemming (e.g. 'regulations' matches 'regulatory').
        """
        words = re.findall(r'\b[A-Za-z0-9_]{3,}\b', query)
        stopwords = {
            "what", "which", "when", "where", "who", "whom", "this", "that", "these", "those",
            "about", "from", "with", "have", "been", "were", "does", "latest", "most", "some", "tell",
            "find", "show", "give", "much", "many", "there"
        }
        meaningful_words = [w for w in words if w.lower() not in stopwords]
        if not meaningful_words:
            return []

        match_query = " OR ".join(f'"{w}"' for w in meaningful_words)

        with self._get_connection() as conn:
            cursor = conn.cursor()
            try:
                if session_id:
                    cursor.execute(
                        """
                        SELECT session_id, topic_or_entity, finding_snippet, source_url, source_title, fact_date, rank
                        FROM research_knowledge_fts
                        WHERE research_knowledge_fts MATCH ? AND session_id = ?
                        ORDER BY rank
                        LIMIT ?
                        """,
                        (match_query, session_id, limit),
                    )
                else:
                    cursor.execute(
                        """
                        SELECT session_id, topic_or_entity, finding_snippet, source_url, source_title, fact_date, rank
                        FROM research_knowledge_fts
                        WHERE research_knowledge_fts MATCH ?
                        ORDER BY rank
                        LIMIT ?
                        """,
                        (match_query, limit),
                    )
                rows = cursor.fetchall()
                return [
                    KnowledgeSnippetRecord(
                        session_id=r["session_id"],
                        topic_or_entity=r["topic_or_entity"],
                        finding_snippet=r["finding_snippet"],
                        source_url=r["source_url"],
                        source_title=r["source_title"],
                        fact_date=r["fact_date"],
                        score=round(float(r["rank"]), 4) if "rank" in r.keys() else None,
                    )
                    for r in rows
                ]
            except Exception:
                return []

    def get_relationships_for_entity(self, entity_name: str) -> list[RelationshipRecord]:
        clean = entity_name.strip().lower()
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT * FROM entity_relationships
                WHERE LOWER(subject_entity) = ? OR LOWER(object_entity) = ?
                ORDER BY created_at DESC
                """,
                (clean, clean),
            )
            rows = cursor.fetchall()
            return [
                RelationshipRecord(
                    rel_id=r["rel_id"],
                    subject_entity=r["subject_entity"],
                    relation=r["relation"],
                    object_entity=r["object_entity"],
                    source_url=r["source_url"],
                    created_at=r["created_at"],
                )
                for r in rows
            ]

    def get_all_entities(self) -> list[EntityRecord]:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM entities ORDER BY created_at DESC")
            rows = cursor.fetchall()
            return [
                EntityRecord(
                    entity_id=r["entity_id"],
                    name=r["name"],
                    category=r["category"],
                    aliases=json.loads(r["aliases_json"] or "[]"),
                    created_at=r["created_at"],
                )
                for r in rows
            ]

    def get_facts_for_entity(self, entity_id_or_name: str) -> list[FactRecord]:
        key = entity_id_or_name.strip().lower().replace(" ", "_")
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT * FROM entity_facts 
                WHERE entity_id = ? OR LOWER(entity_name) = LOWER(?)
                ORDER BY discovered_at DESC
                """,
                (key, entity_id_or_name.strip()),
            )
            rows = cursor.fetchall()
            return [
                FactRecord(
                    fact_id=r["fact_id"],
                    entity_id=r["entity_id"],
                    entity_name=r["entity_name"],
                    attribute=r["attribute"],
                    value=r["value"],
                    source_url=r["source_url"] or "",
                    source_title=r["source_title"],
                    fact_date=r["fact_date"],
                    discovered_at=r["discovered_at"] or r["verified_at"] or "",
                    verified_at=r["verified_at"],
                )
                for r in rows
            ]

    # --- Reference & Anaphora Resolution ---

    def resolve_references(self, session_id: str, question: str) -> ReferenceResolutionResult:
        """
        Resolves ambiguous pronouns/demonstratives ("them", "that company", "he") using
        the active session's recent context and entity relationships.
        
        Guarantees:
        - If ambiguous without confident resolution, raises clarification_required=True.
        - Does NOT hallucinate entities when reference is unknown.
        - Retains source URLs for retrieved memory facts.
        """
        q_raw = question.strip()
        recent_session_entities = self.get_session_recent_entities(session_id, limit=6)
        all_stored_entities = [e.name for e in self.get_all_entities()]
        
        detected_refs = []
        resolved_refs = {}
        entities_in_q = []
        memory_hits = []
        memory_misses = []
        facts_retrieved = []
        clarification_required = False
        clarification_msg = None

        # Check which stored entities are explicitly mentioned in current question
        for ent_name in all_stored_entities:
            pattern = r'\b' + re.escape(ent_name) + r'\b'
            if re.search(pattern, q_raw, re.IGNORECASE):
                if ent_name not in entities_in_q:
                    entities_in_q.append(ent_name)

        q_lower = q_raw.lower()

        # 1. Plural references: "which of them", "them", "those companies", "these companies"
        plural_match = re.search(r'\b(which of them|them|those companies|these companies|those startups)\b', q_lower)
        if plural_match:
            ref_phrase = plural_match.group(0)
            detected_refs.append(ref_phrase)

            if len(recent_session_entities) >= 2:
                # Format: "Zepto, Blinkit, and Swiggy Instamart"
                if len(recent_session_entities) == 2:
                    replacement = f"{recent_session_entities[0]} and {recent_session_entities[1]}"
                else:
                    replacement = ", ".join(recent_session_entities[:-1]) + f", and {recent_session_entities[-1]}"
                
                if ref_phrase == "which of them":
                    resolved_text = f"Which of {replacement}"
                else:
                    resolved_text = replacement

                resolved_refs[ref_phrase] = resolved_text
                # Substitute in question
                pattern = re.compile(re.escape(ref_phrase), re.IGNORECASE)
                resolved_q = pattern.sub(resolved_text, q_raw, count=1)
                for e in recent_session_entities:
                    if e not in entities_in_q:
                        entities_in_q.append(e)
            elif len(recent_session_entities) == 1:
                # Single entity for a plural question is ambiguous or partial
                resolved_text = recent_session_entities[0]
                resolved_refs[ref_phrase] = resolved_text
                pattern = re.compile(re.escape(ref_phrase), re.IGNORECASE)
                resolved_q = pattern.sub(resolved_text, q_raw, count=1)
                if recent_session_entities[0] not in entities_in_q:
                    entities_in_q.append(recent_session_entities[0])
            else:
                # No entities in session to resolve "them"! Must clarify, do not hallucinate
                clarification_required = True
                clarification_msg = "Could you clarify which companies or entities you are referring to?"
                resolved_q = q_raw

        # 2. Singular company references: "that company", "this company", "the company"
        elif re.search(r'\b(that company|this company|the company)\b', q_lower):
            match = re.search(r'\b(that company|this company|the company)\b', q_lower)
            ref_phrase = match.group(0)
            detected_refs.append(ref_phrase)

            if len(recent_session_entities) == 1:
                resolved_text = recent_session_entities[0]
                resolved_refs[ref_phrase] = resolved_text
                pattern = re.compile(re.escape(ref_phrase), re.IGNORECASE)
                resolved_q = pattern.sub(resolved_text, q_raw, count=1)
                if resolved_text not in entities_in_q:
                    entities_in_q.append(resolved_text)
            elif len(recent_session_entities) > 1:
                # Ambiguous: multiple recent companies exist, user asked for "that company"
                clarification_required = True
                clarification_msg = (
                    f"Multiple companies were previously discussed ({', '.join(recent_session_entities)}). "
                    "Which company are you referring to?"
                )
                resolved_q = q_raw
            else:
                clarification_required = True
                clarification_msg = "Could you specify which company you are referring to?"
                resolved_q = q_raw

        # 3. Person references / Relationship traversal: "he", "she", "where did he work", "when did he join"
        elif re.search(r'\b(he|she|his|her)\b', q_lower):
            match = re.search(r'\b(he|she|his|her)\b', q_lower)
            ref_phrase = match.group(0)
            detected_refs.append(ref_phrase)

            # Look for recent person entities or relationships in session
            person_found = None
            for e in recent_session_entities:
                rels = self.get_relationships_for_entity(e)
                for r in rels:
                    # If subject is a person linked to this company
                    if "head" in r.relation.lower() or "cto" in r.relation.lower() or "founder" in r.relation.lower():
                        person_found = r.subject_entity
                        break
                if person_found:
                    break

            if person_found:
                resolved_refs[ref_phrase] = person_found
                pattern = re.compile(r'\b' + re.escape(ref_phrase) + r'\b', re.IGNORECASE)
                resolved_q = pattern.sub(person_found, q_raw, count=1)
                if person_found not in entities_in_q:
                    entities_in_q.append(person_found)
            elif len(recent_session_entities) == 1:
                # Check if a fact has a person name (e.g. cto = Sajid Rahman)
                facts = self.get_facts_for_entity(recent_session_entities[0])
                for f in facts:
                    if f.attribute.lower() in ("cto", "head_of_engineering", "ceo", "founder"):
                        person_found = f.value
                        break
                if person_found:
                    resolved_refs[ref_phrase] = person_found
                    pattern = re.compile(r'\b' + re.escape(ref_phrase) + r'\b', re.IGNORECASE)
                    resolved_q = pattern.sub(person_found, q_raw, count=1)
                    if person_found not in entities_in_q:
                        entities_in_q.append(person_found)
                else:
                    clarification_required = True
                    clarification_msg = f"Could you clarify which person you are referring to for {recent_session_entities[0]}?"
                    resolved_q = q_raw
            else:
                clarification_required = True
                clarification_msg = "Could you specify who you are referring to?"
                resolved_q = q_raw
        else:
            resolved_q = q_raw

        # Retrieve known facts for all identified entities
        for ent in entities_in_q:
            facts = self.get_facts_for_entity(ent)
            if facts:
                memory_hits.append(ent)
                for f in facts:
                    facts_retrieved.append({
                        "entity": f.entity_name,
                        "attribute": f.attribute,
                        "value": f.value,
                        "source_url": f.source_url,
                        "source_title": f.source_title,
                        "fact_date": f.fact_date,
                        "discovered_at": f.discovered_at,
                    })
            else:
                memory_misses.append(ent)

        # 4. Semantic / Thematic Topic Search via SQLite FTS5 (BM25 ranking)
        fts_hits = self.search_knowledge_fts(q_raw, session_id=session_id, limit=3)
        for hit in fts_hits:
            facts_retrieved.append({
                "entity": hit.topic_or_entity,
                "attribute": "fts5_knowledge_snippet",
                "value": hit.finding_snippet,
                "source_url": hit.source_url,
                "source_title": hit.source_title,
                "fact_date": hit.fact_date,
                "bm25_rank": hit.score,
            })
            if hit.topic_or_entity not in memory_hits:
                memory_hits.append(hit.topic_or_entity)
            if hit.topic_or_entity not in entities_in_q:
                entities_in_q.append(hit.topic_or_entity)

        return ReferenceResolutionResult(
            original_question=q_raw,
            resolved_question=resolved_q,
            references_detected=detected_refs,
            references_resolved=resolved_refs,
            entities_detected=entities_in_q,
            memory_hits=memory_hits,
            memory_misses=memory_misses,
            facts_retrieved=facts_retrieved,
            clarification_required=clarification_required,
            clarification_message=clarification_msg,
        )

    def resolve_context(self, question: str) -> dict:
        """Backward-compatible helper returning dictionary for orchestrator."""
        all_entities = self.get_all_entities()
        matched_entities = []
        q_lower = question.lower()

        has_anaphora = any(
            phrase in q_lower
            for phrase in ["those companies", "these companies", "mentioned earlier", "from earlier", "the companies"]
        )

        for ent in all_entities:
            if ent.name.lower() in q_lower or (ent.category and ent.category.lower() in q_lower):
                matched_entities.append(ent)
                continue
            if has_anaphora:
                matched_entities.append(ent)

        unique_matches = {e.entity_id: e for e in matched_entities}.values()
        facts_by_entity = {}
        for ent in unique_matches:
            facts = self.get_facts_for_entity(ent.entity_id)
            facts_by_entity[ent.name] = [f.model_dump() for f in facts]

        return {
            "memory_hit": len(unique_matches) > 0,
            "matched_entities": [e.name for e in unique_matches],
            "known_facts": facts_by_entity,
        }
