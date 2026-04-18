# ABOUTME: LLM-assisted structural classification of CleanBlocks into h1/h2/h3/p/blockquote/li.
# ABOUTME: Talks to LM Studio via the OpenAI SDK, with retry-on-bad-JSON and SQLite cache.

import json
from collections.abc import Callable, Iterable, Sequence
from statistics import median
from typing import Any

from rich.console import Console
from rich.progress import (
    BarColumn,
    MofNCompleteColumn,
    Progress,
    SpinnerColumn,
    TextColumn,
    TimeRemainingColumn,
)

from bookery.convert.cache import LLMCache, make_key
from bookery.convert.errors import LLMBadResponse
from bookery.convert.types import (
    ChapterPlan,
    ChapterSpan,
    ClassifiedBlock,
    ClassifiedChapter,
    ClassifiedDoc,
    CleanBlock,
    CleanDoc,
)
from bookery.core.config import ConvertConfig

VALID_KINDS = {"h1", "h2", "h3", "p", "blockquote", "li"}
CHUNK_SIZE = 40  # block count per LLM call

SYSTEM_PROMPT = (
    "You classify paragraph blocks from a book PDF into structural tags. "
    "Respond with JSON of shape "
    '{"classifications": ["p", "h2", "li", ...]} '
    "containing one entry per input block in the same order. "
    "Allowed tags: h1, h2, h3, p, blockquote, li."
)


ClientFactory = Callable[[ConvertConfig], Any]


def _default_client_factory(cfg: ConvertConfig) -> Any:
    # Lazy import so tests that mock this factory don't pay the openai import cost.
    from openai import OpenAI

    return OpenAI(base_url=cfg.llm_base_url, api_key=cfg.llm_api_key)


def _chunks(blocks: Sequence[CleanBlock], size: int) -> Iterable[Sequence[CleanBlock]]:
    for i in range(0, len(blocks), size):
        yield blocks[i : i + size]


def _chunk_text(chunk: Sequence[CleanBlock]) -> str:
    lines = [f"{i + 1}. {b.text}" for i, b in enumerate(chunk)]
    return "\n".join(lines)


def _heuristic_kinds(chunk: Sequence[CleanBlock], is_first_chunk: bool) -> list[str]:
    if not chunk:
        return []
    baseline = median(b.font_size for b in chunk)
    kinds: list[str] = []
    for idx, block in enumerate(chunk):
        heading_leader = (
            idx == 0 and is_first_chunk and block.font_size >= baseline * 1.1
        )
        heading_inline = (
            block.font_size >= baseline * 1.3 and len(block.text) <= 120
        )
        if heading_leader or heading_inline:
            kinds.append("h2")
        else:
            kinds.append("p")
    return kinds


def _parse_response(raw: str, expected: int) -> list[str]:
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise LLMBadResponse(f"invalid JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise LLMBadResponse("top-level JSON is not an object")
    classifications = data.get("classifications")
    if not isinstance(classifications, list):
        raise LLMBadResponse("missing 'classifications' list")
    if len(classifications) != expected:
        raise LLMBadResponse(
            f"expected {expected} classifications, got {len(classifications)}"
        )
    out: list[str] = []
    for item in classifications:
        kind = str(item).lower()
        if kind not in VALID_KINDS:
            kind = "p"
        out.append(kind)
    return out


def _call_llm(client: Any, cfg: ConvertConfig, prompt_text: str) -> str:
    response = client.chat.completions.create(
        model=cfg.llm_model,
        response_format={"type": "json_object"},
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": prompt_text},
        ],
    )
    return response.choices[0].message.content or ""


def _classify_chunk(
    chunk: Sequence[CleanBlock],
    *,
    client: Any,
    cache: LLMCache,
    cfg: ConvertConfig,
    warnings: list[str],
    is_first_chunk: bool,
) -> list[str]:
    if not chunk:
        return []
    prompt_text = _chunk_text(chunk)
    key = make_key(cfg.prompt_version, cfg.llm_model, prompt_text)
    cached = cache.get(key)
    if cached is not None:
        try:
            return _parse_response(cached, expected=len(chunk))
        except LLMBadResponse:
            pass  # fall through to re-query on corrupt cache entry

    last_err: Exception | None = None
    for _ in range(max(1, cfg.llm_max_retries)):
        try:
            raw = _call_llm(client, cfg, prompt_text)
            kinds = _parse_response(raw, expected=len(chunk))
            cache.put(key, raw)
            return kinds
        except LLMBadResponse as exc:
            last_err = exc
            continue
        except Exception as exc:  # network/timeout/etc — retry, then fall back
            last_err = exc
            continue

    warnings.append(
        f"LLM classification failed after retries ({last_err}); using heuristic."
    )
    return _heuristic_kinds(chunk, is_first_chunk=is_first_chunk)


def _chapter_blocks(doc: CleanDoc, span: ChapterSpan) -> Sequence[CleanBlock]:
    return doc.blocks[span.start : span.end]


def classify(
    doc: CleanDoc,
    plan: ChapterPlan,
    cache: LLMCache,
    cfg: ConvertConfig,
    *,
    client_factory: ClientFactory | None = None,
    console: Console | None = None,
) -> ClassifiedDoc:
    """Classify each CleanBlock into h1/h2/h3/p/blockquote/li via LM Studio + cache."""
    if not plan.spans:
        return ClassifiedDoc(chapters=())

    factory = client_factory or _default_client_factory
    client = factory(cfg)
    warnings: list[str] = []
    chapters: list[ClassifiedChapter] = []

    columns = (
        SpinnerColumn(),
        TextColumn("[bold]{task.description}"),
        BarColumn(),
        MofNCompleteColumn(),
        TimeRemainingColumn(),
    )
    progress = Progress(*columns, console=console, transient=True, disable=console is None)

    with progress:
        task_id = progress.add_task("Classifying chapters", total=len(plan.spans))
        for span in plan.spans:
            blocks = _chapter_blocks(doc, span)
            chapter_classified: list[ClassifiedBlock] = []
            for chunk_idx, chunk in enumerate(_chunks(blocks, CHUNK_SIZE)):
                kinds = _classify_chunk(
                    chunk,
                    client=client,
                    cache=cache,
                    cfg=cfg,
                    warnings=warnings,
                    is_first_chunk=(chunk_idx == 0),
                )
                for block, kind in zip(chunk, kinds, strict=True):
                    chapter_classified.append(
                        ClassifiedBlock(text=block.text, kind=kind)
                    )
            chapters.append(
                ClassifiedChapter(
                    title=span.title, blocks=tuple(chapter_classified)
                )
            )
            progress.advance(task_id)

    return ClassifiedDoc(chapters=tuple(chapters), warnings=tuple(warnings))
