# ABOUTME: Assembles a ClassifiedDoc into an EPUB via ebooklib with the Kobo base stylesheet.
# ABOUTME: Metadata here is placeholder; downstream match_one fills in provider-sourced fields.

import html
import uuid
from collections.abc import Iterable
from importlib import resources
from pathlib import Path

from ebooklib import epub

from bookery.convert.types import ClassifiedBlock, ClassifiedChapter, ClassifiedDoc

CSS_FILENAME = "kobo.css"
CSS_PACKAGE = "bookery.convert.assets"


def _load_css() -> str:
    return resources.files(CSS_PACKAGE).joinpath(CSS_FILENAME).read_text(encoding="utf-8")


def _render_block(block: ClassifiedBlock) -> str:
    tag = block.kind if block.kind in {"h1", "h2", "h3", "blockquote", "li"} else "p"
    if tag == "li":
        return f"<li>{html.escape(block.text)}</li>"
    return f"<{tag}>{html.escape(block.text)}</{tag}>"


def _chapter_body(blocks: Iterable[ClassifiedBlock]) -> str:
    pieces: list[str] = []
    in_list = False
    for block in blocks:
        if block.kind == "li":
            if not in_list:
                pieces.append("<ul>")
                in_list = True
            pieces.append(_render_block(block))
        else:
            if in_list:
                pieces.append("</ul>")
                in_list = False
            pieces.append(_render_block(block))
    if in_list:
        pieces.append("</ul>")
    return "\n".join(pieces)


def _chapter_xhtml(chapter: ClassifiedChapter, index: int) -> epub.EpubHtml:
    filename = f"chap_{index:03d}.xhtml"
    item = epub.EpubHtml(
        title=chapter.title,
        file_name=filename,
        lang="en",
    )
    body = _chapter_body(chapter.blocks)
    item.content = (
        "<?xml version='1.0' encoding='utf-8'?>\n"
        "<!DOCTYPE html>\n"
        '<html xmlns="http://www.w3.org/1999/xhtml">\n'
        "<head>\n"
        f"<title>{html.escape(chapter.title)}</title>\n"
        '<link rel="stylesheet" type="text/css" href="style/kobo.css" />\n'
        "</head>\n"
        f"<body>\n<h1>{html.escape(chapter.title)}</h1>\n{body}\n</body>\n</html>\n"
    ).encode()
    return item


def _guess_title(doc: ClassifiedDoc) -> str:
    for chapter in doc.chapters:
        for block in chapter.blocks:
            if block.kind == "h1" and block.text.strip():
                return block.text.strip()
    if doc.chapters:
        return doc.chapters[0].title
    return "Untitled"


def assemble(doc: ClassifiedDoc, out_dir: Path, *, stem: str) -> Path:
    """Write an EPUB at `out_dir/{stem}.epub` and return its path."""
    out_dir.mkdir(parents=True, exist_ok=True)
    book = epub.EpubBook()
    book.set_identifier(f"bookery-convert-{uuid.uuid4()}")
    book.set_title(_guess_title(doc))
    book.set_language("en")

    css_item = epub.EpubItem(
        uid="style_kobo",
        file_name="style/kobo.css",
        media_type="text/css",
        content=_load_css().encode("utf-8"),
    )
    book.add_item(css_item)

    chapter_items: list[epub.EpubHtml] = []
    for idx, chapter in enumerate(doc.chapters, start=1):
        item = _chapter_xhtml(chapter, idx)
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
