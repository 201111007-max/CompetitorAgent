"""HTML extraction, Markdown-to-HTML conversion, and text utilities.

Extracted from dota2_fastmcp.py (lines 192-448). All pure functions with
no external dependencies beyond stdlib (except ``requests`` lazily imported
inside ``fetch_fulltext``).
"""

import html
import logging
import re
from html.parser import HTMLParser
from typing import List, Optional, Tuple

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Timeout constant used by fetch_fulltext
# ---------------------------------------------------------------------------
TIMEOUT: int = 30


# ---------------------------------------------------------------------------
# 1. truncate_text
# ---------------------------------------------------------------------------

def truncate_text(text: str, max_len: int = 160) -> str:
    """Truncate *text* to at most *max_len* characters, appending '…' if cut."""
    if not text:
        return ""
    if len(text) <= max_len:
        return text
    return text[: max_len - 3] + "..."


# ---------------------------------------------------------------------------
# 2. HTMLTextExtractor
# ---------------------------------------------------------------------------

class HTMLTextExtractor(HTMLParser):
    """Extract visible text from HTML, skipping ``<script>`` / ``<style>`` blocks."""

    def __init__(self) -> None:
        super().__init__()
        self._chunks: List[str] = []
        self._skip_depth: int = 0
        self._block_tags = {
            "p", "br", "div", "li", "tr", "section", "article",
            "header", "footer", "h1", "h2", "h3", "h4", "h5", "h6", "pre",
        }
        self._skip_tags = {"script", "style", "noscript"}

    def handle_starttag(self, tag: str, attrs: List[Tuple[str, Optional[str]]]) -> None:
        if tag in self._skip_tags:
            self._skip_depth += 1
            return
        if tag in self._block_tags:
            self._chunks.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in self._skip_tags:
            if self._skip_depth > 0:
                self._skip_depth -= 1
            return
        if tag in self._block_tags:
            self._chunks.append("\n")

    def handle_data(self, data: str) -> None:
        if self._skip_depth == 0 and data:
            self._chunks.append(data)

    def get_text(self) -> str:
        """Return the accumulated visible text."""
        return "".join(self._chunks)


# ---------------------------------------------------------------------------
# 3. extract_text_from_html
# ---------------------------------------------------------------------------

def extract_text_from_html(html_text: str) -> str:
    """Strip HTML tags and return clean plain text."""
    if not html_text:
        return ""
    parser = HTMLTextExtractor()
    try:
        parser.feed(html_text)
        parser.close()
    except Exception:
        return ""
    text = html.unescape(parser.get_text() or "")
    text = text.replace("\r", "")
    text = re.sub(r"[ \t]+", " ", text)
    lines = [line.strip() for line in text.split("\n")]
    lines = [line for line in lines if line]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# 4. render_inline_markdown
# ---------------------------------------------------------------------------

def render_inline_markdown(text: str) -> str:
    """Render inline Markdown (strong / emphasis / inline code), escaping the rest."""
    escaped = html.escape(text or "")
    escaped = re.sub(r"`([^`]+)`", r"<code>\1</code>", escaped)
    escaped = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", escaped)
    escaped = re.sub(r"__([^_]+)__", r"<strong>\1</strong>", escaped)
    escaped = re.sub(r"(?<!\*)\*([^*\n]+)\*(?!\*)", r"<em>\1</em>", escaped)
    escaped = re.sub(r"(?<!_)_([^_\n]+)_(?!_)", r"<em>\1</em>", escaped)
    return escaped


# ---------------------------------------------------------------------------
# 5. is_hr_line
# ---------------------------------------------------------------------------

def is_hr_line(line: str) -> bool:
    """Return True if *line* looks like a Markdown horizontal rule (---)."""
    s = (line or "").strip()
    return bool(s and re.fullmatch(r"(?:-{3,}|(?:-\s*){3,})", s))


# ---------------------------------------------------------------------------
# 6. split_md_table_row
# ---------------------------------------------------------------------------

def split_md_table_row(line: str) -> List[str]:
    """Split a pipe-delimited Markdown table row into stripped cell strings."""
    trimmed = (line or "").strip()
    if trimmed.startswith("|"):
        trimmed = trimmed[1:]
    if trimmed.endswith("|"):
        trimmed = trimmed[:-1]
    return [cell.strip() for cell in trimmed.split("|")]


# ---------------------------------------------------------------------------
# 7. is_md_table_separator
# ---------------------------------------------------------------------------

def is_md_table_separator(line: str) -> bool:
    """Return True if *line* is a Markdown table separator (``|---|---|``)."""
    return bool(re.fullmatch(r"\s*\|?\s*:?-+:?\s*(\|\s*:?-+:?\s*)+\|?\s*", line or ""))


# ---------------------------------------------------------------------------
# 8. markdown_to_html_fragment
# ---------------------------------------------------------------------------

def markdown_to_html_fragment(markdown_text: str) -> str:
    """Convert common Markdown report markup into an HTML fragment.

    Handles headings, bullet / ordered lists, pipe tables, horizontal rules,
    and inline formatting.  Unrecognised lines are collected into ``<p>``
    paragraphs.
    """
    normalized = (markdown_text or "").replace("\r\n", "\n").replace("\r", "\n")
    lines = normalized.split("\n")
    blocks: List[str] = []
    para_lines: List[str] = []
    list_tag: Optional[str] = None
    list_items: List[str] = []
    ordered_start: Optional[int] = None
    idx = 0

    def flush_paragraph() -> None:
        nonlocal para_lines
        if para_lines:
            blocks.append(f"<p>{'<br>'.join(para_lines)}</p>")
            para_lines = []

    def flush_list() -> None:
        nonlocal list_tag, list_items, ordered_start
        if list_tag and list_items:
            start_attr = ""
            if list_tag == "ol" and ordered_start and ordered_start > 1:
                start_attr = f" start=\"{ordered_start}\""
            blocks.append(f"<{list_tag}{start_attr}>" + "".join(list_items) + f"</{list_tag}>")
        list_tag = None
        list_items = []
        ordered_start = None

    while idx < len(lines):
        line = lines[idx]
        stripped = line.strip()

        if not stripped:
            flush_paragraph()
            flush_list()
            idx += 1
            continue

        if stripped in {"*", "-", "+", "•"}:
            idx += 1
            continue

        if is_hr_line(stripped):
            flush_paragraph()
            flush_list()
            blocks.append("<hr>")
            idx += 1
            continue

        # Pipe table: header + separator + body
        if "|" in stripped and idx + 1 < len(lines) and is_md_table_separator(lines[idx + 1]):
            flush_paragraph()
            flush_list()
            header_cells = split_md_table_row(stripped)
            table_rows: List[List[str]] = []
            j = idx + 2
            while j < len(lines):
                row_line = lines[j]
                row_trim = row_line.strip()
                if not row_trim or "|" not in row_trim:
                    break
                table_rows.append(split_md_table_row(row_trim))
                j += 1
            width = len(header_cells)
            for row in table_rows:
                if len(row) > width:
                    width = len(row)
            if width > 0:
                header = header_cells + [""] * (width - len(header_cells))
                thead = "<tr>" + "".join(
                    f"<th>{render_inline_markdown(c)}</th>" for c in header
                ) + "</tr>"
                body_rows_html: List[str] = []
                for row in table_rows:
                    padded = row + [""] * (width - len(row))
                    body_rows_html.append(
                        "<tr>" + "".join(
                            f"<td>{render_inline_markdown(c)}</td>" for c in padded
                        ) + "</tr>"
                    )
                blocks.append(
                    "<table><thead>" + thead + "</thead><tbody>"
                    + "".join(body_rows_html) + "</tbody></table>"
                )
                idx = j
                continue

        heading_match = re.match(r"^\s*(#{1,4})\s+(.*)$", line)
        if heading_match:
            flush_paragraph()
            flush_list()
            level = len(heading_match.group(1))
            content = render_inline_markdown(heading_match.group(2).strip())
            blocks.append(f"<h{level}>{content}</h{level}>")
            idx += 1
            continue

        ordered_match = re.match(r"^\s*(\d+)\.\s+(.*)$", line)
        if ordered_match:
            flush_paragraph()
            number = int(ordered_match.group(1))
            if list_tag != "ol":
                flush_list()
                list_tag = "ol"
                ordered_start = number
            list_items.append(
                f"<li>{render_inline_markdown(ordered_match.group(2).strip())}</li>"
            )
            idx += 1
            continue

        bullet_match = re.match(r"^\s*[-*+•]\s+(.*)$", line)
        if bullet_match:
            flush_paragraph()
            if list_tag != "ul":
                flush_list()
                list_tag = "ul"
            list_items.append(
                f"<li>{render_inline_markdown(bullet_match.group(1).strip())}</li>"
            )
            idx += 1
            continue

        flush_list()
        para_lines.append(render_inline_markdown(stripped))
        idx += 1

    flush_paragraph()
    flush_list()
    return "\n".join(blocks)


# ---------------------------------------------------------------------------
# 9. normalize_report_fragment
# ---------------------------------------------------------------------------

def normalize_report_fragment(content: str) -> str:
    """Normalize a report fragment: return HTML as-is, otherwise convert Markdown to HTML."""
    text = (content or "").strip()
    if not text:
        return ""
    if re.search(r"<[a-zA-Z][^>]*>", text):
        return text
    return markdown_to_html_fragment(text)


# ---------------------------------------------------------------------------
# 10. fetch_fulltext
# ---------------------------------------------------------------------------

def fetch_fulltext(url: str, max_chars: int = 8000) -> Tuple[Optional[str], Optional[str], bool]:
    """Fetch a URL and extract its visible text.

    Returns
    -------
    text : Optional[str]
        Extracted plain text (possibly truncated), or ``None`` on failure.
    error : Optional[str]
        Error message if the fetch failed, otherwise ``None``.
    truncated : bool
        ``True`` if the extracted text exceeded *max_chars* and was cut short.
    """
    if not url or not isinstance(url, str):
        return None, "invalid url", False
    if not url.startswith("http"):
        return None, "unsupported url scheme", False

    # Lazy import so the module loads without ``requests`` installed.
    import requests  # noqa: WPS433

    try:
        response = requests.get(
            url,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/120.0.0.0 Safari/537.36"
                )
            },
            timeout=TIMEOUT,
        )
        response.raise_for_status()
    except requests.exceptions.RequestException as exc:
        return None, str(exc), False

    content_type = response.headers.get("Content-Type", "")
    if content_type and "html" not in content_type.lower():
        # Try parsing anyway, but the content may not be HTML.
        pass

    text = extract_text_from_html(response.text)
    if not text:
        return None, "no text extracted", False

    truncated = False
    if max_chars and max_chars > 0 and len(text) > max_chars:
        text = text[:max_chars].rstrip() + "\n...[truncated]"
        truncated = True

    return text, None, truncated
