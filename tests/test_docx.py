"""Tests for DOCX document comparison with formatting awareness."""

from __future__ import annotations

import json
import os
import tempfile
import zipfile
from typing import Any

import pytest

# ── DOCX fixture builder ─────────────────────────────────────────────
# Creates minimal valid .docx files from paragraph/run descriptions so
# tests are self-contained (no binary fixture files needed).

WORD_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
REL_NS = "http://schemas.openxmlformats.org/package/2006/relationships"
CT_NS = "http://schemas.openxmlformats.org/package/2006/content-types"
OFFREL_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"


def _build_run_xml(text: str, props: dict[str, str] | None = None) -> str:
    """Build a <w:r> element string."""
    rpr = ""
    if props:
        rpr_parts: list[str] = []
        for key, val in props.items():
            if key in ("b", "i", "strike", "dstrike", "caps", "smallCaps"):
                if val == "true":
                    rpr_parts.append(f'<w:{key}/>')
                else:
                    rpr_parts.append(f'<w:{key} w:val="{val}"/>')
            elif key == "u":
                rpr_parts.append(f'<w:u w:val="{val}"/>')
            elif key == "sz":
                rpr_parts.append(f'<w:sz w:val="{val}"/>')
            elif key == "color":
                rpr_parts.append(f'<w:color w:val="{val}"/>')
            elif key == "font":
                rpr_parts.append(f'<w:rFonts w:ascii="{val}"/>')
            elif key == "highlight":
                rpr_parts.append(f'<w:highlight w:val="{val}"/>')
            elif key == "vertAlign":
                rpr_parts.append(f'<w:vertAlign w:val="{val}"/>')
        if rpr_parts:
            rpr = "<w:rPr>" + "".join(rpr_parts) + "</w:rPr>"

    # xml:space="preserve" keeps leading/trailing spaces
    return f'<w:r>{rpr}<w:t xml:space="preserve">{text}</w:t></w:r>'


def _build_para_xml(
    runs: list[dict[str, Any]],
    props: dict[str, str] | None = None,
) -> str:
    """Build a <w:p> element string.

    Each run dict has ``text`` and optional ``props``.
    """
    ppr = ""
    if props:
        ppr_parts: list[str] = []
        if "paragraph_style" in props:
            ppr_parts.append(f'<w:pStyle w:val="{props["paragraph_style"]}"/>')
        if "alignment" in props:
            ppr_parts.append(f'<w:jc w:val="{props["alignment"]}"/>')
        if ppr_parts:
            ppr = "<w:pPr>" + "".join(ppr_parts) + "</w:pPr>"

    run_xml = "".join(
        _build_run_xml(r["text"], r.get("props")) for r in runs
    )
    return f"<w:p>{ppr}{run_xml}</w:p>"


def build_docx(paragraphs: list[dict[str, Any]]) -> bytes:
    """Build a minimal .docx (ZIP) from a list of paragraph descriptions.

    Each paragraph dict:
    - ``runs``: list of ``{"text": str, "props": dict | None}``
    - ``props``: optional dict of paragraph-level properties
    """
    body_parts = [_build_para_xml(p["runs"], p.get("props")) for p in paragraphs]
    body_xml = "".join(body_parts)

    document_xml = (
        f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        f'<w:document xmlns:w="{WORD_NS}">'
        f"<w:body>{body_xml}</w:body>"
        f"</w:document>"
    )

    content_types = (
        f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        f'<Types xmlns="{CT_NS}">'
        f'<Default Extension="xml" ContentType="application/xml"/>'
        f'<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        f'<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
        f'</Types>'
    )

    rels = (
        f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        f'<Relationships xmlns="{REL_NS}">'
        f'<Relationship Id="rId1" Type="{OFFREL_NS}/officeDocument" Target="word/document.xml"/>'
        f'</Relationships>'
    )

    import io
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("[Content_Types].xml", content_types)
        zf.writestr("_rels/.rels", rels)
        zf.writestr("word/document.xml", document_xml)
    return buf.getvalue()


def write_docx(path: str, paragraphs: list[dict[str, Any]]) -> None:
    """Write a .docx to *path*."""
    with open(path, "wb") as f:
        f.write(build_docx(paragraphs))


# ── Skip if lxml not available ────────────────────────────────────────

pytest.importorskip("lxml")

from redlines import Redlines  # noqa: E402
from redlines.docx import DocxFile, DocxProcessor, DOCX_AVAILABLE  # noqa: E402
from redlines.processor import RichToken  # noqa: E402


# ── Parser tests ──────────────────────────────────────────────────────

class TestDocxParser:
    """Test the low-level XML parser."""

    def test_simple_paragraph(self, tmp_path: Any) -> None:
        path = str(tmp_path / "simple.docx")
        write_docx(path, [
            {"runs": [{"text": "Hello world"}]},
        ])

        from redlines.docx_parser import parse_docx
        paragraphs = parse_docx(path)

        assert len(paragraphs) == 1
        assert len(paragraphs[0]["runs"]) == 1
        assert paragraphs[0]["runs"][0]["text"] == "Hello world"

    def test_bold_run(self, tmp_path: Any) -> None:
        path = str(tmp_path / "bold.docx")
        write_docx(path, [
            {"runs": [{"text": "Bold text", "props": {"b": "true"}}]},
        ])

        from redlines.docx_parser import parse_docx
        paragraphs = parse_docx(path)

        run = paragraphs[0]["runs"][0]
        assert run["properties"]["b"] == "true"

    def test_multiple_runs(self, tmp_path: Any) -> None:
        path = str(tmp_path / "multi.docx")
        write_docx(path, [
            {"runs": [
                {"text": "Normal "},
                {"text": "bold ", "props": {"b": "true"}},
                {"text": "italic", "props": {"i": "true"}},
            ]},
        ])

        from redlines.docx_parser import parse_docx
        paragraphs = parse_docx(path)

        runs = paragraphs[0]["runs"]
        assert len(runs) == 3
        assert runs[0]["text"] == "Normal "
        assert "b" not in runs[0]["properties"]
        assert runs[1]["properties"]["b"] == "true"
        assert runs[2]["properties"]["i"] == "true"

    def test_paragraph_style(self, tmp_path: Any) -> None:
        path = str(tmp_path / "styled.docx")
        write_docx(path, [
            {
                "runs": [{"text": "Heading"}],
                "props": {"paragraph_style": "Heading1"},
            },
        ])

        from redlines.docx_parser import parse_docx
        paragraphs = parse_docx(path)

        assert paragraphs[0]["properties"]["paragraph_style"] == "Heading1"

    def test_paragraph_alignment(self, tmp_path: Any) -> None:
        path = str(tmp_path / "aligned.docx")
        write_docx(path, [
            {
                "runs": [{"text": "Centered"}],
                "props": {"alignment": "center"},
            },
        ])

        from redlines.docx_parser import parse_docx
        paragraphs = parse_docx(path)

        assert paragraphs[0]["properties"]["alignment"] == "center"

    def test_font_and_size(self, tmp_path: Any) -> None:
        path = str(tmp_path / "font.docx")
        write_docx(path, [
            {"runs": [{"text": "Big text", "props": {"sz": "48", "font": "Arial"}}]},
        ])

        from redlines.docx_parser import parse_docx
        paragraphs = parse_docx(path)

        run = paragraphs[0]["runs"][0]
        assert run["properties"]["sz"] == "48"
        assert run["properties"]["font"] == "Arial"

    def test_color_and_highlight(self, tmp_path: Any) -> None:
        path = str(tmp_path / "color.docx")
        write_docx(path, [
            {"runs": [{"text": "Colored", "props": {"color": "FF0000", "highlight": "yellow"}}]},
        ])

        from redlines.docx_parser import parse_docx
        paragraphs = parse_docx(path)

        run = paragraphs[0]["runs"][0]
        assert run["properties"]["color"] == "FF0000"
        assert run["properties"]["highlight"] == "yellow"

    def test_empty_document(self, tmp_path: Any) -> None:
        path = str(tmp_path / "empty.docx")
        write_docx(path, [])

        from redlines.docx_parser import parse_docx
        paragraphs = parse_docx(path)

        assert paragraphs == []

    def test_multiple_paragraphs(self, tmp_path: Any) -> None:
        path = str(tmp_path / "multi_para.docx")
        write_docx(path, [
            {"runs": [{"text": "First paragraph"}]},
            {"runs": [{"text": "Second paragraph"}]},
        ])

        from redlines.docx_parser import parse_docx
        paragraphs = parse_docx(path)

        assert len(paragraphs) == 2
        assert paragraphs[0]["runs"][0]["text"] == "First paragraph"
        assert paragraphs[1]["runs"][0]["text"] == "Second paragraph"


# ── RichToken tests ───────────────────────────────────────────────────

class TestRichToken:
    def test_equality_same(self) -> None:
        a = RichToken("hello", (("b", "true"),))
        b = RichToken("hello", (("b", "true"),))
        assert a == b
        assert hash(a) == hash(b)

    def test_inequality_different_text(self) -> None:
        a = RichToken("hello", (("b", "true"),))
        b = RichToken("world", (("b", "true"),))
        assert a != b

    def test_inequality_different_formatting(self) -> None:
        a = RichToken("hello", (("b", "true"),))
        b = RichToken("hello", (("b", "false"),))
        assert a != b

    def test_inequality_formatting_vs_none(self) -> None:
        a = RichToken("hello", (("b", "true"),))
        b = RichToken("hello", ())
        assert a != b

    def test_str(self) -> None:
        t = RichToken("word ", (("i", "true"),))
        assert str(t) == "word "

    def test_formatting_dict(self) -> None:
        t = RichToken("x", (("b", "true"), ("sz", "24")))
        assert t.formatting_dict == {"b": "true", "sz": "24"}

    def test_normalized(self) -> None:
        t = RichToken("word  ", (("b", "true"),))
        n = t.normalized()
        assert n.text == "word"
        assert n.formatting == t.formatting


# ── DocxFile tests ────────────────────────────────────────────────────

class TestDocxFile:
    def test_text_property(self, tmp_path: Any) -> None:
        path = str(tmp_path / "test.docx")
        write_docx(path, [
            {"runs": [{"text": "Hello world"}]},
        ])

        doc = DocxFile(path)
        assert doc.text == "Hello world"

    def test_text_multiple_paragraphs(self, tmp_path: Any) -> None:
        path = str(tmp_path / "test.docx")
        write_docx(path, [
            {"runs": [{"text": "First"}]},
            {"runs": [{"text": "Second"}]},
        ])

        doc = DocxFile(path)
        assert doc.text == "First\n\nSecond"

    def test_rich_tokens(self, tmp_path: Any) -> None:
        path = str(tmp_path / "test.docx")
        write_docx(path, [
            {"runs": [
                {"text": "Hello ", "props": {"b": "true"}},
                {"text": "world"},
            ]},
        ])

        doc = DocxFile(path)
        tokens = doc.rich_tokens

        # "Hello " is one token, "world" is another
        assert len(tokens) == 2
        hello_tok = tokens[0]
        assert hello_tok.text == "Hello "
        assert ("b", "true") in hello_tok.formatting

        world_tok = tokens[1]
        assert world_tok.text == "world"
        assert ("b", "true") not in world_tok.formatting

    def test_rich_tokens_paragraph_separator(self, tmp_path: Any) -> None:
        path = str(tmp_path / "test.docx")
        write_docx(path, [
            {"runs": [{"text": "First"}]},
            {"runs": [{"text": "Second"}]},
        ])

        doc = DocxFile(path)
        tokens = doc.rich_tokens

        # Should be: "First", " ¶ ", "Second"
        assert len(tokens) == 3
        assert tokens[1].text == " ¶ "

    def test_rich_tokens_carry_paragraph_props(self, tmp_path: Any) -> None:
        path = str(tmp_path / "test.docx")
        write_docx(path, [
            {
                "runs": [{"text": "Heading text"}],
                "props": {"paragraph_style": "Heading1"},
            },
        ])

        doc = DocxFile(path)
        tokens = doc.rich_tokens

        # Each word token carries paragraph_style
        for tok in tokens:
            if tok.text.strip():
                assert ("paragraph_style", "Heading1") in tok.formatting


# ── DocxProcessor tests ──────────────────────────────────────────────

class TestDocxProcessor:
    def test_identical_docs(self, tmp_path: Any) -> None:
        path1 = str(tmp_path / "a.docx")
        path2 = str(tmp_path / "b.docx")
        paras = [{"runs": [{"text": "Hello world"}]}]
        write_docx(path1, paras)
        write_docx(path2, paras)

        doc1 = DocxFile(path1)
        doc2 = DocxFile(path2)
        proc = DocxProcessor()
        ops = proc.process(doc1, doc2)

        # Only equal operations
        assert all(op.opcodes[0] == "equal" for op in ops)

    def test_text_change_detected(self, tmp_path: Any) -> None:
        path1 = str(tmp_path / "a.docx")
        path2 = str(tmp_path / "b.docx")
        write_docx(path1, [{"runs": [{"text": "Hello world"}]}])
        write_docx(path2, [{"runs": [{"text": "Hello earth"}]}])

        doc1 = DocxFile(path1)
        doc2 = DocxFile(path2)
        proc = DocxProcessor()
        ops = proc.process(doc1, doc2)

        tags = [op.opcodes[0] for op in ops]
        assert "replace" in tags

    def test_formatting_change_detected(self, tmp_path: Any) -> None:
        """Same text but different formatting should be a replace."""
        path1 = str(tmp_path / "a.docx")
        path2 = str(tmp_path / "b.docx")
        write_docx(path1, [{"runs": [{"text": "Hello world"}]}])
        write_docx(path2, [{"runs": [{"text": "Hello world", "props": {"b": "true"}}]}])

        doc1 = DocxFile(path1)
        doc2 = DocxFile(path2)
        proc = DocxProcessor()
        ops = proc.process(doc1, doc2)

        tags = [op.opcodes[0] for op in ops]
        assert "replace" in tags

    def test_paragraph_style_change_detected(self, tmp_path: Any) -> None:
        """Changing paragraph style should be a replace."""
        path1 = str(tmp_path / "a.docx")
        path2 = str(tmp_path / "b.docx")
        write_docx(path1, [
            {"runs": [{"text": "Some text"}], "props": {"paragraph_style": "Normal"}},
        ])
        write_docx(path2, [
            {"runs": [{"text": "Some text"}], "props": {"paragraph_style": "Heading1"}},
        ])

        doc1 = DocxFile(path1)
        doc2 = DocxFile(path2)
        proc = DocxProcessor()
        ops = proc.process(doc1, doc2)

        tags = [op.opcodes[0] for op in ops]
        assert "replace" in tags

    def test_rich_tokens_on_chunks(self, tmp_path: Any) -> None:
        path1 = str(tmp_path / "a.docx")
        path2 = str(tmp_path / "b.docx")
        write_docx(path1, [{"runs": [{"text": "Hello"}]}])
        write_docx(path2, [{"runs": [{"text": "Hello"}]}])

        doc1 = DocxFile(path1)
        doc2 = DocxFile(path2)
        proc = DocxProcessor()
        ops = proc.process(doc1, doc2)

        # Chunks should carry rich_tokens
        assert ops[0].source_chunk.rich_tokens is not None
        assert ops[0].test_chunk.rich_tokens is not None


# ── Integration tests via Redlines ────────────────────────────────────

class TestDocxRedlinesIntegration:
    def test_auto_selects_docx_processor(self, tmp_path: Any) -> None:
        path1 = str(tmp_path / "a.docx")
        path2 = str(tmp_path / "b.docx")
        write_docx(path1, [{"runs": [{"text": "Hello world"}]}])
        write_docx(path2, [{"runs": [{"text": "Hello earth"}]}])

        doc1 = DocxFile(path1)
        doc2 = DocxFile(path2)
        diff = Redlines(doc1, doc2)

        assert isinstance(diff.processor, DocxProcessor)

    def test_changes_property(self, tmp_path: Any) -> None:
        path1 = str(tmp_path / "a.docx")
        path2 = str(tmp_path / "b.docx")
        write_docx(path1, [{"runs": [{"text": "The quick brown fox"}]}])
        write_docx(path2, [{"runs": [{"text": "The slow brown fox"}]}])

        diff = Redlines(DocxFile(path1), DocxFile(path2))
        changes = diff.changes

        assert len(changes) == 1
        assert changes[0].operation == "replace"
        assert "quick" in (changes[0].source_text or "")
        assert "slow" in (changes[0].test_text or "")

    def test_stats(self, tmp_path: Any) -> None:
        path1 = str(tmp_path / "a.docx")
        path2 = str(tmp_path / "b.docx")
        write_docx(path1, [{"runs": [{"text": "Hello world"}]}])
        write_docx(path2, [{"runs": [{"text": "Hello earth"}]}])

        diff = Redlines(DocxFile(path1), DocxFile(path2))
        stats = diff.stats()

        assert stats.total_changes == 1
        assert stats.replacements == 1

    def test_output_json_plain_text_change(self, tmp_path: Any) -> None:
        path1 = str(tmp_path / "a.docx")
        path2 = str(tmp_path / "b.docx")
        write_docx(path1, [{"runs": [{"text": "Hello world"}]}])
        write_docx(path2, [{"runs": [{"text": "Hello earth"}]}])

        diff = Redlines(DocxFile(path1), DocxFile(path2))
        data = json.loads(diff.output_json())

        assert "changes" in data
        assert "stats" in data

        # Source tokens should be rich (dicts with "text" and "formatting")
        assert isinstance(data["source_tokens"][0], dict)
        assert "text" in data["source_tokens"][0]

    def test_output_json_formatting_change(self, tmp_path: Any) -> None:
        """Same text, different formatting → replace with formatting_changes."""
        path1 = str(tmp_path / "a.docx")
        path2 = str(tmp_path / "b.docx")
        write_docx(path1, [{"runs": [{"text": "Hello"}]}])
        write_docx(path2, [{"runs": [{"text": "Hello", "props": {"b": "true"}}]}])

        diff = Redlines(DocxFile(path1), DocxFile(path2))
        data = json.loads(diff.output_json(pretty=True))

        # Find the replace change
        replaces = [c for c in data["changes"] if c["type"] == "replace"]
        assert len(replaces) >= 1

        replace = replaces[0]
        assert replace["text_changed"] is False
        assert "formatting_changes" in replace
        assert "b" in replace["formatting_changes"]

    def test_output_json_formatting_and_text_change(self, tmp_path: Any) -> None:
        path1 = str(tmp_path / "a.docx")
        path2 = str(tmp_path / "b.docx")
        write_docx(path1, [{"runs": [{"text": "Hello world"}]}])
        write_docx(path2, [{"runs": [{"text": "Hello earth", "props": {"b": "true"}}]}])

        diff = Redlines(DocxFile(path1), DocxFile(path2))
        data = json.loads(diff.output_json())

        replaces = [c for c in data["changes"] if c["type"] == "replace"]
        assert len(replaces) >= 1

    def test_output_json_insert_and_delete(self, tmp_path: Any) -> None:
        path1 = str(tmp_path / "a.docx")
        path2 = str(tmp_path / "b.docx")
        write_docx(path1, [{"runs": [{"text": "Hello beautiful world"}]}])
        write_docx(path2, [{"runs": [{"text": "Hello world"}]}])

        diff = Redlines(DocxFile(path1), DocxFile(path2))
        data = json.loads(diff.output_json())

        types = {c["type"] for c in data["changes"]}
        assert "equal" in types
        assert "delete" in types or "replace" in types

    def test_output_json_identical_docs(self, tmp_path: Any) -> None:
        path1 = str(tmp_path / "a.docx")
        path2 = str(tmp_path / "b.docx")
        paras = [{"runs": [{"text": "Hello world"}]}]
        write_docx(path1, paras)
        write_docx(path2, paras)

        diff = Redlines(DocxFile(path1), DocxFile(path2))
        data = json.loads(diff.output_json())

        assert data["stats"]["total_changes"] == 0
        types = {c["type"] for c in data["changes"]}
        assert types == {"equal"}

    def test_output_json_paragraph_style_change(self, tmp_path: Any) -> None:
        """Paragraph style change shows in formatting_changes."""
        path1 = str(tmp_path / "a.docx")
        path2 = str(tmp_path / "b.docx")
        write_docx(path1, [
            {"runs": [{"text": "Title"}], "props": {"paragraph_style": "Normal"}},
        ])
        write_docx(path2, [
            {"runs": [{"text": "Title"}], "props": {"paragraph_style": "Heading1"}},
        ])

        diff = Redlines(DocxFile(path1), DocxFile(path2))
        data = json.loads(diff.output_json(pretty=True))

        replaces = [c for c in data["changes"] if c["type"] == "replace"]
        assert len(replaces) >= 1
        replace = replaces[0]
        assert replace["text_changed"] is False
        assert "paragraph_style" in replace.get("formatting_changes", {})

    def test_multi_paragraph_change(self, tmp_path: Any) -> None:
        path1 = str(tmp_path / "a.docx")
        path2 = str(tmp_path / "b.docx")
        write_docx(path1, [
            {"runs": [{"text": "First paragraph"}]},
            {"runs": [{"text": "Second paragraph"}]},
        ])
        write_docx(path2, [
            {"runs": [{"text": "First paragraph"}]},
            {"runs": [{"text": "Modified paragraph"}]},
        ])

        diff = Redlines(DocxFile(path1), DocxFile(path2))
        changes = diff.changes

        assert len(changes) == 1
        assert changes[0].operation == "replace"

    def test_markdown_output_still_works(self, tmp_path: Any) -> None:
        """Markdown output uses plain text tokens and shouldn't break."""
        path1 = str(tmp_path / "a.docx")
        path2 = str(tmp_path / "b.docx")
        write_docx(path1, [{"runs": [{"text": "Hello world"}]}])
        write_docx(path2, [{"runs": [{"text": "Hello earth"}]}])

        diff = Redlines(DocxFile(path1), DocxFile(path2))
        md = diff.output_markdown

        assert "world" in md
        assert "earth" in md

    def test_opcodes(self, tmp_path: Any) -> None:
        path1 = str(tmp_path / "a.docx")
        path2 = str(tmp_path / "b.docx")
        write_docx(path1, [{"runs": [{"text": "Hello world"}]}])
        write_docx(path2, [{"runs": [{"text": "Hello earth"}]}])

        diff = Redlines(DocxFile(path1), DocxFile(path2))
        opcodes = diff.opcodes

        assert isinstance(opcodes, list)
        assert all(isinstance(op, tuple) and len(op) == 5 for op in opcodes)


# ── Edge cases ────────────────────────────────────────────────────────

class TestDocxEdgeCases:
    def test_empty_runs_ignored(self, tmp_path: Any) -> None:
        """Paragraphs with empty text should not produce tokens."""
        path = str(tmp_path / "empty_run.docx")
        write_docx(path, [
            {"runs": [{"text": ""}]},
            {"runs": [{"text": "Real text"}]},
        ])

        doc = DocxFile(path)
        # Only "Real text" tokens, no separator for empty paragraph
        assert all("¶" not in tok.text for tok in doc.rich_tokens if tok.text.strip())

    def test_docx_processor_rejects_strings(self) -> None:
        proc = DocxProcessor()
        with pytest.raises(TypeError, match="DocxProcessor requires DocxFile"):
            proc.process("hello", "world")

    def test_underline_property(self, tmp_path: Any) -> None:
        path = str(tmp_path / "underline.docx")
        write_docx(path, [
            {"runs": [{"text": "Underlined", "props": {"u": "single"}}]},
        ])

        from redlines.docx_parser import parse_docx
        paragraphs = parse_docx(path)

        assert paragraphs[0]["runs"][0]["properties"]["u"] == "single"


# ── File-based comparison (tests/documents/DocxFile/) ─────────────────

FIXTURES = os.path.join(os.path.dirname(__file__), "documents", "DocxFile")


class TestDocxFileComparison:
    """Compare the persistent source.docx and test.docx fixture files.

    The fixtures represent a short "Service Agreement" document where
    ``test.docx`` has deliberate text, formatting, and structural changes
    relative to ``source.docx``:

    * Text change: "hereby agrees" → "consents"
    * Formatting-only change: "in good faith" gains bold (was italic-only)
    * Paragraph style change: "Terms and Conditions" Normal → Heading2
    * Alignment change: CONFIDENTIAL centered → left, red color removed
    * New paragraph appended
    """

    @pytest.fixture()
    def diff(self) -> Redlines:
        source = DocxFile(os.path.join(FIXTURES, "source.docx"))
        test = DocxFile(os.path.join(FIXTURES, "test.docx"))
        return Redlines(source, test)

    @pytest.fixture()
    def diff_json(self, diff: Redlines) -> dict[str, Any]:
        return json.loads(diff.output_json(pretty=True))

    # ── basic properties ──────────────────────────────────────────────

    def test_source_text_extracted(self, diff: Redlines) -> None:
        assert "Service Agreement" in diff.source
        assert "CONFIDENTIAL" in diff.source

    def test_test_text_extracted(self, diff: Redlines) -> None:
        assert "Service Agreement" in diff.test
        assert "date of signing" in diff.test

    def test_processor_is_docx(self, diff: Redlines) -> None:
        assert isinstance(diff.processor, DocxProcessor)

    # ── stats ─────────────────────────────────────────────────────────

    def test_total_changes(self, diff: Redlines) -> None:
        stats = diff.stats()
        assert stats.total_changes == 4
        assert stats.replacements == 4

    # ── text change: "hereby agrees" → "consents" ────────────────────

    def test_text_change_detected(self, diff_json: dict[str, Any]) -> None:
        replaces = [c for c in diff_json["changes"] if c["type"] == "replace"]
        text_changes = [
            c for c in replaces
            if c.get("text_changed") is True
            and "agrees" in (c.get("source_text") or "")
        ]
        assert len(text_changes) == 1
        assert "consents" in text_changes[0]["test_text"]

    def test_text_change_has_underline_formatting_diff(
        self, diff_json: dict[str, Any]
    ) -> None:
        """'consents' also gained underline, so formatting_changes includes u."""
        replaces = [c for c in diff_json["changes"] if c["type"] == "replace"]
        text_changes = [
            c for c in replaces if "agrees" in (c.get("source_text") or "")
        ]
        fmt = text_changes[0].get("formatting_changes", {})
        assert "u" in fmt
        assert fmt["u"]["to"] == "single"

    # ── formatting-only: "in good faith" italic → bold+italic ────────

    def test_formatting_only_change(self, diff_json: dict[str, Any]) -> None:
        replaces = [c for c in diff_json["changes"] if c["type"] == "replace"]
        fmt_only = [
            c for c in replaces
            if c.get("text_changed") is False
            and "good faith" in (c.get("source_text") or "")
        ]
        assert len(fmt_only) == 1
        fmt = fmt_only[0]["formatting_changes"]
        assert fmt["b"]["from"] is None
        assert fmt["b"]["to"] == "true"

    # ── paragraph style change: Normal → Heading2 ────────────────────

    def test_paragraph_style_change(self, diff_json: dict[str, Any]) -> None:
        replaces = [c for c in diff_json["changes"] if c["type"] == "replace"]
        style_changes = [
            c for c in replaces
            if c.get("text_changed") is False
            and "Terms" in (c.get("source_text") or "")
        ]
        assert len(style_changes) == 1
        fmt = style_changes[0]["formatting_changes"]
        assert "paragraph_style" in fmt
        assert fmt["paragraph_style"]["to"] == "Heading2"

    # ── alignment + color change on CONFIDENTIAL ─────────────────────

    def test_alignment_and_color_change(self, diff_json: dict[str, Any]) -> None:
        replaces = [c for c in diff_json["changes"] if c["type"] == "replace"]
        conf = [
            c for c in replaces if "CONFIDENTIAL" in (c.get("source_text") or "")
        ]
        assert len(conf) == 1
        fmt = conf[0].get("formatting_changes", {})
        assert fmt["alignment"]["from"] == "center"
        assert fmt["alignment"]["to"] == "left"
        assert fmt["color"]["from"] == "FF0000"
        assert fmt["color"]["to"] is None

    # ── JSON structure validation ─────────────────────────────────────

    def test_tokens_are_rich(self, diff_json: dict[str, Any]) -> None:
        """source_tokens and test_tokens carry formatting dicts."""
        for tok in diff_json["source_tokens"]:
            assert isinstance(tok, dict)
            assert "text" in tok
            assert "formatting" in tok

    def test_changes_cover_full_text(self, diff_json: dict[str, Any]) -> None:
        """Equal + changed spans should cover all source tokens."""
        total_source_span = 0
        for c in diff_json["changes"]:
            if c["type"] in ("equal", "delete", "replace"):
                i1, i2 = c["source_token_position"]
                total_source_span += i2 - i1
        assert total_source_span == len(diff_json["source_tokens"])

    def test_stats_section(self, diff_json: dict[str, Any]) -> None:
        stats = diff_json["stats"]
        assert stats["replacements"] == 4
        assert stats["total_changes"] == 4
        assert stats["insertions"] == 0
        assert stats["deletions"] == 0
        assert 0 < stats["change_ratio"] < 1

    # ── markdown output ──────────────────────────────────────────────

    def test_markdown_output(self, diff: Redlines) -> None:
        md = diff.output_markdown
        assert isinstance(md, str)
        assert "Service Agreement" in md

    def test_markdown_formatting_only_not_del_ins(self, diff: Redlines) -> None:
        """Formatting-only changes should NOT show del+ins of same text."""
        md = diff.output_markdown
        # "in good faith" is formatting-only (italic → bold+italic).
        # It should appear once in blue, not as strikethrough + insertion.
        assert "line-through;'>in good faith" not in md

    def test_markdown_formatting_only_has_annotation(self, diff: Redlines) -> None:
        md = diff.output_markdown
        assert "[+bold]" in md

    def test_markdown_style_change_annotation(self, diff: Redlines) -> None:
        md = diff.output_markdown
        assert "+style: Heading2" in md

    def test_markdown_text_change_still_del_ins(self, diff: Redlines) -> None:
        """Text changes should still use standard del+ins."""
        md = diff.output_markdown
        assert "hereby agrees" in md
        assert "consents" in md

    def test_markdown_text_change_with_formatting_note(self, diff: Redlines) -> None:
        """Text change that also has formatting diff should include a note."""
        md = diff.output_markdown
        assert "+underline: single" in md

    # ── rich (terminal) output ───────────────────────────────────────

    def test_rich_output(self, diff: Redlines) -> None:
        from rich.text import Text
        rich = diff.output_rich
        assert isinstance(rich, Text)
        plain = rich.plain
        assert "Service Agreement" in plain

    def test_rich_formatting_only_has_annotation(self, diff: Redlines) -> None:
        plain = diff.output_rich.plain
        assert "[+bold]" in plain

    def test_rich_style_change_annotation(self, diff: Redlines) -> None:
        plain = diff.output_rich.plain
        assert "+style: Heading2" in plain
