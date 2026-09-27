"""
Core application settings and pricing configuration.
"""

import os
from pathlib import Path
from pydantic import BaseModel, Field
from dotenv import load_dotenv

# Load .env file from project root
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
load_dotenv(PROJECT_ROOT / ".env")


class ModelPricing(BaseModel):
    """Cost in USD per 1M tokens."""
    input_per_million: float
    output_per_million: float


# Pricing rates (USD per 1M tokens)
PRICING_TABLE = {
    # Gemini models (Default recommendations for low-cost, fast research)
    "gemini-flash-lite-latest": ModelPricing(input_per_million=0.075, output_per_million=0.30),
    "gemini-3.1-flash-lite": ModelPricing(input_per_million=0.075, output_per_million=0.30),
    "gemini-3.5-flash-lite": ModelPricing(input_per_million=0.075, output_per_million=0.30),
    "gemini-3.5-flash": ModelPricing(input_per_million=0.075, output_per_million=0.30),
    "gemini-3.8-flash": ModelPricing(input_per_million=0.075, output_per_million=0.30),
    "gemini-flash-latest": ModelPricing(input_per_million=0.075, output_per_million=0.30),
    "gemini-2.5-flash": ModelPricing(input_per_million=0.075, output_per_million=0.30),
    "gemini-1.5-flash": ModelPricing(input_per_million=0.075, output_per_million=0.30),
    "gemini-1.5-pro": ModelPricing(input_per_million=1.25, output_per_million=5.00),
    # OpenAI models
    "gpt-4o-mini": ModelPricing(input_per_million=0.15, output_per_million=0.60),
    "gpt-4o": ModelPricing(input_per_million=2.50, output_per_million=10.00),
    # Claude models
    "claude-3-5-sonnet-20241022": ModelPricing(input_per_million=3.00, output_per_million=15.00),
    "claude-3-5-haiku-20241022": ModelPricing(input_per_million=0.80, output_per_million=4.00),
}


class Settings(BaseModel):
    # Paths
    project_root: Path = PROJECT_ROOT
    logs_dir: Path = PROJECT_ROOT / "logs"
    runs_log_dir: Path = PROJECT_ROOT / "logs" / "runs"
    ai_sessions_log_dir: Path = PROJECT_ROOT / "logs" / "ai_sessions"
    db_path: Path = PROJECT_ROOT / "app" / "memory" / "entities.db"

    # API Keys
    gemini_api_key: str = Field(default_factory=lambda: os.getenv("GEMINI_API_KEY", ""))
    openai_api_key: str = Field(default_factory=lambda: os.getenv("OPENAI_API_KEY", ""))
    anthropic_api_key: str = Field(default_factory=lambda: os.getenv("ANTHROPIC_API_KEY", ""))
    tavily_api_key: str = Field(default_factory=lambda: os.getenv("TAVILY_API_KEY", ""))

    # Active LLM Model
    llm_model: str = Field(default_factory=lambda: os.getenv("LLM_MODEL", "gemini-flash-lite-latest"))

    # Economy & Telemetry
    usd_to_inr: float = Field(default_factory=lambda: float(os.getenv("USD_TO_INR_RATE", "87.0")))

    # Hard constraints, concurrency & adaptive fetching thresholds
    max_wall_clock_seconds: int = 120  # Hard 2-minute ceiling per question
    fetch_timeout_seconds: float = 15.0
    max_concurrent_fetches: int = 5
    max_search_results: int = 10
    max_candidate_urls: int = 10  # Initial K: candidate URLs extracted from search
    min_usable_sources: int = 3   # Minimum verified usable sources before Analyst proceeds
    min_extracted_characters: int = 180
    max_extracted_characters_per_page: int = 12000

    # Rate Limiting & Exponential Backoff Settings
    max_retries: int = 3
    retry_base_delay: float = 1.0   # seconds
    retry_max_delay: float = 8.0    # seconds
    retry_jitter_max: float = 0.5   # seconds
    max_per_domain_concurrency: int = 2

    def calculate_cost(self, model: str, input_tokens: int, output_tokens: int) -> tuple[float, float]:
        """Returns (cost_usd, cost_inr)"""
        pricing = PRICING_TABLE.get(model, ModelPricing(input_per_million=0.15, output_per_million=0.60))
        cost_usd = (input_tokens / 1_000_000 * pricing.input_per_million) + (
            output_tokens / 1_000_000 * pricing.output_per_million
        )
        cost_inr = cost_usd * self.usd_to_inr
        return cost_usd, cost_inr


settings = Settings()
