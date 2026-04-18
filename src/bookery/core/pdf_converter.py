# ABOUTME: Orchestrates the PDF→EPUB→KEPUB pipeline end to end.
# ABOUTME: Returns a PdfConvertResult the CLI hands to core.pipeline.match_one.

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from rich.console import Console

from bookery.convert import assemble as assemble_mod
from bookery.convert import chapters as chapters_mod
from bookery.convert import clean as clean_mod
from bookery.convert import extract as extract_mod
from bookery.convert import kepub as kepub_mod
from bookery.convert import llm as llm_mod
from bookery.convert import preflight as preflight_mod
from bookery.convert.cache import LLMCache
from bookery.core.config import ConvertConfig, load_config


@dataclass(frozen=True)
class PdfConvertResult:
    source: Path
    epub_path: Path
    kepub_path: Path
    warnings: tuple[str, ...]


ClientFactory = Callable[[ConvertConfig], Any]


def convert_pdf(
    src: Path,
    out_dir: Path,
    *,
    cfg: ConvertConfig | None = None,
    data_dir: Path | None = None,
    console: Console | None = None,
    client_factory: ClientFactory | None = None,
) -> PdfConvertResult:
    """Run the full PDF→EPUB→KEPUB pipeline; raises convert.errors on failure.

    The caller owns `out_dir` (typically a tempdir) and is responsible for cleanup.
    Preflight runs first so missing dependencies fail fast before any heavy work.
    """
    resolved = load_config()
    resolved_cfg = cfg or resolved.convert
    resolved_data = data_dir or resolved.data_dir

    preflight_mod.check_kepubify()
    preflight_mod.check_llm(resolved_cfg.llm_base_url)
    preflight_mod.check_pdf(src)

    raw = extract_mod.extract(src)
    cleaned = clean_mod.clean(
        raw, header_footer_threshold=resolved_cfg.header_footer_threshold
    )
    plan = chapters_mod.plan_chapters(cleaned)

    cache = LLMCache(resolved_data / "convert_cache.db")
    classified = llm_mod.classify(
        cleaned,
        plan,
        cache,
        resolved_cfg,
        client_factory=client_factory,
        console=console,
    )

    out_dir.mkdir(parents=True, exist_ok=True)
    epub_path = assemble_mod.assemble(
        classified, out_dir, stem=src.stem, title_hint=src.stem
    )
    kepub_path = kepub_mod.run_kepubify(epub_path, out_dir=out_dir)

    return PdfConvertResult(
        source=src,
        epub_path=epub_path,
        kepub_path=kepub_path,
        warnings=classified.warnings,
    )
