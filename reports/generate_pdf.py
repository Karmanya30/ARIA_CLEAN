from __future__ import annotations

import re
import textwrap
from pathlib import Path


ROOT = Path(__file__).resolve().parent
SOURCE = ROOT / "ARIA_Project_Report.md"
TARGET = ROOT / "ARIA_Project_Report.pdf"

PAGE_WIDTH = 595
PAGE_HEIGHT = 842
LEFT = 54
RIGHT = 54
TOP = 58
BOTTOM = 54
BODY_SIZE = 10
TITLE_SIZE = 18
HEADING_SIZE = 13
LEADING = 14
FONT = "F1"
MAX_CHARS = 92


def clean_line(line: str) -> tuple[str, str]:
    raw = line.rstrip()
    if not raw:
        return "blank", ""
    if raw.startswith("# "):
        return "title", raw[2:].strip()
    if raw.startswith("## "):
        return "heading", raw[3:].strip()
    if raw.startswith("### "):
        return "subheading", raw[4:].strip()
    if raw.startswith("- "):
        return "bullet", raw[2:].strip()
    if re.match(r"^\d+\. ", raw):
        return "number", raw.strip()
    return "body", raw.strip()


def strip_markdown(text: str) -> str:
    text = text.replace("`", "")
    text = text.replace("**", "")
    text = text.replace("### ", "")
    return text


def prepare_lines(markdown: str) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    for line in markdown.splitlines():
        kind, value = clean_line(line)
        value = strip_markdown(value)
        out.append((kind, value))
    return out


def escape_pdf_text(text: str) -> str:
    replacements = {
        "\\": "\\\\",
        "(": "\\(",
        ")": "\\)",
        "\u20b9": "Rs.",
        "\u2014": "-",
        "\u2013": "-",
        "\u2018": "'",
        "\u2019": "'",
        "\u201c": '"',
        "\u201d": '"',
    }
    for old, new in replacements.items():
        text = text.replace(old, new)
    return text.encode("latin-1", "replace").decode("latin-1")


def add_wrapped(
    pages: list[list[tuple[str, int, int, str]]],
    text: str,
    y_state: list[int],
    size: int,
    style: str,
    indent: int = 0,
) -> None:
    if not pages:
        pages.append([])
    width_chars = max(30, MAX_CHARS - indent // 5)
    wrapped = textwrap.wrap(text, width=width_chars) or [""]
    for idx, part in enumerate(wrapped):
        if y_state[0] < BOTTOM:
            pages.append([])
            y_state[0] = PAGE_HEIGHT - TOP
        prefix = ""
        x = LEFT + indent
        if style == "bullet" and idx == 0:
            prefix = "- "
        pages[-1].append((x, y_state[0], size, prefix + part))
        y_state[0] -= LEADING if size <= BODY_SIZE else LEADING + 2


def layout(lines: list[tuple[str, str]]) -> list[list[tuple[str, int, int, str]]]:
    pages: list[list[tuple[str, int, int, str]]] = [[]]
    y_state = [PAGE_HEIGHT - TOP]
    for kind, value in lines:
        if kind == "blank":
            y_state[0] -= 6
            continue
        if kind == "title":
            add_wrapped(pages, value, y_state, TITLE_SIZE, "title")
            y_state[0] -= 8
        elif kind == "heading":
            y_state[0] -= 8
            add_wrapped(pages, value, y_state, HEADING_SIZE, "heading")
            y_state[0] -= 2
        elif kind == "subheading":
            y_state[0] -= 6
            add_wrapped(pages, value, y_state, 11, "subheading")
        elif kind == "bullet":
            add_wrapped(pages, value, y_state, BODY_SIZE, "bullet", indent=12)
        elif kind == "number":
            add_wrapped(pages, value, y_state, BODY_SIZE, "number")
        else:
            add_wrapped(pages, value, y_state, BODY_SIZE, "body")
    return [page for page in pages if page]


def stream_for_page(page: list[tuple[str, int, int, str]], page_num: int, total: int) -> bytes:
    commands = ["BT", f"/{FONT} {BODY_SIZE} Tf"]
    for x, y, size, text in page:
        commands.append(f"/{FONT} {size} Tf")
        commands.append(f"1 0 0 1 {x} {y} Tm")
        commands.append(f"({escape_pdf_text(text)}) Tj")
    commands.append(f"/{FONT} 8 Tf")
    commands.append(f"1 0 0 1 {PAGE_WIDTH // 2 - 20} 28 Tm")
    commands.append(f"(Page {page_num} of {total}) Tj")
    commands.append("ET")
    return ("\n".join(commands)).encode("latin-1", "replace")


def write_pdf(pages: list[list[tuple[str, int, int, str]]]) -> None:
    objects: list[bytes] = []
    catalog_id = 1
    pages_id = 2
    font_id = 3
    content_ids = []
    page_ids = []

    next_id = 4
    streams = [stream_for_page(page, i + 1, len(pages)) for i, page in enumerate(pages)]
    for _ in pages:
        content_ids.append(next_id)
        next_id += 1
        page_ids.append(next_id)
        next_id += 1

    objects.append(f"<< /Type /Catalog /Pages {pages_id} 0 R >>".encode())
    kids = " ".join(f"{pid} 0 R" for pid in page_ids)
    objects.append(f"<< /Type /Pages /Kids [{kids}] /Count {len(page_ids)} >>".encode())
    objects.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")

    for stream, content_id, page_id in zip(streams, content_ids, page_ids):
        objects.append(
            b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream"
        )
        page_obj = (
            f"<< /Type /Page /Parent {pages_id} 0 R /MediaBox [0 0 {PAGE_WIDTH} {PAGE_HEIGHT}] "
            f"/Resources << /Font << /{FONT} {font_id} 0 R >> >> /Contents {content_id} 0 R >>"
        ).encode()
        objects.append(page_obj)

    pdf = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets = [0]
    for obj_id, obj in enumerate(objects, start=1):
        offsets.append(len(pdf))
        pdf.extend(f"{obj_id} 0 obj\n".encode())
        pdf.extend(obj)
        pdf.extend(b"\nendobj\n")

    xref_offset = len(pdf)
    pdf.extend(f"xref\n0 {len(objects) + 1}\n".encode())
    pdf.extend(b"0000000000 65535 f \n")
    for offset in offsets[1:]:
        pdf.extend(f"{offset:010d} 00000 n \n".encode())
    pdf.extend(
        (
            f"trailer\n<< /Size {len(objects) + 1} /Root {catalog_id} 0 R >>\n"
            f"startxref\n{xref_offset}\n%%EOF\n"
        ).encode()
    )
    TARGET.write_bytes(pdf)


def main() -> None:
    markdown = SOURCE.read_text(encoding="utf-8")
    pages = layout(prepare_lines(markdown))
    write_pdf(pages)
    print(f"Wrote {TARGET} ({len(pages)} pages)")


if __name__ == "__main__":
    main()
