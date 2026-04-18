# ABOUTME: Assembles a MagazineDoc into an EPUB via ebooklib with the Kobo base stylesheet.
# ABOUTME: One chapter per Article; metadata placeholder until downstream match_one fills it in.

import html
import uuid
from importlib import resources
from pathlib import Path

from ebooklib import epub

from bookery.convert.types import Article, MagazineDoc

CSS_FILENAME = "kobo.css"
CSS_PACKAGE = "bookery.convert.assets"


def _load_css() -> str:
    return resources.files(CSS_PACKAGE).joinpath(CSS_FILENAME).read_text(encoding="utf-8")


def _render_body_paragraphs(body: str) -> str:
    parts = [p.strip() for p in body.split("\n\n") if p.strip()]
    return "\n".join(f"<p>{html.escape(p)}</p>" for p in parts)


def _chapter_content(article: Article) -> str:
    pieces: list[str] = [f"<h1>{html.escape(article.title)}</h1>"]
    if article.section:
        pieces.append(f'<p class="section">{html.escape(article.section)}</p>')
    if article.byline:
        pieces.append(f'<p class="byline">{html.escape(article.byline)}</p>')
    if article.dek:
        pieces.append(f'<p class="dek">{html.escape(article.dek)}</p>')
    pieces.append(_render_body_paragraphs(article.body))
    return "\n".join(pieces)


def _chapter_xhtml(article: Article, index: int) -> epub.EpubHtml:
    filename = f"chap_{index:03d}.xhtml"
    item = epub.EpubHtml(
        title=article.title,
        file_name=filename,
        lang="en",
    )
    body = _chapter_content(article)
    item.content = (
        "<?xml version='1.0' encoding='utf-8'?>\n"
        "<!DOCTYPE html>\n"
        '<html xmlns="http://www.w3.org/1999/xhtml">\n'
        "<head>\n"
        f"<title>{html.escape(article.title)}</title>\n"
        '<link rel="stylesheet" type="text/css" href="style/kobo.css" />\n'
        "</head>\n"
        f"<body>\n{body}\n</body>\n</html>\n"
    ).encode()
    return item


def _humanize_stem(stem: str) -> str:
    cleaned = stem.replace("_", " ").replace("-", " ")
    collapsed = " ".join(cleaned.split())
    return collapsed.strip() or stem


def _resolve_title(doc: MagazineDoc, stem: str, title_hint: str | None) -> str:
    if doc.publication and doc.issue:
        return f"{doc.publication} - {doc.issue}"
    if doc.publication:
        return doc.publication
    if doc.issue:
        return doc.issue
    if title_hint and title_hint.strip():
        return title_hint.strip()
    humanized = _humanize_stem(stem)
    return humanized or "Untitled"


def assemble(
    doc: MagazineDoc,
    out_dir: Path,
    *,
    stem: str,
    title_hint: str | None = None,
) -> Path:
    """Write an EPUB at `out_dir/{stem}.epub` and return its path."""
    out_dir.mkdir(parents=True, exist_ok=True)
    book = epub.EpubBook()
    book.set_identifier(f"bookery-convert-{uuid.uuid4()}")
    book.set_title(_resolve_title(doc, stem, title_hint))
    book.set_language("en")

    css_item = epub.EpubItem(
        uid="style_kobo",
        file_name="style/kobo.css",
        media_type="text/css",
        content=_load_css().encode("utf-8"),
    )
    book.add_item(css_item)

    chapter_items: list[epub.EpubHtml] = []
    for idx, article in enumerate(doc.articles, start=1):
        item = _chapter_xhtml(article, idx)
        item.add_item(css_item)
        book.add_item(item)
        chapter_items.append(item)

    book.toc = [
        epub.Link(item.file_name, item.title, f"chap_{i:03d}")
        for i, item in enumerate(chapter_items, start=1)
    ]
    book.add_item(epub.EpubNcx())
    book.add_item(epub.EpubNav())
    book.spine = ["nav", *chapter_items]

    out_path = out_dir / f"{stem}.epub"
    epub.write_epub(str(out_path), book)
    return out_path
