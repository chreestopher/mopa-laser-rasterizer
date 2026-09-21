"""Render trusted, repository-owned Markdown as documentation guide blocks.

This deliberately supports only the small Markdown subset used by the manual
Krasnow guide.  It is not intended for user-provided content.
"""

from html import escape
from pathlib import Path
import re


_ORDERED_ITEM = re.compile(r"^\s*\d+\.\s+(.*)$")
_UNORDERED_ITEM = re.compile(r"^\s*[-*]\s+(.*)$")


def _list_item(line):
    ordered = re.match(r"^(\s*)\d+\.\s+(.*)$", line)
    if ordered:
        return len(ordered.group(1)), "ol", ordered.group(2)
    unordered = re.match(r"^(\s*)[-*]\s+(.*)$", line)
    if unordered:
        return len(unordered.group(1)), "ul", unordered.group(2)
    return None


def _render_list(lines, index, indent=None, list_tag=None):
    first = _list_item(lines[index])
    if first is None:
        return "", index
    indent = first[0] if indent is None else indent
    list_tag = first[1] if list_tag is None else list_tag
    items = []

    while index < len(lines):
        current = _list_item(lines[index])
        if current is None or current[0] < indent:
            break
        if current[0] > indent:
            nested, index = _render_list(lines, index, current[0], current[1])
            if items:
                items[-1] += nested
            continue
        if current[1] != list_tag:
            break

        item = f"<li>{_inline(current[2].strip())}"
        index += 1
        while index < len(lines):
            following = _list_item(lines[index])
            if following is None or following[0] <= indent:
                break
            nested, index = _render_list(lines, index, following[0], following[1])
            item += nested
        items.append(item + "</li>")

    return f"<{list_tag}>{''.join(items)}</{list_tag}>", index


def _inline(text):
    code_fragments = []

    def preserve_code(match):
        code_fragments.append(f"<code>{escape(match.group(1))}</code>")
        return f"\x00CODE{len(code_fragments) - 1}\x00"

    rendered = re.sub(r"`([^`]+)`", preserve_code, text)
    rendered = escape(rendered)
    rendered = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", rendered)
    rendered = re.sub(r"\*([^*]+?)\*", r"<em>\1</em>", rendered)
    rendered = re.sub(
        r"\[([^\]]+)\]\((https?://[^)]+)\)",
        r'<a href="\2" target="_blank" rel="noopener noreferrer">\1</a>',
        rendered,
    )
    for index, fragment in enumerate(code_fragments):
        rendered = rendered.replace(f"\x00CODE{index}\x00", fragment)
    return rendered


def _is_table_separator(line):
    cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
    return bool(cells) and all(re.fullmatch(r":?-{3,}:?", cell) for cell in cells)


def _render_blocks(lines):
    blocks = []
    index = 0
    while index < len(lines):
        line = lines[index]
        if not line.strip():
            index += 1
            continue

        if line.startswith("### "):
            blocks.append(f"<h3>{_inline(line[4:].strip())}</h3>")
            index += 1
            continue

        if line.startswith("```"):
            language = line[3:].strip()
            code = []
            index += 1
            while index < len(lines) and not lines[index].startswith("```"):
                code.append(lines[index])
                index += 1
            index += 1
            language_class = f' class="language-{escape(language)}"' if language else ""
            blocks.append(f"<pre><code{language_class}>{escape(chr(10).join(code))}</code></pre>")
            continue

        if (
            line.lstrip().startswith("|")
            and index + 1 < len(lines)
            and _is_table_separator(lines[index + 1])
        ):
            headers = [cell.strip() for cell in line.strip().strip("|").split("|")]
            index += 2
            rows = []
            while index < len(lines) and lines[index].lstrip().startswith("|"):
                rows.append([cell.strip() for cell in lines[index].strip().strip("|").split("|")])
                index += 1
            head = "".join(f"<th scope=\"col\">{_inline(cell)}</th>" for cell in headers)
            body = "".join(
                "<tr>" + "".join(f"<td>{_inline(cell)}</td>" for cell in row) + "</tr>"
                for row in rows
            )
            blocks.append(
                '<div class="docs-table-wrap"><table class="docs-markdown-table">'
                f"<thead><tr>{head}</tr></thead><tbody>{body}</tbody></table></div>"
            )
            continue

        if _list_item(line):
            rendered_list, index = _render_list(lines, index)
            blocks.append(rendered_list)
            continue

        if line.startswith(">"):
            quoted = []
            while index < len(lines) and lines[index].startswith(">"):
                quoted.append(lines[index][1:].strip())
                index += 1
            blocks.append(f"<blockquote>{_inline(' '.join(quoted))}</blockquote>")
            continue

        paragraph = [line.strip()]
        index += 1
        while index < len(lines):
            candidate = lines[index]
            if not candidate.strip():
                break
            if candidate.startswith(("### ", "```", ">")):
                break
            if _ORDERED_ITEM.match(candidate) or _UNORDERED_ITEM.match(candidate):
                break
            if (
                candidate.lstrip().startswith("|")
                and index + 1 < len(lines)
                and _is_table_separator(lines[index + 1])
            ):
                break
            paragraph.append(candidate.strip())
            index += 1
        blocks.append(f"<p>{_inline(' '.join(paragraph))}</p>")

    return [{"html": block} for block in blocks]


def markdown_guide_page(source_path, *, description, outcome, related):
    """Build a DOCS catalog entry from a trusted Markdown guide."""
    source = Path(source_path).read_text(encoding="utf-8")
    lines = source.splitlines()
    if not lines or not lines[0].startswith("# "):
        raise ValueError(f"Guide must begin with an H1 heading: {source_path}")

    title = lines[0][2:].strip()
    groups = []
    heading = "Understand what you are building"
    body = []
    for line in lines[1:]:
        if line.startswith("## "):
            if body:
                groups.append((heading, _render_blocks(body)))
            heading = re.sub(r"^\d+\.\s*", "", line[3:].strip())
            body = []
        else:
            body.append(line)
    if body:
        groups.append((heading, _render_blocks(body)))

    first_paragraph = next(
        (block["html"][3:-4] for block in groups[0][1] if block["html"].startswith("<p>")),
        description,
    )
    return {
        "title": title,
        "description": description,
        "intro": re.sub(r"<[^>]+>", "", first_paragraph),
        "sections": groups,
        "related": list(related),
        "external_links": [],
        "guide": True,
        "guide_outcome": outcome,
    }
