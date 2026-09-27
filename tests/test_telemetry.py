"""
Unit tests for Telemetry, cost calculation, and run serialization.
"""

from pathlib import Path
from app.core.config import settings
from app.core.telemetry import RunLogRecord, ClaimAuditRecord, ToolInvocationLog


def test_cost_calculation():
    # Model: gemini-2.5-flash -> input 0.075/M, output 0.30/M, USD_TO_INR = 87.0
    cost_usd, cost_inr = settings.calculate_cost("gemini-2.5-flash", 1_000_000, 1_000_000)
    assert round(cost_usd, 4) == 0.3750
    assert round(cost_inr, 2) == round(0.3750 * 87.0, 2)


def test_run_log_serialization(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(settings, "runs_log_dir", tmp_path)

    record = RunLogRecord(
        question="Which quick-commerce companies raised funding?",
        category="quick_commerce",
        model_name="gemini-2.5-flash",
        prompt_tokens=1500,
        completion_tokens=400,
        total_tokens=1900,
        cost_usd=0.0002,
        cost_inr=0.0174,
    )
    record.audit_records.append(
        ClaimAuditRecord(
            claim_id="claim_1",
            claim_text="Zepto raised $665M in June 2024",
            cited_url="https://example.com/zepto-round",
            verdict="SUPPORTED",
            auditor_explanation="Source confirms the round size and date.",
        )
    )

    saved_file = record.save_to_disk()
    assert Path(saved_file).exists()
    assert "Zepto raised $665M" in Path(saved_file).read_text(encoding="utf-8")
