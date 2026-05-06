import re

from schemas import IngestionJob, ParsedSection


_FRONTMATTER_DELIMITER = re.compile(r"^\s*---\s*$")
_ITEM_HEADING = re.compile(r"^(item\s+\d+[a-z]?\.?\s+.+)$", re.IGNORECASE)
_PART_HEADING = re.compile(r"^(part\s+[ivx]+\.?)$", re.IGNORECASE)
_PAGE_NUMBER = re.compile(r"^\s*\d+\s*$")


def extract_markdown_frontmatter(raw_content: str) -> tuple[dict[str, str], str]:
    """Extract simple YAML frontmatter without depending on a YAML parser."""
    lines = raw_content.splitlines(keepends=True)
    if not lines or not _FRONTMATTER_DELIMITER.match(lines[0]):
        return {}, raw_content

    metadata: dict[str, str] = {}
    end_index: int | None = None
    for i, line in enumerate(lines[1:], start=1):
        if _FRONTMATTER_DELIMITER.match(line):
            end_index = i
            break
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or ":" not in stripped:
            continue
        key, value = stripped.split(":", 1)
        key = key.strip()
        value = value.strip().strip("'\"")
        if key:
            metadata[key] = value

    if end_index is None:
        return {}, raw_content
    return metadata, "".join(lines[end_index + 1 :])


def _bold_heading_text(line: str) -> str | None:
    if line.startswith("|") or line.startswith("#"):
        return None

    match = re.fullmatch(r"\*{2,3}\s*(.+?)\s*\*{2,3}", line)
    if not match:
        return None

    text = re.sub(r"\s+", " ", match.group(1)).strip()
    return text or None


def _looks_like_heading(text: str) -> bool:
    if _ITEM_HEADING.match(text) or _PART_HEADING.match(text):
        return True
    if len(text) > 90 or text.isupper():
        return False
    return bool(re.search(r"[A-Za-z]", text))


def normalize_markdown_for_sections(raw_content: str) -> str:
    _, body = extract_markdown_frontmatter(raw_content)
    normalized_lines: list[str] = []
    in_filing_body = False

    for line in body.splitlines():
        stripped = line.strip()
        if _PAGE_NUMBER.match(stripped):
            continue

        heading = _bold_heading_text(stripped)
        if heading and heading.strip("*").lower() == "table of contents":
            continue
        if heading and (_ITEM_HEADING.match(heading) or _PART_HEADING.match(heading)):
            in_filing_body = True
        if heading and _looks_like_heading(heading) and (
            in_filing_body or _ITEM_HEADING.match(heading) or _PART_HEADING.match(heading)
        ):
            if _PART_HEADING.match(heading):
                normalized_lines.append(f"# {heading}")
            elif _ITEM_HEADING.match(heading):
                normalized_lines.append(f"## {heading}")
            else:
                normalized_lines.append(f"### {heading}")
            continue

        normalized_lines.append(line)

    return "\n".join(normalized_lines)


def parse_pdf(raw_bytes: bytes) -> list[ParsedSection]:
    import fitz  # PyMuPDF

    doc = fitz.open(stream=raw_bytes, filetype="pdf")
    sections = []
    for page_num in range(len(doc)):
        page = doc[page_num]
        text = page.get_text()
        if text.strip():
            sections.append(
                ParsedSection(
                    content=text,
                    page_number=page_num + 1,
                    section=None,
                )
            )
    return sections


def parse_markdown(raw_content: str) -> list[ParsedSection]:
    raw_content = normalize_markdown_for_sections(raw_content)
    blocks = []
    current_section = None
    current_item = None
    current_lines: list[str] = []

    for line in raw_content.splitlines(keepends=True):
        if line.startswith("#"):
            if current_lines:
                text = "".join(current_lines).strip()
                if text:
                    blocks.append(
                        ParsedSection(
                            content=text,
                            page_number=None,
                            section=current_section,
                        )
                    )
            heading_level = len(line) - len(line.lstrip("#"))
            heading = line.lstrip("#").strip()
            if heading_level <= 1:
                current_item = None
                current_section = heading
            elif heading_level == 2:
                current_item = heading
                current_section = heading
            elif current_item:
                current_section = f"{current_item} / {heading}"
            else:
                current_section = heading
            current_lines = []
        else:
            current_lines.append(line)

    if current_lines:
        text = "".join(current_lines).strip()
        if text:
            blocks.append(
                ParsedSection(content=text, page_number=None, section=current_section)
            )

    return blocks if blocks else [ParsedSection(content=raw_content, page_number=None, section=None)]


def parse_html(raw_content: str) -> list[ParsedSection]:
    try:
        from bs4 import BeautifulSoup

        soup = BeautifulSoup(raw_content, "html.parser")
        text = soup.get_text(separator="\n")
    except ImportError:
        text = raw_content
    return [ParsedSection(content=text.strip(), page_number=None, section=None)]


def parse_wiki(raw_content: str) -> list[ParsedSection]:
    return parse_markdown(raw_content)


def parse_structured(raw_content: str) -> list[ParsedSection]:
    return [ParsedSection(content=raw_content, page_number=None, section=None)]


def parse_job(job: IngestionJob) -> IngestionJob:
    match job.source_type:
        case "pdf":
            sections = parse_pdf(job.raw_content_bytes or b"")
        case "html":
            sections = parse_html(job.raw_content or "")
        case "markdown":
            sections = parse_markdown(job.raw_content or "")
        case "wiki_export":
            sections = parse_wiki(job.raw_content or "")
        case "db_export":
            sections = parse_structured(job.raw_content or "")
        case _:
            sections = [
                ParsedSection(content=job.raw_content or "", page_number=None, section=None)
            ]

    return job.model_copy(update={"parsed_sections": sections, "stage": "parser"})
