"""
facTrack - Evidence-First Web Research Agent with Independent Claim Verification.
Interactive Streamlit Dashboard.
"""

import sys
import asyncio
import json
import time
import subprocess
from pathlib import Path

# Ensure project root is in sys.path when executed via streamlit
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import os
import streamlit as st
import pandas as pd

from app.core.config import settings
from app.core.telemetry import RunLogRecord
from app.orchestrator import ResearchOrchestrator
from app.memory.store import EntityMemoryStore
from scripts.run_eval import EVAL_QUESTIONS

st.set_page_config(
    page_title="facTrack | Evidence-First Research Agent",
    page_icon="🛡️",
    layout="wide",
    initial_sidebar_state="expanded",
)

# Cohesive Dark Obsidian Theme - Eliminates Split Black/White Panels
st.markdown(
    """
    <style>
    @import url('https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@300;400;500;600;700;800&family=JetBrains+Mono:wght@400;500;600&display=swap');

    html, body, [class*="css"] {
        font-family: 'Plus Jakarta Sans', sans-serif;
    }
    
    code, pre, .mono-text {
        font-family: 'JetBrains Mono', monospace !important;
    }

    /* Unified Seamless Dark Background for Main App, Header, and Sidebar */
    .stApp, 
    header[data-testid="stHeader"], 
    section[data-testid="stSidebar"],
    div[data-testid="stToolbar"] {
        background-color: #080b14 !important;
        background-image: radial-gradient(circle at 15% 15%, #0f172a 0%, #06080f 90%) !important;
        color: #f1f5f9 !important;
    }

    section[data-testid="stSidebar"] {
        border-right: 1px solid rgba(255, 255, 255, 0.08) !important;
    }

    section[data-testid="stSidebar"] * {
        color: #e2e8f0 !important;
    }

    /* Hero Banner */
    .hero-container {
        padding: 26px 30px;
        background: linear-gradient(135deg, rgba(30, 41, 59, 0.6) 0%, rgba(15, 23, 42, 0.8) 100%);
        border: 1px solid rgba(56, 189, 248, 0.2);
        border-radius: 16px;
        backdrop-filter: blur(12px);
        margin-bottom: 24px;
        box-shadow: 0 12px 36px rgba(0, 0, 0, 0.45);
    }

    .brand-title {
        font-size: 2.6rem;
        font-weight: 800;
        letter-spacing: -0.03em;
        background: linear-gradient(135deg, #38bdf8 0%, #818cf8 50%, #c084fc 100%);
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
        margin: 0;
        display: inline-block;
    }

    .brand-badge {
        display: inline-block;
        padding: 4px 12px;
        border-radius: 20px;
        font-size: 0.74rem;
        font-weight: 700;
        text-transform: uppercase;
        letter-spacing: 0.08em;
        background: rgba(56, 189, 248, 0.16);
        color: #38bdf8;
        border: 1px solid rgba(56, 189, 248, 0.35);
        margin-left: 12px;
        vertical-align: middle;
    }

    .brand-tagline {
        font-size: 1.08rem;
        color: #94a3b8;
        margin-top: 6px;
        font-weight: 500;
    }

    /* High-Contrast Search Textarea */
    .stTextArea textarea {
        background-color: #0f172a !important;
        color: #ffffff !important;
        font-size: 16px !important;
        font-weight: 500 !important;
        border: 2px solid #334155 !important;
        border-radius: 12px !important;
        padding: 14px 16px !important;
        line-height: 1.6 !important;
        transition: border-color 0.2s ease, box-shadow 0.2s ease !important;
    }

    .stTextArea textarea:focus {
        border-color: #38bdf8 !important;
        box-shadow: 0 0 0 3px rgba(56, 189, 248, 0.25) !important;
    }

    /* Primary Execution Button */
    .stButton > button[kind="primary"] {
        background: linear-gradient(135deg, #3b82f6 0%, #1d4ed8 100%) !important;
        color: #ffffff !important;
        font-weight: 700 !important;
        font-size: 15px !important;
        border: 1px solid rgba(255, 255, 255, 0.15) !important;
        border-radius: 10px !important;
        padding: 10px 20px !important;
        box-shadow: 0 4px 16px rgba(37, 99, 235, 0.35) !important;
        transition: all 0.2s ease !important;
    }

    .stButton > button[kind="primary"]:hover {
        background: linear-gradient(135deg, #60a5fa 0%, #2563eb 100%) !important;
        box-shadow: 0 6px 22px rgba(37, 99, 235, 0.55) !important;
        transform: translateY(-1px) !important;
    }

    /* Standard Button */
    .stButton > button {
        background-color: #1e293b !important;
        color: #f1f5f9 !important;
        border: 1px solid #334155 !important;
        border-radius: 8px !important;
        font-weight: 600 !important;
        font-size: 13px !important;
    }

    .stButton > button:hover {
        background-color: #334155 !important;
        color: #38bdf8 !important;
        border-color: #38bdf8 !important;
    }

    /* Navigation Tabs */
    button[data-baseweb="tab"] {
        color: #cbd5e1 !important;
        font-weight: 600 !important;
        font-size: 14px !important;
        padding: 10px 18px !important;
        background: transparent !important;
    }

    button[data-baseweb="tab"][aria-selected="true"] {
        color: #38bdf8 !important;
        border-bottom: 3px solid #38bdf8 !important;
    }

    /* Cards & Containers */
    .glass-card {
        background: rgba(30, 41, 59, 0.5);
        border: 1px solid rgba(255, 255, 255, 0.08);
        border-radius: 12px;
        padding: 18px;
        backdrop-filter: blur(8px);
        margin-bottom: 16px;
    }

    /* Evidence Card */
    .evidence-card {
        background: rgba(15, 23, 42, 0.85);
        border: 1px solid rgba(255, 255, 255, 0.1);
        border-radius: 10px;
        padding: 16px;
        margin-bottom: 14px;
        transition: border-color 0.2s ease;
    }
    .evidence-card:hover {
        border-color: rgba(56, 189, 248, 0.35);
    }

    /* Metric Tiles */
    div[data-testid="stMetric"] {
        background: linear-gradient(135deg, rgba(30, 41, 59, 0.6) 0%, rgba(15, 23, 42, 0.8) 100%) !important;
        border: 1px solid rgba(255, 255, 255, 0.1) !important;
        border-radius: 12px !important;
        padding: 12px 16px !important;
    }
    div[data-testid="stMetric"] label {
        color: #94a3b8 !important;
        font-weight: 600 !important;
        font-size: 0.85rem !important;
    }
    div[data-testid="stMetric"] div[data-testid="stMetricValue"] {
        color: #ffffff !important;
        font-weight: 800 !important;
    }

    /* Stepper */
    .step-track {
        display: flex;
        justify-content: space-between;
        margin: 16px 0;
        background: rgba(15, 23, 42, 0.7);
        border: 1px solid rgba(255, 255, 255, 0.08);
        border-radius: 10px;
        padding: 12px 16px;
    }
    .step-node {
        display: flex;
        align-items: center;
        font-size: 0.85rem;
        font-weight: 600;
        color: #cbd5e1;
    }
    .step-node.active {
        color: #38bdf8;
    }
    .step-num {
        width: 24px;
        height: 24px;
        border-radius: 50%;
        background: rgba(255, 255, 255, 0.12);
        display: flex;
        align-items: center;
        justify-content: center;
        margin-right: 8px;
        font-size: 0.75rem;
    }
    .step-node.active .step-num {
        background: #38bdf8;
        color: #030712;
        font-weight: 700;
    }
    </style>
    """,
    unsafe_allow_html=True,
)


@st.cache_resource
def get_orchestrator():
    return ResearchOrchestrator()


orchestrator = get_orchestrator()

# Hero Header
st.markdown(
    f"""
    <div class="hero-container">
        <div>
            <h1 class="brand-title">facTrack</h1>
            <span class="brand-badge">Adversarial Research Agent</span>
        </div>
        <div class="brand-tagline">
            An evidence-first web research agent with independent claim verification.
        </div>
    </div>
    """,
    unsafe_allow_html=True,
)

# Unified Sidebar
with st.sidebar:
    st.markdown("### ⚙️ Engine Telemetry")
    st.markdown(
        f"""
        <div class="glass-card" style="padding: 14px;">
            <div style="font-size: 0.78rem; color: #94a3b8; font-weight: 600;">ACTIVE LLM MODEL</div>
            <div style="font-weight: 800; color: #38bdf8; font-size: 1.05rem; margin-top: 2px;">{settings.llm_model}</div>
            <div style="margin-top: 10px; font-size: 0.78rem; color: #94a3b8; font-weight: 600;">HARD CEILING</div>
            <div style="font-weight: 800; color: #f59e0b; font-size: 1.05rem; margin-top: 2px;">{settings.max_wall_clock_seconds} seconds</div>
            <div style="margin-top: 10px; font-size: 0.78rem; color: #94a3b8; font-weight: 600;">TELEMETRY FX RATE</div>
            <div style="font-weight: 700; color: #cbd5e1; font-size: 0.9rem; margin-top: 2px;">1 USD = ₹{settings.usd_to_inr}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    st.markdown("---")
    st.markdown("### 🧠 SQLite Memory")
    mem_store = EntityMemoryStore()
    entities = mem_store.get_all_entities()
    st.metric("Tracked Entities", len(entities))

    if entities:
        with st.expander("View Stored Entities", expanded=False):
            for e in entities[:10]:
                st.markdown(f"• **{e.name}** (`{e.category}`)")
            if len(entities) > 10:
                st.caption(f"...and {len(entities) - 10} more")

    st.markdown("---")
    st.markdown("### 📜 AI Session Logs")
    if st.button("Export Active AI Session Log", use_container_width=True):
        with st.spinner("Exporting session transcripts..."):
            res = subprocess.run([".\\.venv\\Scripts\\python.exe", "scripts/export_ai_session.py"], capture_output=True, text=True)
            st.success("Session saved to logs/ai_sessions/!")
            st.caption(res.stdout)


# Main Tab Navigation
tab_studio, tab_audit, tab_memory, tab_telemetry, tab_benchmarks = st.tabs([
    "⚡ Research Studio",
    "🛡️ Adversarial Audit",
    "🧠 Knowledge Graph",
    "📊 Telemetry & Latencies",
    "🧪 8-Question Benchmarks",
])


# -----------------------------------------------------------------------------
# TAB 1: RESEARCH STUDIO
# -----------------------------------------------------------------------------
with tab_studio:
    st.markdown("#### Enter Research Question")
    st.caption("Ask any question freely. facTrack will search, fetch parallel primary sources, and independently fact-check every claim.")

    current_val = st.session_state.get(
        "active_query",
        "",
    )
    query_text = st.text_area(
        "Question:",
        value=current_val,
        height=95,
        placeholder="Enter your question here (e.g., Which quick commerce companies operate in India and what are their dark store counts?)...",
        label_visibility="collapsed",
    )

    col_btn, col_info = st.columns([1, 2])
    with col_btn:
        execute_click = st.button("🚀 Run facTrack Research", type="primary", use_container_width=True)
    with col_info:
        st.markdown(
            "<div style='padding: 8px 0; color: #94a3b8; font-size: 0.85rem;'>"
            "Pipeline: Entity Context → Multi-Query Search → Parallel Fetch → Claim-Evidence Mapping → Adversarial Auditor Re-fetch"
            "</div>",
            unsafe_allow_html=True,
        )

    if execute_click and query_text.strip():
        # Pipeline progress stepper visualizer
        st.markdown(
            """
            <div class="step-track">
                <div class="step-node active"><div class="step-num">1</div> Entity Resolution</div>
                <div class="step-node active"><div class="step-num">2</div> Parallel Multi-Fetch</div>
                <div class="step-node active"><div class="step-num">3</div> Claim-Evidence Map</div>
                <div class="step-node active"><div class="step-num">4</div> Independent Re-Fetch</div>
                <div class="step-node active"><div class="step-num">5</div> Verified Synthesis</div>
            </div>
            """,
            unsafe_allow_html=True,
        )

        with st.spinner("facTrack is actively investigating and fact-checking..."):
            record = asyncio.run(orchestrator.execute_question(query_text.strip()))
            st.session_state.latest_record = record

    # Auto-load latest record on startup if not already in session state
    if "latest_record" not in st.session_state:
        import glob
        run_files = sorted(glob.glob(str(settings.runs_log_dir / "*.json")), key=os.path.getmtime, reverse=True)
        if run_files:
            try:
                with open(run_files[0], "r", encoding="utf-8") as f:
                    st.session_state.latest_record = RunLogRecord.model_validate_json(f.read())
            except Exception:
                pass

    # Display Results
    rec = st.session_state.get("latest_record")
    if rec:
        st.markdown("---")
        # Top KPI Metric Cards
        k1, k2, k3, k4, k5 = st.columns(5)
        k1.metric("Execution Time", f"{rec.execution_time_seconds:.2f}s", f"Ceiling: {settings.max_wall_clock_seconds}s")
        k2.metric("Total Tokens", f"{rec.total_tokens:,}")
        k3.metric("Estimated Cost", f"₹{rec.cost_inr:.4f}", f"${rec.cost_usd:.5f}")
        k4.metric("Evidence Coverage", f"{rec.claims_with_evidence}/{rec.number_of_claims} Claims")
        k5.metric("Verified Claims", f"{rec.final_verified_claims}", "Supported")

        # Verified Final Answer Card
        st.markdown("### 📋 Final Verified Answer")
        if rec.correction_triggered:
            st.warning("⚠️ **Correction Triggered:** The Auditor detected unverified assertions in the preliminary draft. An amended answer was synthesized.")

        # Render rich markdown directly with tables, headers, and clickable citations
        st.markdown(rec.final_verified_answer)

        # Grounded Evidence & Citations Section with Distinct Auditor Panels
        st.markdown("### 🛡️ Verified Evidence Matrix & Auditor Dossier")

        if rec.number_of_claims == 0 or not rec.audit_records:
            st.warning(
                "⚠️ **No Primary Sources Found With Proper Citations.**\n\n"
                "facTrack enforces an evidence-first research policy. Because no primary web sources could be accessed or retrieved for this query, "
                "no ungrounded factual assertions were accepted into the final answer."
            )
        else:
            import urllib.parse
            total_claims = len(rec.audit_records)
            unique_domains = len(set(
                urllib.parse.urlparse(a.cited_url).netloc.replace("www.", "")
                for a in rec.audit_records if a.cited_url
            ))
            supported_count = rec.number_supported

            # Evidence Overview Metrics Bar
            m_col1, m_col2, m_col3 = st.columns(3)
            m_col1.metric("Audited Evidence Panels", f"{total_claims} Panels", "Target: ≥ 5 Claims")
            m_col2.metric("Primary Web Publishers", f"{unique_domains} Unique Domains", "Cross-Corroboration")
            m_col3.metric("Auditor Agreement", f"{supported_count}/{total_claims} Verified", f"{(supported_count/max(1, total_claims)*100):.0f}% Match")

            st.caption("Inspect live primary source excerpts alongside the Auditor Agent's independent adversarial cross-examinations:")

            # View Mode Selector
            view_mode = st.radio(
                "Evidence Display Mode:",
                ["🗂️ Interactive Auditor Dossier (Tabbed Panels)", "📋 Expanded Multi-Panel Matrix (All Panels)"],
                horizontal=True,
                index=0,
                help="Toggle between an interactive tabbed dossier or the full multi-panel comparison matrix."
            )

            def _render_single_evidence_panel(audit, idx: int):
                v = audit.verdict
                badge_style = {
                    "SUPPORTED": ("background: #065f46; color: #34d399; border: 1px solid #10b981;", "✅ SUPPORTED"),
                    "CONTRADICTED": ("background: #7f1d1d; color: #f87171; border: 1px solid #ef4444;", "❌ CONTRADICTED"),
                    "UNSUPPORTED": ("background: #78350f; color: #fbbf24; border: 1px solid #f59e0b;", "⚠️ UNSUPPORTED"),
                    "UNVERIFIABLE": ("background: #1e293b; color: #cbd5e1; border: 1px solid #64748b;", "🔒 UNVERIFIABLE"),
                    "NO_CITATION": ("background: #4c1d95; color: #c084fc; border: 1px solid #a855f7;", "🚫 NO CITATION"),
                }.get(v, ("background: #1e293b; color: #94a3b8;", v))

                quote_display = audit.source_snippet_extracted or audit.analyst_evidence or "No direct verbatim quote extracted."
                source_url_display = audit.cited_url or "No URL cited"

                domain_name = "Unknown Source"
                if source_url_display and source_url_display.startswith("http"):
                    domain_name = urllib.parse.urlparse(source_url_display).netloc.replace("www.", "")

                # Render Top Claim Banner
                st.markdown(
                    f"""
                    <div style="background: linear-gradient(135deg, rgba(30, 41, 59, 0.7) 0%, rgba(15, 23, 42, 0.9) 100%); border: 1px solid rgba(255, 255, 255, 0.1); border-left: 5px solid {'#10b981' if v=='SUPPORTED' else '#ef4444' if v=='CONTRADICTED' else '#f59e0b'}; border-radius: 12px; padding: 14px 18px; margin-top: 14px; margin-bottom: 12px;">
                        <div style="display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 10px;">
                            <div>
                                <span style="background: rgba(56, 189, 248, 0.2); color: #38bdf8; padding: 3px 10px; border-radius: 8px; font-size: 0.8rem; font-weight: 800; margin-right: 8px;">PANEL {idx} • {audit.claim_id}</span>
                                <span style="font-weight: 700; font-size: 1.05rem; color: #f8fafc;">{audit.claim_text}</span>
                            </div>
                            <span style="padding: 4px 14px; border-radius: 16px; font-size: 0.82rem; font-weight: 700; {badge_style[0]}">{badge_style[1]}</span>
                        </div>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )

                # Two-Column Sub-Panels: Left = Primary Evidence, Right = Auditor Agent Evaluation
                col_left, col_right = st.columns([1, 1])

                with col_left:
                    st.markdown(
                        f"""
                        <div style="background: rgba(15, 23, 42, 0.8); border: 1px solid rgba(56, 189, 248, 0.2); border-radius: 12px; padding: 16px; height: 100%; min-height: 220px;">
                            <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 10px; border-bottom: 1px solid rgba(255, 255, 255, 0.08); padding-bottom: 8px;">
                                <span style="font-size: 0.82rem; font-weight: 700; color: #38bdf8; text-transform: uppercase; letter-spacing: 0.5px;">📦 Primary Source Evidence</span>
                                <span style="font-size: 0.8rem; color: #94a3b8;">🌐 <b>{domain_name}</b></span>
                            </div>
                            <div style="font-size: 0.84rem; color: #94a3b8; margin-bottom: 8px;">
                                <b>Citation Link:</b> <a href="{source_url_display}" target="_blank" style="color: #60a5fa; text-decoration: underline; word-break: break-all;">{source_url_display} ↗</a>
                            </div>
                            <div style="background: rgba(30, 41, 59, 0.6); border-left: 3px solid #38bdf8; border-radius: 8px; padding: 12px 14px; margin-top: 10px;">
                                <div style="color: #94a3b8; font-size: 0.74rem; font-weight: 700; letter-spacing: 0.5px; margin-bottom: 4px;">📖 VERBATIM EXTRACTED QUOTE:</div>
                                <div style="color: #f1f5f9; font-size: 0.92rem; font-style: italic; line-height: 1.5;">"{quote_display}"</div>
                            </div>
                        </div>
                        """,
                        unsafe_allow_html=True,
                    )

                with col_right:
                    st.markdown(
                        f"""
                        <div style="background: rgba(15, 23, 42, 0.8); border: 1px solid {'rgba(16, 185, 129, 0.3)' if v=='SUPPORTED' else 'rgba(239, 68, 68, 0.3)' if v=='CONTRADICTED' else 'rgba(245, 158, 11, 0.3)'}; border-radius: 12px; padding: 16px; height: 100%; min-height: 220px;">
                            <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 10px; border-bottom: 1px solid rgba(255, 255, 255, 0.08); padding-bottom: 8px;">
                                <span style="font-size: 0.82rem; font-weight: 700; color: {'#34d399' if v=='SUPPORTED' else '#f87171' if v=='CONTRADICTED' else '#fbbf24'}; text-transform: uppercase; letter-spacing: 0.5px;">🛡️ Auditor Adversarial Evaluation</span>
                                <span style="font-size: 0.78rem; font-weight: 700; padding: 2px 8px; border-radius: 8px; {badge_style[0]}">{badge_style[1]}</span>
                            </div>
                            <div style="color: #f8fafc; font-size: 0.92rem; line-height: 1.65; margin-top: 6px;">
                                {audit.auditor_explanation}
                            </div>
                        </div>
                        """,
                        unsafe_allow_html=True,
                    )

            if "Tabbed" in view_mode:
                # Tabbed Dossier View: Each claim gets a distinct full-width tab
                tab_titles = []
                for idx, audit in enumerate(rec.audit_records, 1):
                    d_name = "Source"
                    if audit.cited_url and audit.cited_url.startswith("http"):
                        d_name = urllib.parse.urlparse(audit.cited_url).netloc.replace("www.", "").split(".")[0].capitalize()
                    icon = "✅" if audit.verdict == "SUPPORTED" else "❌" if audit.verdict == "CONTRADICTED" else "⚠️"
                    tab_titles.append(f"{icon} Panel {idx} [{audit.claim_id}: {d_name}]")

                evidence_tabs = st.tabs(tab_titles)
                for idx, (tab, audit) in enumerate(zip(evidence_tabs, rec.audit_records), 1):
                    with tab:
                        _render_single_evidence_panel(audit, idx)
            else:
                # Expanded Matrix View: All panels stacked with 2-column sub-panels
                for idx, audit in enumerate(rec.audit_records, 1):
                    _render_single_evidence_panel(audit, idx)
                    st.markdown("<div style='height: 12px;'></div>", unsafe_allow_html=True)

        # Unverified Information Gaps Banner
        if rec.unverified_information_gaps:
            with st.expander("⚠️ Declared Information Gaps (Explicitly Refused / Unverified)", expanded=True):
                for gap in rec.unverified_information_gaps:
                    st.markdown(f"• **Unverified:** {gap}")


# -----------------------------------------------------------------------------
# TAB 2: ADVERSARIAL AUDIT & CLAIM INSPECTOR
# -----------------------------------------------------------------------------
with tab_audit:
    st.markdown("### 🛡️ Independent Auditor Verification Matrix")
    st.caption("The Auditor independently re-fetches cited URLs and verifies each claim without trusting Analyst quotes.")

    rec = st.session_state.get("latest_record")
    if not rec:
        st.info("Execute a research question in the Studio to inspect claim-level audit records.")
    else:
        # Verdict Summary Badges
        c_sup, c_con, c_uns, c_unv, c_noc = st.columns(5)
        c_sup.metric("SUPPORTED", rec.number_supported)
        c_con.metric("CONTRADICTED", rec.number_contradicted)
        c_uns.metric("UNSUPPORTED", rec.number_unsupported)
        c_unv.metric("UNVERIFIABLE", rec.number_unverifiable)
        c_noc.metric("NO CITATION", rec.number_without_citation)

        st.markdown("#### Claim-by-Claim Evidence Inspector")

        # Interactive filter
        verdict_filter = st.selectbox(
            "Filter by verdict:",
            ["ALL", "SUPPORTED", "CONTRADICTED", "UNSUPPORTED", "UNVERIFIABLE", "NO_CITATION"],
        )

        filtered_records = rec.audit_records if verdict_filter == "ALL" else [r for r in rec.audit_records if r.verdict == verdict_filter]

        if not filtered_records:
            st.info("No audit records matching the selected filter.")
        else:
            for audit in filtered_records:
                v = audit.verdict
                badge_style = {
                    "SUPPORTED": ("background: #065f46; color: #34d399;", "SUPPORTED"),
                    "CONTRADICTED": ("background: #7f1d1d; color: #f87171;", "CONTRADICTED"),
                    "UNSUPPORTED": ("background: #78350f; color: #fbbf24;", "UNSUPPORTED"),
                    "UNVERIFIABLE": ("background: #1e293b; color: #cbd5e1;", "UNVERIFIABLE"),
                    "NO_CITATION": ("background: #4c1d95; color: #c084fc;", "NO CITATION"),
                }.get(v, ("background: #1e293b; color: #94a3b8;", v))

                st.markdown(
                    f"""
                    <div class="evidence-card" style="border-left: 4px solid {'#10b981' if v=='SUPPORTED' else '#ef4444' if v=='CONTRADICTED' else '#f59e0b'};">
                        <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 6px;">
                            <div>
                                <span style="padding: 2px 8px; border-radius: 6px; font-size: 0.75rem; font-weight: 700; margin-right: 8px; {badge_style[0]}">{badge_style[1]}</span>
                                <strong>Claim {audit.claim_id}:</strong> {audit.claim_text}
                            </div>
                        </div>
                        <div style="font-size: 0.88rem; color: #cbd5e1; margin-top: 6px;">
                            <b>Auditor Verdict:</b> {audit.auditor_explanation}
                        </div>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )

                with st.expander(f"Inspect Evidence Comparison: {audit.claim_id}", expanded=False):
                    col_left, col_right = st.columns(2)
                    with col_left:
                        st.markdown("**Analyst Reported Evidence:**")
                        st.info(audit.analyst_evidence or "No quote extracted")
                        if audit.cited_url:
                            st.caption(f"Cited Source: [{audit.cited_url}]({audit.cited_url})")
                    with col_right:
                        st.markdown("**Auditor Independently Fetched Text:**")
                        st.success(audit.source_snippet_extracted or "Independent verification text snippet")
                        st.caption(f"Source HTTP Status: `{audit.auditor_source_status}`")


# -----------------------------------------------------------------------------
# TAB 3: KNOWLEDGE GRAPH & SQLITE MEMORY
# -----------------------------------------------------------------------------
with tab_memory:
    st.markdown("### 🧠 SQLite Relational Memory & FTS5 BM25 Engine")
    st.caption(f"Local zero-cost database persisted at `{settings.db_path.name}`. No cloud database or API key required.")

    mem_store = EntityMemoryStore()
    all_ents = mem_store.get_all_entities()

    col_m1, col_m2 = st.columns([1, 1])

    with col_m1:
        st.markdown("#### 🏢 Discovered Entities")
        if not all_ents:
            st.info("No entities discovered yet. Run a question to populate memory.")
        else:
            ent_data = [{"Name": e.name, "Category": e.category, "Entity ID": e.entity_id} for e in all_ents]
            st.dataframe(pd.DataFrame(ent_data), use_container_width=True, height=260)

    with col_m2:
        st.markdown("#### 🔍 Live FTS5 BM25 Search Playground")
        st.caption("Test full-text search directly over the SQLite knowledge base:")
        search_kw = st.text_input("Search knowledge base:", placeholder="e.g. dark stores, funding, Mumbai")
        if search_kw.strip():
            bm25_matches = mem_store.search_knowledge_bm25(search_kw.strip(), limit=5)
            if bm25_matches:
                for match in bm25_matches:
                    st.markdown(
                        f"""
                        <div class="glass-card" style="padding: 10px; margin-bottom: 6px;">
                            <strong>{match.get('title', 'Fact')}</strong> (Score: {match.get('rank', 0.0):.2f})<br/>
                            <small>{match.get('content', '')}</small>
                        </div>
                        """,
                        unsafe_allow_html=True,
                    )
            else:
                st.caption("No BM25 matches found in knowledge base.")

    st.markdown("---")
    st.markdown("#### 📝 Entity Facts Explorer")
    if all_ents:
        selected_ent_name = st.selectbox("Select entity to inspect facts:", options=[e.name for e in all_ents])
        if selected_ent_name:
            selected_ent = next((e for e in all_ents if e.name == selected_ent_name), None)
            if selected_ent:
                facts = mem_store.get_facts_for_entity(selected_ent.entity_id)
                if facts:
                    fact_data = [
                        {
                            "Attribute": f.attribute,
                            "Value": f.value,
                            "Source URL": f.source_url or "Context",
                            "Date": str(f.fact_date or "N/A"),
                        }
                        for f in facts
                    ]
                    st.dataframe(pd.DataFrame(fact_data), use_container_width=True)
                else:
                    st.info(f"No specific facts recorded for {selected_ent_name}.")


# -----------------------------------------------------------------------------
# TAB 4: TELEMETRY & PHASE LATENCIES
# -----------------------------------------------------------------------------
with tab_telemetry:
    st.markdown("### 📊 Engineering Telemetry & 120-Second Ceiling Monitor")

    rec = st.session_state.get("latest_record")
    if not rec:
        st.info("Execute a research run to view live phase breakdown and network telemetry.")
    else:
        t1, t2, t3, t4 = st.columns(4)
        t1.metric("Total Execution", f"{rec.execution_time_seconds:.2f}s", "Ceiling: 120s")
        t2.metric("Prompt / Completion Tokens", f"{rec.prompt_tokens} / {rec.completion_tokens}")
        t3.metric("Total Tokens", f"{rec.total_tokens:,}")
        t4.metric("Cost (USD / INR)", f"${rec.cost_usd:.5f}", f"₹{rec.cost_inr:.3f}")

        st.markdown("#### ⏱️ Phase-by-Phase Latency Breakdown")
        latency_data = {
            "Phase": [
                "Planning",
                "Web Search",
                "Parallel Fetch",
                "Analyst Synthesis",
                "Auditor Verification",
                "Correction Cycle",
            ],
            "Seconds": [
                rec.planning_time_seconds,
                rec.search_time_seconds,
                rec.fetch_time_seconds,
                rec.analyst_synthesis_time_seconds,
                rec.auditor_time_seconds,
                rec.correction_time_seconds,
            ],
        }
        df_latency = pd.DataFrame(latency_data)
        st.bar_chart(df_latency.set_index("Phase"), color="#38bdf8")

        st.markdown("#### 🌐 Network Traffic & Candidate Failure Matrix")
        col_net1, col_net2, col_net3, col_net4 = st.columns(4)
        col_net1.metric("URLs Searched", rec.number_of_urls_searched)
        col_net2.metric("URLs Fetched", rec.number_of_urls_fetched)
        col_net3.metric("Usable Sources", rec.number_of_usable_sources)
        col_net4.metric("Failures / Retries", f"{rec.failures_count} / {rec.total_retries_performed}")

        with st.expander("Inspect Raw JSON Execution Telemetry", expanded=False):
            st.json(rec.model_dump())


# -----------------------------------------------------------------------------
# TAB 5: 8-QUESTION BENCHMARKS
# -----------------------------------------------------------------------------
with tab_benchmarks:
    st.markdown("### 🧪 Thuli Studios Problem 3: 8-Question Benchmark Suite")
    st.caption("Standardized evaluation suite testing baseline discovery, entity memory transfer, and adversarial trap handling.")

    for item in EVAL_QUESTIONS:
        qid = item["id"]
        q_text = item["question"]
        q_cat = item["category"]
        q_notes = item["notes"]

        with st.container():
            st.markdown(
                f"""
                <div class="glass-card" style="margin-bottom: 10px; padding: 12px 16px;">
                    <div style="display: flex; justify-content: space-between; align-items: center;">
                        <div>
                            <span class="badge-pill" style="background: rgba(56, 189, 248, 0.2); color: #38bdf8; font-weight:700; padding:3px 8px; border-radius:6px;">{qid}</span>
                            <span class="badge-pill" style="background: rgba(148, 163, 184, 0.2); color: #cbd5e1; font-weight:600; padding:3px 8px; border-radius:6px;">{q_cat}</span>
                            <strong>{q_text}</strong>
                        </div>
                    </div>
                    <div style="font-size: 0.8rem; color: #94a3b8; margin-top: 4px;">
                        <i>Notes: {q_notes}</i>
                    </div>
                </div>
                """,
                unsafe_allow_html=True,
            )
            if st.button(f"Load & Run {qid} in Studio", key=f"btn_bench_{qid}"):
                st.session_state.active_query = q_text
                st.success(f"Loaded {qid} into Research Studio! Switch to Tab 1 to execute.")
