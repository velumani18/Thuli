"""
Unified LLM Client supporting Google Gemini, OpenAI, and Anthropic.
Automatically tracks token usage and response latency.
"""

import os
import json
import asyncio
from typing import Optional
from pydantic import BaseModel

from app.core.config import settings

try:
    from google import genai
    from google.genai import types
except ImportError:
    genai = None

try:
    import openai
except ImportError:
    openai = None


class LLMResponse(BaseModel):
    content: str
    model: str
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    cost_usd: float = 0.0
    cost_inr: float = 0.0


class LLMClient:
    def __init__(self, model_name: Optional[str] = None):
        self.model_name = model_name or settings.llm_model

    async def generate(self, prompt: str, system_instruction: Optional[str] = None, json_mode: bool = False) -> LLMResponse:
        """Asynchronously dispatches LLM request and returns token usage."""
        loop = asyncio.get_event_loop()

        # 1. Google Gemini via google-genai SDK
        if "gemini" in self.model_name.lower():
            api_key = settings.gemini_api_key or os.getenv("GEMINI_API_KEY")
            if not api_key:
                raise ValueError("GEMINI_API_KEY is not set in environment or .env file.")

            candidate_models = [self.model_name]
            for fallback in ["gemini-flash-lite-latest", "gemini-3.1-flash-lite", "gemini-3.5-flash-lite", "gemini-flash-latest"]:
                if fallback not in candidate_models:
                    candidate_models.append(fallback)

            def _sync_gemini():
                import time
                import random
                client = genai.Client(api_key=api_key)
                config_args = {}
                if system_instruction:
                    config_args["system_instruction"] = system_instruction
                if json_mode:
                    config_args["response_mime_type"] = "application/json"

                config = types.GenerateContentConfig(**config_args) if config_args else None
                
                last_err = None
                for current_model in candidate_models:
                    for attempt in range(3):
                        try:
                            response = client.models.generate_content(
                                model=current_model,
                                contents=prompt,
                                config=config,
                            )
                            usage = getattr(response, "usage_metadata", None)
                            p_tokens = getattr(usage, "prompt_token_count", 0) or len(prompt) // 4
                            c_tokens = getattr(usage, "candidates_token_count", 0) or len(response.text or "") // 4
                            return response.text or "", p_tokens, c_tokens, current_model
                        except Exception as e:
                            last_err = e
                            err_str = str(e).lower()
                            # If 404 not found or 429 quota exhausted, switch immediately to next candidate model
                            if (
                                "404" in err_str
                                or "not found" in err_str
                                or "no longer available" in err_str
                                or "quota exceeded" in err_str
                                or "resource_exhausted" in err_str
                            ):
                                break
                            # Temporary 503 or transient network failure: brief backoff and retry
                            delay = min(2.0, (0.5 * (2 ** attempt)) + random.uniform(0.1, 0.3))
                            time.sleep(delay)
                raise last_err or RuntimeError("All candidate Gemini models failed.")

            text, p_tokens, c_tokens, used_model = await loop.run_in_executor(None, _sync_gemini)
            t_tokens = p_tokens + c_tokens
            cost_usd, cost_inr = settings.calculate_cost(used_model, p_tokens, c_tokens)
            return LLMResponse(
                content=text,
                model=used_model,
                prompt_tokens=p_tokens,
                completion_tokens=c_tokens,
                total_tokens=t_tokens,
                cost_usd=cost_usd,
                cost_inr=cost_inr,
            )

        # 2. OpenAI / Compatible API
        else:
            api_key = settings.openai_api_key or os.getenv("OPENAI_API_KEY")
            if not api_key:
                raise ValueError("OPENAI_API_KEY is not set.")

            def _sync_openai():
                client = openai.OpenAI(api_key=api_key)
                messages = []
                if system_instruction:
                    messages.append({"role": "system", "content": system_instruction})
                messages.append({"role": "user", "content": prompt})

                resp = client.chat.completions.create(
                    model=self.model_name,
                    messages=messages,
                    response_format={"type": "json_object"} if json_mode else None,
                )
                text = resp.choices[0].message.content or ""
                p_tokens = resp.usage.prompt_tokens if resp.usage else len(prompt) // 4
                c_tokens = resp.usage.completion_tokens if resp.usage else len(text) // 4
                return text, p_tokens, c_tokens

            text, p_tokens, c_tokens = await loop.run_in_executor(None, _sync_openai)
            t_tokens = p_tokens + c_tokens
            cost_usd, cost_inr = settings.calculate_cost(self.model_name, p_tokens, c_tokens)
            return LLMResponse(
                content=text,
                model=self.model_name,
                prompt_tokens=p_tokens,
                completion_tokens=c_tokens,
                total_tokens=t_tokens,
                cost_usd=cost_usd,
                cost_inr=cost_inr,
            )
