# ABOUTME: Single-call semantic extraction — turns extracted PDF text into a MagazineDoc via LLM.
# ABOUTME: Uses the openai SDK (LM Studio and OpenAI both implement the same API) + SQLite cache.

from collections.abc import Callable
from typing import Any

from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn, TimeElapsedColumn

from bookery.convert.cache import LLMCache, make_key
from bookery.convert.errors import LLMBadResponse
from bookery.convert.types import MagazineDoc, RawDoc
from bookery.core.config import SemanticConfig

SYSTEM_PROMPT = """You extract the substantive articles from a PDF magazine or book.
The input text was machine-extracted and may contain interleaved columns, page
numbers, running headers, and advertisements.

Your job:
1. Identify the publication title and issue (if applicable).
2. Extract each coherent article/chapter. Skip advertisements, house ads,
   subscription pitches, cover-art descriptions, and incidental marginalia.
3. For each article/chapter: title, section (if present), byline (if present),
   dek/subhead (if present), and complete body text with paragraphs in correct
   reading order. Reassemble prose from interleaved columns. Use the source
   wording verbatim — do not summarize or paraphrase.
4. Return JSON matching the schema.
"""


ClientFactory = Callable[[SemanticConfig], Any]


def _default_client_factory(cfg: SemanticConfig) -> Any:
    # Lazy import so tests that mock this factory don't pay the openai import cost.
    from openai import OpenAI

    return OpenAI(base_url=cfg.base_url, api_key=cfg.resolve_api_key() or "placeholder")


def _serialize_raw(raw: RawDoc) -> str:
    """Serialize RawDoc into a single text blob with page markers for the LLM."""
    chunks: list[str] = []
    for page in raw.pages:
        chunks.append(f"--- PAGE {page.number} ---")
        for block in page.blocks:
            text = block.text.strip()
            if text:
                chunks.append(text)
    if raw.outline:
        chunks.append("--- OUTLINE ---")
        for entry in raw.outline:
            indent = "  " * max(0, entry.level - 1)
            chunks.append(f"{indent}{entry.title} (p.{entry.page})")
    return "\n".join(chunks)


def _call_llm(client: Any, cfg: SemanticConfig, text_blob: str) -> MagazineDoc:
    response = client.beta.chat.completions.parse(
        model=cfg.model,
        response_format=MagazineDoc,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": text_blob},
        ],
    )
    message = response.choices[0].message
    parsed = getattr(message, "parsed", None)
    if isinstance(parsed, MagazineDoc):
        return parsed
    content = message.content or ""
    if not content.strip():
        raise LLMBadResponse("empty response from model")
    try:
        return MagazineDoc.model_validate_json(content)
    except Exception as exc:
        raise LLMBadResponse(f"could not parse MagazineDoc: {exc}") from exc


def extract_semantic(
    raw: RawDoc,
    cfg: SemanticConfig,
    cache: LLMCache,
    *,
    client_factory: ClientFactory | None = None,
    console: Console | None = None,
) -> MagazineDoc:
    """Run one LLM call over the full extracted text; return a validated MagazineDoc."""
    text_blob = _serialize_raw(raw)
    key = make_key(cfg.prompt_version, cfg.model, text_blob)

    cached = cache.get(key)
    if cached is not None:
        try:
            return MagazineDoc.model_validate_json(cached)
        except Exception:
            pass  # corrupt entry — refetch

    factory = client_factory or _default_client_factory
    client = factory(cfg)

    columns = (
        SpinnerColumn(),
        TextColumn("[bold]{task.description}"),
        TimeElapsedColumn(),
    )
    progress = Progress(*columns, console=console, transient=True, disable=console is None)

    last_err: Exception | None = None
    with progress:
        progress.add_task("Classifying document…", total=None)
        for _ in range(max(1, cfg.llm_max_retries)):
            try:
                doc = _call_llm(client, cfg, text_blob)
            except LLMBadResponse as exc:
                last_err = exc
                continue
            except Exception as exc:
                last_err = exc
                continue
            if not doc.articles:
                last_err = LLMBadResponse("model returned zero articles")
                continue
            cache.put(key, doc.model_dump_json())
            return doc

    if isinstance(last_err, LLMBadResponse):
        raise last_err
    detail = str(last_err) if last_err else "unknown error"
    raise LLMBadResponse(f"LLM call failed after retries: {detail}")
