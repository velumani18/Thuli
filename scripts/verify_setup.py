"""
Comprehensive Verification and Audit Script for Analyst & Auditor.
Runs all checks requested by user:
1. Project tree
2. Virtual environment check
3. Package imports
4. File inventory
5. Code inspection of core modules
6. Unit tests execution
7. AI session log integrity & readability
8. Run log destination check
9. Secrets / gitignore leak audit
"""

import sys
import os
import json
import subprocess
from pathlib import Path

# Fix Windows console UTF-8 encoding
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

PROJECT_ROOT = Path(__file__).resolve().parent.parent

print("=" * 80)
print("1. PROJECT TREE (Excluding .venv)")
print("=" * 80)

def print_clean_tree(dir_path: Path, prefix=""):
    entries = sorted(list(dir_path.iterdir()), key=lambda p: (not p.is_dir(), p.name))
    for i, entry in enumerate(entries):
        if entry.name in (".venv", "__pycache__", ".pytest_cache", ".git"):
            continue
        is_last = (i == len(entries) - 1)
        connector = "+-- " if is_last else "|-- "
        if entry.is_dir():
            print(f"{prefix}{connector}{entry.name}/")
            new_prefix = prefix + ("    " if is_last else "|   ")
            print_clean_tree(entry, new_prefix)
        else:
            size_kb = entry.stat().st_size / 1024
            print(f"{prefix}{connector}{entry.name} ({size_kb:.1f} KB)")

print_clean_tree(PROJECT_ROOT)
print()

print("=" * 80)
print("2. VIRTUAL ENVIRONMENT & PYTHON RUNTIME")
print("=" * 80)
print(f"Python Executable: {sys.executable}")
print(f"Python Version: {sys.version.split()[0]}")
is_venv = sys.prefix != sys.base_prefix
print(f"Active Virtual Environment: {'YES (.venv)' if is_venv else 'NO'}")
print()

print("=" * 80)
print("3. PACKAGE IMPORT VERIFICATION")
print("=" * 80)
packages = [
    ("pydantic", "pydantic"),
    ("httpx", "httpx"),
    ("trafilatura", "trafilatura"),
    ("beautifulsoup4", "bs4"),
    ("duckduckgo_search", "duckduckgo_search"),
    ("streamlit", "streamlit"),
    ("google-genai", "google.genai"),
    ("openai", "openai"),
    ("pytest", "pytest"),
    ("dotenv", "dotenv"),
]

for display_name, mod_name in packages:
    try:
        mod = __import__(mod_name)
        ver = getattr(mod, "__version__", "installed")
        print(f"  [OK] {display_name:<20} -> {ver}")
    except Exception as e:
        print(f"  [FAIL] {display_name:<20} -> {e}")
print()

print("=" * 80)
print("4. CORE MODULES INSPECTION")
print("=" * 80)
sys.path.insert(0, str(PROJECT_ROOT))
core_files = [
    "app/core/config.py",
    "app/core/llm.py",
    "app/core/telemetry.py",
    "app/tools/fetcher.py",
    "app/tools/search.py",
    "app/memory/store.py",
    "app/agents/analyst.py",
    "app/agents/auditor.py",
    "app/orchestrator.py",
    "scripts/export_ai_session.py",
    "scripts/run_eval.py",
]

for cf in core_files:
    p = PROJECT_ROOT / cf
    if p.exists():
        lines = len(p.read_text(encoding="utf-8").splitlines())
        size_kb = p.stat().st_size / 1024
        print(f"  [EXISTS] {cf:<30} ({lines} lines, {size_kb:.1f} KB)")
    else:
        print(f"  [MISSING] {cf:<30}")
print()

print("=" * 80)
print("5. PYTEST SUITE EXECUTION")
print("=" * 80)
res = subprocess.run([sys.executable, "-m", "pytest", "-v"], capture_output=True, text=True, cwd=str(PROJECT_ROOT))
print(res.stdout.strip())
print()

print("=" * 80)
print("6. AI SESSION LOGS (logs/ai_sessions) INSPECTION")
print("=" * 80)
ai_sessions_dir = PROJECT_ROOT / "logs" / "ai_sessions"
md_files = sorted(list(ai_sessions_dir.glob("*.md")))
jsonl_files = sorted(list(ai_sessions_dir.glob("*.jsonl")))

print(f"Total MD session files: {len(md_files)}")
print(f"Total JSONL session files: {len(jsonl_files)}")

if md_files:
    latest_md = md_files[-1]
    content = latest_md.read_text(encoding="utf-8")
    lines = content.splitlines()
    print(f"\nLatest Markdown Transcript: {latest_md.name} ({len(lines)} lines)")
    print("--- First 15 lines ---")
    for l in lines[:15]:
        print(l)
    print("...")
    print(f"Contains 'USER PROMPT': {'YES' if 'USER PROMPT' in content else 'NO'}")
    print(f"Contains 'AGENT RESPONSE': {'YES' if 'AGENT RESPONSE' in content else 'NO'}")
    print(f"Contains 'Analyst and Auditor': {'YES' if 'Analyst and Auditor' in content else 'NO'}")

print()

print("=" * 80)
print("7. RUN LOGS DIRECTORY (logs/runs) READINESS")
print("=" * 80)
runs_dir = PROJECT_ROOT / "logs" / "runs"
print(f"Path: {runs_dir}")
print(f"Exists: {runs_dir.exists()}")
print(f"Writable: {os.access(runs_dir, os.W_OK)}")
existing_runs = list(runs_dir.glob("*.json"))
print(f"Existing run JSON files: {len(existing_runs)}")
print()

print("=" * 80)
print("8. SECRETS & LEAKAGE AUDIT")
print("=" * 80)
gitignore_path = PROJECT_ROOT / ".gitignore"
gitignore_has_env = False
if gitignore_path.exists():
    with open(gitignore_path, "r", encoding="utf-8") as f:
        content = f.read()
        gitignore_has_env = ".env" in content

print(f".gitignore exists: {gitignore_path.exists()}")
print(f".gitignore protects .env: {'YES' if gitignore_has_env else 'NO'}")

# Check if any hardcoded API keys exist in code
suspicious_patterns = ["AIzaSy", "sk-proj-", "tvly-"]
found_leaks = []
for p in (PROJECT_ROOT / "app").rglob("*.py"):
    with open(p, "r", encoding="utf-8") as f:
        text = f.read()
        for pat in suspicious_patterns:
            if pat in text:
                found_leaks.append((p.name, pat))

if found_leaks:
    print(f"[WARNING] Potential secrets found in code: {found_leaks}")
else:
    print("[OK] No hardcoded API keys or secrets detected in codebase.")

print("=" * 80)
