from __future__ import annotations

from pathlib import Path
from .config import Config


class CleanupError(RuntimeError):
    pass


_PROMPT_PATH = Path(__file__).parent / "prompts" / "cleanup.txt"
_prompt_cache: str | None = None
_client = None
_client_key: str | None = None


def _load_prompt() -> str:
    global _prompt_cache
    if _prompt_cache is None:
        _prompt_cache = _PROMPT_PATH.read_text(encoding="utf-8")
    return _prompt_cache


def _get_client(api_key: str):
    global _client, _client_key
    if not api_key:
        raise CleanupError("anthropic_api_key not set in config")
    try:
        from anthropic import Anthropic
    except ImportError as e:
        raise CleanupError("anthropic package not installed") from e
    if _client is None or _client_key != api_key:
        # SDK does its own internal retry; we ask for 3 retries on transient errors.
        _client = Anthropic(api_key=api_key, max_retries=3, timeout=30.0)
        _client_key = api_key
    return _client


def clean(raw: str, cfg: Config) -> str:
    raw = (raw or "").strip()
    if not raw:
        return ""
    client = _get_client(cfg.anthropic_api_key)
    prompt = _load_prompt()
    try:
        resp = client.messages.create(
            model=cfg.cleanup_model,
            max_tokens=2048,
            system=[
                {
                    "type": "text",
                    "text": prompt,
                    "cache_control": {"type": "ephemeral"},
                }
            ],
            messages=[{"role": "user", "content": raw}],
        )
    except Exception as e:
        raise CleanupError(f"Anthropic cleanup failed: {e}") from e

    parts = []
    for block in resp.content:
        if getattr(block, "type", None) == "text":
            parts.append(block.text)
    return "".join(parts).strip()
