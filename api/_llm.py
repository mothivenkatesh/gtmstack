"""
GTMforce — one chat completion, provider-agnostic.

Both content engines (_teardown, _personas) want the same thing: send a system
+ user prompt, get text back, and fall back to a heuristic when no model is
configured. This module owns the provider switch so neither engine repeats it.

Provider is chosen by env, most specific first:
  1. GTMFORCE_LLM_BASE_URL  -> any OpenAI-compatible endpoint (RunPod Serverless
     vLLM, OpenRouter, DeepSeek, a local server). One POST to
     {base}/chat/completions, bearer = GTMFORCE_LLM_KEY. The bring-your-own-model
     path. Uses requests (already a dep), so no openai SDK needed.
  2. ANTHROPIC_API_KEY      -> Anthropic Messages API (the original path).
  3. neither                -> raise NoModel; the caller runs its heuristic.

GTMFORCE_MODEL names the model for whichever provider wins. GTMFORCE_MAX_TOKENS
optionally raises the ceiling (reasoning models need room for their <think>
block before the JSON). Shared by app.py (Flask) and the Vercel handlers.
"""
from __future__ import annotations

import os


class NoModel(Exception):
    """No live provider configured; the caller should use its heuristic."""


def configured():
    """True when some live model is reachable (either provider)."""
    return bool(os.getenv("GTMFORCE_LLM_BASE_URL") or os.getenv("ANTHROPIC_API_KEY"))


def _provider():
    if os.getenv("GTMFORCE_LLM_BASE_URL"):
        return "openai"
    if os.getenv("ANTHROPIC_API_KEY"):
        return "anthropic"
    return None


def _model(prov):
    m = os.getenv("GTMFORCE_MODEL")
    if m:
        return m
    return "deepseek-ai/DeepSeek-R1-Distill-Qwen-14B" if prov == "openai" else "claude-haiku-4-5"


def _strip_think(text):
    """Reasoning models (DeepSeek-R1, QwQ) prepend a <think>...</think> block.
    Drop everything up to the last </think> so the JSON the caller extracts is
    not polluted by braces or brackets inside the reasoning."""
    if text and "</think>" in text:
        return text.rsplit("</think>", 1)[-1]
    return text or ""


def chat(system, user, max_tokens=900):
    """One completion. Returns the model's text with any reasoning block
    stripped. Raises NoModel when nothing is configured; lets provider and
    network errors propagate so the caller can fall back to its heuristic."""
    prov = _provider()
    if prov is None:
        raise NoModel()
    model = _model(prov)
    # Reasoning models spend tokens thinking before they answer, so give the
    # OpenAI-compatible path more headroom or the JSON gets truncated.
    mt = int(os.getenv("GTMFORCE_MAX_TOKENS") or
             (max(max_tokens, 3000) if prov == "openai" else max_tokens))

    if prov == "openai":
        import requests
        base = os.environ["GTMFORCE_LLM_BASE_URL"].rstrip("/")
        key = os.getenv("GTMFORCE_LLM_KEY") or os.getenv("OPENAI_API_KEY") or "x"
        r = requests.post(
            f"{base}/chat/completions",
            headers={"Authorization": f"Bearer {key}"},
            json={"model": model, "max_tokens": mt, "temperature": 0.6,
                  "messages": [{"role": "system", "content": system},
                               {"role": "user", "content": user}]},
            timeout=float(os.getenv("GTMFORCE_LLM_TIMEOUT", "120")),
        )
        r.raise_for_status()
        return _strip_think(r.json()["choices"][0]["message"]["content"])

    from anthropic import Anthropic
    msg = Anthropic().messages.create(
        model=model, max_tokens=mt, system=system,
        messages=[{"role": "user", "content": user}],
    )
    return _strip_think("".join(b.text for b in msg.content
                                if getattr(b, "type", "") == "text"))
