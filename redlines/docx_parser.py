"""Low-level DOCX XML parsing using zipfile + lxml.

Extracts paragraph and run structure from ``word/document.xml`` inside a
``.docx`` file.  Each paragraph is returned as a dict with ``properties``
(paragraph-level formatting) and ``runs`` (list of text segments with
character-level formatting).

Only the main document body is parsed — headers, footers, comments and
footnotes are ignored.  Track-change markup (``<w:ins>``/``<w:del>``) is
read as-is (accepted state) rather than resolved.
"""

from __future__ import annotations

import os
import zipfile
from io import BytesIO
from typing import Any

from lxml import etree

# ── OOXML namespaces ─────────────────────────────────────────────────
WORD_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
W = f"{{{WORD_NS}}}"


# ── Public API ────────────────────────────────────────────────────────

def parse_docx(
    source: str | bytes | os.PathLike[str] | BytesIO,
) -> list[dict[str, Any]]:
    """Parse a DOCX file and return a list of paragraph dicts.

    Each paragraph dict has:
    - ``properties``: ``dict[str, str]`` of paragraph-level formatting.
    - ``runs``: ``list[dict]`` where each run has ``text`` (str) and
      ``properties`` (``dict[str, str]``).

    :param source: File path, raw bytes of the ``.docx``, or a file-like
        ``BytesIO`` object.
    :returns: List of paragraph dicts.
    """
    if isinstance(source, bytes):
        buf = BytesIO(source)
    elif isinstance(source, BytesIO):
        buf = source
    else:
        buf = str(source)  # type: ignore[assignment]

    with zipfile.ZipFile(buf) as zf:
        doc_xml = zf.read("word/document.xml")

    root = etree.fromstring(doc_xml)
    body = root.find(f"{W}body")
    if body is None:
        return []

    return [_parse_paragraph(p) for p in body.findall(f"{W}p")]


# ── Paragraph parsing ─────────────────────────────────────────────────

def _parse_paragraph(p_elem: etree._Element) -> dict[str, Any]:
    ppr = p_elem.find(f"{W}pPr")
    props = _extract_paragraph_properties(ppr)

    runs: list[dict[str, Any]] = []
    for child in p_elem:
        tag = _local_tag(child)
        if tag == "r":
            run = _parse_run(child)
            if run["text"]:
                runs.append(run)
        # Track-change wrappers — read the accepted content inside them.
        elif tag in ("ins", "del"):
            for inner in child.findall(f"{W}r"):
                run = _parse_run(inner)
                if run["text"]:
                    runs.append(run)

    return {"properties": props, "runs": runs}


# ── Run parsing ───────────────────────────────────────────────────────

def _parse_run(r_elem: etree._Element) -> dict[str, Any]:
    rpr = r_elem.find(f"{W}rPr")
    props = _extract_run_properties(rpr)

    text_parts: list[str] = []
    for child in r_elem:
        tag = _local_tag(child)
        if tag == "t":
            text_parts.append(child.text or "")
        elif tag == "tab":
            text_parts.append("\t")
        elif tag == "br":
            text_parts.append("\n")

    return {"text": "".join(text_parts), "properties": props}


# ── Attribute helpers ─────────────────────────────────────────────────

def _local_tag(elem: etree._Element) -> str:
    """Return the local element name without namespace."""
    tag = elem.tag
    if isinstance(tag, str) and "}" in tag:
        return tag.split("}", 1)[1]
    return str(tag)


def _get_val(elem: etree._Element) -> str | None:
    """Get the ``val`` attribute, trying both namespaced and plain."""
    val = elem.get(f"{W}val")
    if val is None:
        val = elem.get("val")
    return val


def _is_toggle_on(elem: etree._Element | None) -> bool | None:
    """Interpret an OOXML toggle element.

    * ``<w:b/>`` (no val) → True
    * ``<w:b w:val="true"/>`` → True
    * ``<w:b w:val="false"/>`` → False
    * element absent → None
    """
    if elem is None:
        return None
    val = _get_val(elem)
    if val is None:
        return True
    return val.lower() not in ("false", "0", "off", "none")


# ── Property extraction ──────────────────────────────────────────────

def _extract_paragraph_properties(
    ppr: etree._Element | None,
) -> dict[str, str]:
    props: dict[str, str] = {}
    if ppr is None:
        return props

    # Style name
    pstyle = ppr.find(f"{W}pStyle")
    if pstyle is not None:
        val = _get_val(pstyle)
        if val:
            props["paragraph_style"] = val

    # Justification / alignment
    jc = ppr.find(f"{W}jc")
    if jc is not None:
        val = _get_val(jc)
        if val:
            props["alignment"] = val

    # Indentation
    ind = ppr.find(f"{W}ind")
    if ind is not None:
        for attr in ("left", "right", "hanging", "firstLine"):
            val = ind.get(f"{W}{attr}") or ind.get(attr)
            if val:
                props[f"indent_{attr}"] = val

    # Spacing
    spacing = ppr.find(f"{W}spacing")
    if spacing is not None:
        for attr in ("before", "after", "line", "lineRule"):
            val = spacing.get(f"{W}{attr}") or spacing.get(attr)
            if val:
                props[f"spacing_{attr}"] = val

    # Numbering (lists)
    numpr = ppr.find(f"{W}numPr")
    if numpr is not None:
        ilvl = numpr.find(f"{W}ilvl")
        if ilvl is not None:
            val = _get_val(ilvl)
            if val:
                props["num_level"] = val
        numid = numpr.find(f"{W}numId")
        if numid is not None:
            val = _get_val(numid)
            if val:
                props["num_id"] = val

    return props


def _extract_run_properties(
    rpr: etree._Element | None,
) -> dict[str, str]:
    props: dict[str, str] = {}
    if rpr is None:
        return props

    # Boolean toggles
    for prop_name in ("b", "i", "strike", "dstrike", "caps", "smallCaps"):
        elem = rpr.find(f"{W}{prop_name}")
        val = _is_toggle_on(elem)
        if val is not None:
            props[prop_name] = str(val).lower()

    # Underline
    u_elem = rpr.find(f"{W}u")
    if u_elem is not None:
        val = _get_val(u_elem)
        if val and val.lower() != "none":
            props["u"] = val

    # Font family
    rfonts = rpr.find(f"{W}rFonts")
    if rfonts is not None:
        for attr in ("ascii", "hAnsi", "eastAsia", "cs"):
            val = rfonts.get(f"{W}{attr}") or rfonts.get(attr)
            if val:
                props["font"] = val
                break

    # Font size (half-points)
    sz = rpr.find(f"{W}sz")
    if sz is not None:
        val = _get_val(sz)
        if val:
            props["sz"] = val

    # Color
    color = rpr.find(f"{W}color")
    if color is not None:
        val = _get_val(color)
        if val:
            props["color"] = val

    # Highlight
    highlight = rpr.find(f"{W}highlight")
    if highlight is not None:
        val = _get_val(highlight)
        if val:
            props["highlight"] = val

    # Superscript / subscript
    vert_align = rpr.find(f"{W}vertAlign")
    if vert_align is not None:
        val = _get_val(vert_align)
        if val:
            props["vertAlign"] = val

    return props
