"""Muse Spark review client via Meta Model API.

Sends transcript-review prompts in one of three API styles (chat,
messages, responses) and returns the model's raw text reply. Retries
429/5xx with backoff; errors are concise, key-free SparkError messages
in the same shape as voice_transcribe. Every HTTP attempt is reported
through on_attempt for the api_calls log; this module never touches
the database itself.
"""

import json
import time

import requests

from backend.core import config
from backend.core.errors import HakiScribeError
from backend.integrations.meta.voice_transcribe import html_title, is_html_body

SPARK_TIMEOUT_SECONDS = 120
SPARK_MAX_RETRIES = 3
SPARK_RETRY_BASE_SECONDS = 1.0
SPARK_MAX_TOKENS = 2000
SPARK_TEMPERATURE = 0

SPARK_STYLES = ("chat", "messages", "responses")
STYLE_PATHS = {
    "chat": "/chat/completions",
    "messages": "/messages",
    "responses": "/responses",
}


class SparkError(HakiScribeError):
    """Raised when a Spark review request or reply fails."""

    code = "spark_failed"


def get_api_style() -> str:
    """Validated Spark API style; default chat, ValueError when invalid."""
    style = (config.META_SPARK_API_STYLE or "").strip().lower() or "chat"
    if style not in SPARK_STYLES:
        raise ValueError(
            f"invalid META_SPARK_API_STYLE: {config.META_SPARK_API_STYLE!r} "
            "(use chat, messages, or responses)"
        )
    return style


def build_request_body(
    style: str,
    model: str,
    system: str,
    user: str,
    max_tokens: int = SPARK_MAX_TOKENS,
) -> dict:
    """Build the POST body for one API style. ValueError when unknown."""
    if style == "chat":
        return {
            "model": model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": SPARK_TEMPERATURE,
            "max_tokens": max_tokens,
        }
    if style == "messages":
        return {
            "model": model,
            "system": system,
            "messages": [{"role": "user", "content": user}],
            "temperature": SPARK_TEMPERATURE,
            "max_tokens": max_tokens,
        }
    if style == "responses":
        return {
            "model": model,
            "instructions": system,
            "input": user,
            "temperature": SPARK_TEMPERATURE,
            "max_output_tokens": max_tokens,
        }
    raise ValueError(f"unknown Spark API style: {style!r}")


def _content_to_text(content: object, style: str) -> str:
    """Coerce a chat message content block to plain text."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = [
            part.get("text", "")
            for part in content
            if isinstance(part, dict) and isinstance(part.get("text"), str)
        ]
        if parts:
            return "".join(parts)
    raise SparkError(f"Spark {style} reply has no readable text content")


def extract_reply_text(style: str, payload: object) -> str:
    """Pull the model's text from a style-shaped JSON payload."""
    if not isinstance(payload, dict):
        raise SparkError("Spark reply is not a JSON object")
    if style == "chat":
        try:
            choices = payload.get("choices") or []
            content = choices[0]["message"]["content"]
        except (IndexError, KeyError, TypeError):
            raise SparkError(
                "Spark chat reply has no choices/message/content"
            ) from None
        return _content_to_text(content, style)
    if style == "messages":
        blocks = payload.get("content")
        if not isinstance(blocks, list):
            raise SparkError("Spark messages reply has no content blocks")
        texts = [
            block["text"]
            for block in blocks
            if isinstance(block, dict)
            and block.get("type") == "text"
            and isinstance(block.get("text"), str)
        ]
        if not texts:
            raise SparkError("Spark messages reply has no text blocks")
        return "".join(texts)
    if style == "responses":
        texts = []
        for item in payload.get("output") or []:
            if not isinstance(item, dict) or item.get("type") != "message":
                continue
            for part in item.get("content") or []:
                if (
                    isinstance(part, dict)
                    and part.get("type") == "output_text"
                    and isinstance(part.get("text"), str)
                ):
                    texts.append(part["text"])
        if not texts:
            raise SparkError("Spark responses reply has no output_text")
        return "".join(texts)
    raise ValueError(f"unknown Spark API style: {style!r}")


def _retry_delay_seconds(response: requests.Response, attempt: int) -> float:
    retry_after = response.headers.get("Retry-After")
    if retry_after is not None:
        try:
            return max(0.0, float(retry_after))
        except (TypeError, ValueError):
            pass
    return SPARK_RETRY_BASE_SECONDS * (2**attempt)


def _scrub_key(text: str) -> str:
    key = config.get_meta_key()
    if key:
        text = text.replace(key, "[REDACTED]")
    return text


def _format_spark_error(response: requests.Response) -> str:
    """Short key-free message; HTML bodies collapse to title + base hint."""
    status = response.status_code
    headers = getattr(response, "headers", None) or {}
    content_type = headers.get("Content-Type", "") or ""
    body = response.text or ""
    if is_html_body(body, content_type):
        title = html_title(body) or "(no title found)"
        return (
            f"spark request failed: HTTP {status}: {title} "
            "(HTML page, not an API response: check META_API_BASE)"
        )
    return f"spark request failed: HTTP {status}: {_scrub_key(body[:500])}"


def _request_id_of(response: requests.Response | None) -> str | None:
    """Read the request id from response headers when present."""
    headers = getattr(response, "headers", None) or {}
    try:
        return headers.get("x-request-id") or headers.get("request-id")
    except Exception:
        return None


def _notify_attempt(
    on_attempt,
    response: requests.Response | None,
    ok: bool,
    error_code: str | None,
    latency_ms: float,
) -> None:
    """Report one HTTP attempt; logging failures never break the review."""
    if on_attempt is None:
        return
    info = {
        "http_status": response.status_code if response is not None else None,
        "ok": ok,
        "error_code": error_code,
        "latency_ms": latency_ms,
        "audio_bytes": None,
        "audio_ms": None,
        "request_id": _request_id_of(response),
    }
    try:
        on_attempt(info)
    except Exception:
        pass


def _is_retryable(status: int) -> bool:
    return status == 429 or 500 <= status < 600


def _post_with_retry(
    url: str, headers: dict, body: dict, on_attempt=None
) -> requests.Response:
    """POST JSON with 429/5xx retries; every attempt reported via on_attempt."""
    for attempt in range(SPARK_MAX_RETRIES + 1):
        started = time.monotonic()
        try:
            response = requests.post(
                url, headers=headers, json=body, timeout=SPARK_TIMEOUT_SECONDS
            )
        except requests.Timeout as exc:
            _notify_attempt(
                on_attempt, None, False, "TIMEOUT",
                (time.monotonic() - started) * 1000,
            )
            raise SparkError(
                f"spark request timed out after {SPARK_TIMEOUT_SECONDS}s"
            ) from exc
        except requests.ConnectionError as exc:
            _notify_attempt(
                on_attempt, None, False, "CONNECTION_ERROR",
                (time.monotonic() - started) * 1000,
            )
            raise SparkError(f"spark connection failed: {exc}") from exc
        except requests.RequestException as exc:
            _notify_attempt(
                on_attempt, None, False, "REQUEST_ERROR",
                (time.monotonic() - started) * 1000,
            )
            raise SparkError(f"spark request failed: {exc}") from exc
        status = response.status_code
        latency_ms = (time.monotonic() - started) * 1000
        if _is_retryable(status) and attempt < SPARK_MAX_RETRIES:
            _notify_attempt(
                on_attempt, response, False, f"HTTP_{status}",
                latency_ms,
            )
            time.sleep(_retry_delay_seconds(response, attempt))
            continue
        _notify_attempt(
            on_attempt, response, status < 400,
            None if status < 400 else f"HTTP_{status}",
            latency_ms,
        )
        return response
    raise SparkError("spark retry loop exhausted")  # unreachable


def complete(
    system: str,
    user: str,
    *,
    model: str | None = None,
    style: str | None = None,
    max_tokens: int = SPARK_MAX_TOKENS,
    on_attempt=None,
) -> dict:
    """POST one review prompt; return model, style, url, status, text, raw."""
    resolved_style = style or get_api_style()
    if resolved_style not in SPARK_STYLES:
        raise ValueError(f"unknown Spark API style: {resolved_style!r}")
    resolved_model = model or config.META_REASONING_MODEL
    url = f"{config.get_api_base()}{STYLE_PATHS[resolved_style]}"
    headers = {
        "Authorization": f"Bearer {config.get_meta_key()}",
        "Content-Type": "application/json",
    }
    body = build_request_body(
        resolved_style, resolved_model, system, user, max_tokens
    )
    response = _post_with_retry(url, headers, body, on_attempt)
    if response.status_code >= 400:
        raise SparkError(_format_spark_error(response))
    try:
        raw = response.json()
    except ValueError as exc:
        raise SparkError("Spark response is not valid JSON") from exc
    return {
        "model": resolved_model,
        "style": resolved_style,
        "url": url,
        "http_status": response.status_code,
        "text": extract_reply_text(resolved_style, raw),
        "raw": raw,
    }
