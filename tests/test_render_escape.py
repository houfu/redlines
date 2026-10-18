r"""ADR-0037's escape: the worked examples, role encoding, and properties E1 to E4.

CriticMarkup defines no escape, so redlines writes a backslash at delimiter
sites with a parity rule (``redlines/renderers/_escape.py``). These tests run
the escape through the renderer's own spelling of a line
(`redlines.renderers._inplace.serialize`) and read it back with the reference
reader, ``tests/helpers/criticmarkup.py``, which was written from the ADR
rather than from the renderer:

- **E1** ``critic_unescape(critic_escape(s)) == s``, and no live site is left;
- **E2** a whole line -- syntax head, role prefix, content, marks -- survives
  emit, parse, accept-all, ``strip_roles`` and line-start unescape;
- **E3** composite documents with backslash runs right before emitted
  delimiters parse back exactly;
- **E4** the line-start site is injective.

The design runs were E1 over 1,311,111 strings, E2 over 60,000 lines and E4
over 39,062 keys. The default run uses smaller counts; the full ones are
marked ``slow``.
"""

from __future__ import annotations

import itertools
import random
from urllib.parse import quote, unquote

import pytest

from redlines.blocks import Block, BlockKind, BlockTree
from redlines.comparison import compare
from redlines.renderers._escape import (
    CRITIC_SITE,
    critic_escape,
    critic_unescape,
    encode_role,
    escape_line_start,
    html_attr,
    html_text,
)
from redlines.renderers._inplace import Chunk, Piece, render_inplace, serialize
from redlines.renderers._marks import CRITIC
from tests.helpers import criticmarkup as cm

SYMBOLS = "{}+-~>\\<=["
"""E1's exhaustive alphabet: the ten characters every site is made of."""

RANDOM_ALPHABET = list("{}+-~=><\\[] ax")
"""E1's and E2's random alphabet."""


# --- the worked examples ----------------------------------------------------

WORKED_EXAMPLES = [
    ("x++}", "x++\\}", "closer"),
    ("x++\\}", "x++\\\\\\}", "closer with a backslash run"),
    ("a~>", "a~\\>", "separator"),
    ("a~\\>", "a~\\\\\\>", "separator with a backslash run"),
    ("{++", "\\{++", "opener"),
    ("\\{++", "\\\\\\{++", "opener with a backslash run"),
    ("if (a) { b++ }", "if (a) { b++ }", "no site"),
]

LINE_START_EXAMPLES = [
    ("[x] task", "\\[x] task", "roles on"),
    ("\\[x] task", "\\\\\\[x] task", "roles on"),
    ("[link](u) here", "[link](u) here", "not role-shaped"),
    ("[Party A] shall", "[Party A] shall", "not role-shaped"),
]


@pytest.mark.parametrize(("text", "escaped", "note"), WORKED_EXAMPLES)
def test_the_worked_examples_escape_as_the_adr_writes_them(
    text: str, escaped: str, note: str
) -> None:
    assert critic_escape(text) == escaped, note
    assert critic_unescape(escaped) == text
    assert cm.critic_unescape(escaped) == text


@pytest.mark.parametrize(("text", "escaped", "note"), LINE_START_EXAMPLES)
def test_the_line_start_examples_escape_only_with_roles_on(
    text: str, escaped: str, note: str
) -> None:
    assert escape_line_start(text) == escaped, note
    assert serialize([Chunk((Piece("text", text),))], CRITIC, roles=True) == escaped
    assert serialize([Chunk((Piece("text", text),))], CRITIC, roles=False) == text


@pytest.mark.parametrize(("text", "escaped", "note"), WORKED_EXAMPLES)
def test_the_worked_examples_round_trip_as_a_whole_line(
    text: str, escaped: str, note: str
) -> None:
    line = serialize([Chunk((Piece("text", text),))], CRITIC, roles=True)
    assert line == escaped
    assert cm.lines(line, "accept") == [text]


def test_a_third_party_stripper_would_mis_pair_what_the_reference_reader_reads() -> (
    None
):
    """The ADR's example: ``use \\{++ here {++new++}`` is one insertion, of ``new``."""
    tokens = cm.parse("use \\{++ here {++new++}")
    assert tokens == (cm.Token("text", "use {++ here "), cm.Token("insert", "new"))


# --- roles --------------------------------------------------------------------


def test_encode_role_keeps_the_safe_characters_and_encodes_the_rest() -> None:
    assert encode_role("sub_clause") == "sub_clause"
    assert encode_role("a]b") == "a%5Db"
    assert encode_role("r~s") == "r%7Es"
    assert encode_role("a b") == "a%20b"
    assert encode_role("100%") == "100%25"
    assert encode_role("Ü") == "%C3%9C"


def test_urllib_quote_is_not_enough_because_it_keeps_the_tilde() -> None:
    assert quote("r~s", safe="") == "r~s"
    assert encode_role("r~s") != quote("r~s", safe="")


HOSTILE_ROLES = [
    "clause",
    "sub_clause",
    "a]b",
    "x\\y",
    "{++r",
    "r~>s",
    "per cent%",
    "%25",
    "Ünïcode",
    "a b",
    "line\nbreak",
    "",
    "[x]",
    "~",
    "%7E",
]


def test_encode_role_is_injective_and_reversible_and_carries_no_site() -> None:
    encoded = [encode_role(role) for role in HOSTILE_ROLES]
    assert len(set(encoded)) == len(HOSTILE_ROLES)
    for role, text in zip(HOSTILE_ROLES, encoded):
        assert unquote(text) == role
        assert set(text) <= set(
            "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_.-%"
        )
        assert CRITIC_SITE.search(text) is None


def test_html_escapers_are_html_escape() -> None:
    assert html_text("<a href=\"x\">'&'</a>") == "&lt;a href=\"x\"&gt;'&amp;'&lt;/a&gt;"
    assert html_attr("<\"'&>") == "&lt;&quot;&#x27;&amp;&gt;"


# --- E1 -----------------------------------------------------------------------


def _assert_e1(text: str) -> None:
    escaped = critic_escape(text)
    assert critic_unescape(escaped) == text, text
    assert cm.critic_unescape(escaped) == text, text
    for match in CRITIC_SITE.finditer(escaped):
        run = next(group for group in match.groups() if group is not None)
        assert len(run) % 2 == 1, f"a live site is left in {escaped!r}"


def _e1(exhaustive_length: int, random_count: int) -> int:
    count = 0
    for length in range(exhaustive_length + 1):
        for letters in itertools.product(SYMBOLS, repeat=length):
            _assert_e1("".join(letters))
            count += 1
    rng = random.Random(20261019)
    for _ in range(random_count):
        _assert_e1(
            "".join(rng.choice(RANDOM_ALPHABET) for _ in range(rng.randint(0, 14)))
        )
        count += 1
    return count


def test_e1_escape_round_trips_and_leaves_no_live_site() -> None:
    assert _e1(exhaustive_length=5, random_count=20_000) == 131_111


@pytest.mark.slow
def test_e1_at_the_design_counts() -> None:
    assert _e1(exhaustive_length=6, random_count=200_000) == 1_311_111


# --- E2 -----------------------------------------------------------------------

HEADS = ["", "## ", "- ", "1. ", "    - ", "> ", "> - "]
ROLE_POOL: list[str | None] = [None, *HOSTILE_ROLES[:10]]
ROLE_SHAPED_STARTS = [
    "[x] ",
    "\\[x] ",
    "\\\\[x] ",
    "[Party A] ",
    "[a.b-c_%] ",
    "[link](u) ",
]


def _line(head: str, role: str | None, roles: bool, pieces: list[Piece]) -> str:
    """Spell one line the way the layout builds it: head, role, then content."""
    quoted = head.startswith("> ")
    syntax = head[2:] if quoted else head
    line: list[Piece] = [Piece("syntax", syntax)] if syntax else []
    if roles and role is not None:
        line.append(Piece("role", "[" + encode_role(role) + "] "))
    return serialize([Chunk((*line, *pieces), quote=quoted)], CRITIC, roles=roles)


def _e2(count: int, seed: int) -> int:
    rng = random.Random(seed)
    alphabet = RANDOM_ALPHABET + list("ab0.%-_")
    for _ in range(count):
        head = rng.choice(HEADS)
        role = rng.choice(ROLE_POOL)
        roles = rng.random() < 0.8
        content = "".join(rng.choice(alphabet) for _ in range(rng.randint(0, 12)))
        if rng.random() < 0.3:
            content = rng.choice(ROLE_SHAPED_STARTS) + content
        pieces = [Piece("text", content)] if content else []
        expected = content
        if rng.random() < 0.5:
            inserted = "".join(
                rng.choice(RANDOM_ALPHABET) for _ in range(rng.randint(1, 6))
            )
            tail = "".join(
                rng.choice(RANDOM_ALPHABET) for _ in range(rng.randint(0, 4))
            )
            pieces.append(Piece("insert", inserted))
            if tail:
                pieces.append(Piece("text", tail))
            expected += inserted + tail
        line = _line(head, role, roles, pieces)
        read = cm.lines(line, "accept", roles=roles)
        assert read == [head + expected], (head, role, roles, pieces, line, read)
    return count


def test_e2_a_whole_line_survives_the_reader() -> None:
    assert _e2(6_000, seed=5) == 6_000


@pytest.mark.slow
def test_e2_at_the_design_count() -> None:
    assert _e2(60_000, seed=20261019) == 60_000


@pytest.mark.parametrize("head", HEADS)
@pytest.mark.parametrize("start", ROLE_SHAPED_STARTS)
@pytest.mark.parametrize("role", [None, "schedule", "a]b"])
def test_e2_role_shaped_starts_read_back_exactly(
    head: str, start: str, role: str | None
) -> None:
    content = start + "the rest"
    line = _line(head, role, True, [Piece("text", content)])
    assert cm.lines(line, "accept") == [head + content]
    _, decoded, _ = cm.split_role(cm.resolve(cm.parse(line), "accept"))
    assert decoded == role


def test_e2_a_mark_at_the_content_start_keeps_the_accept_side_exact() -> None:
    """A role-shaped insertion or new label at the very start is escaped inside its mark."""
    for pieces, accepted, rejected in (
        ([Piece("insert", "[x]"), Piece("text", " task")], "[x] task", " task"),
        (
            [Piece("substitution", "[ ]", "[x]"), Piece("text", " task")],
            "[x] task",
            "[ ] task",
        ),
        ([Piece("delete", "[y] "), Piece("text", "task")], "task", "[y] task"),
    ):
        line = serialize([Chunk(tuple(pieces))], CRITIC, roles=True)
        assert cm.lines(line, "accept") == [accepted], line
        assert cm.lines(line, "reject") == [rejected], line


# --- E3 -----------------------------------------------------------------------

COMPOSITES = [
    [Piece("text", "a\\"), Piece("insert", "x"), Piece("text", " b")],
    [Piece("text", "path C:\\dir\\"), Piece("delete", "old\\")],
    [
        Piece("text", "use {++ literally "),
        Piece("insert", "and ++} too"),
        Piece("text", " end"),
    ],
    [
        Piece("text", "x"),
        Piece("note", "moved from 7.5 /section[1]/section[7]/list_item[5]"),
    ],
    [Piece("text", "a~"), Piece("substitution", "b~", "c\\"), Piece("text", "~>d")],
]


def _token(piece: Piece) -> cm.Token:
    if piece.kind == "substitution":
        return cm.Token("substitution", piece.text, piece.new)
    assert piece.kind in ("text", "insert", "delete", "note")
    return cm.Token(piece.kind, piece.text)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "pieces", COMPOSITES, ids=[str(i) for i in range(len(COMPOSITES))]
)
def test_e3_backslash_runs_before_emitted_delimiters_parse_back_exactly(
    pieces: list[Piece],
) -> None:
    line = serialize([Chunk(tuple(pieces))], CRITIC, roles=False)
    assert cm.parse(line) == tuple(_token(piece) for piece in pieces)


# --- E4 -----------------------------------------------------------------------


def _e4(length: int) -> int:
    seen: dict[tuple[bool, str], str] = {}
    for size in range(length + 1):
        for letters in itertools.product("[]\\x ", repeat=size):
            content = "".join(letters)
            for roles in (True, False):
                line = serialize(
                    [Chunk((Piece("text", content),))], CRITIC, roles=roles
                )
                key = (roles, line)
                assert seen.setdefault(key, content) == content, (key, content)
    return len(seen)


def test_e4_the_line_start_site_is_injective() -> None:
    assert _e4(length=6) == 39_062


# --- the real traversal ---------------------------------------------------------


def _tree(*blocks: Block) -> BlockTree:
    return BlockTree.build(Block(kind=BlockKind.DOCUMENT, children=blocks))


@pytest.mark.parametrize("roles", [True, False])
def test_hostile_text_through_the_real_traversal_reads_back(roles: bool) -> None:
    """Random hostile paragraphs and list items, compared and rendered for real."""
    rng = random.Random(178)
    alphabet = RANDOM_ALPHABET + list("ab0.%-_")
    for _ in range(150):
        start = rng.choice(["", *ROLE_SHAPED_STARTS])
        texts = [
            start + "".join(rng.choice(alphabet) for _ in range(rng.randint(1, 10)))
            for _ in range(3)
        ]
        role = rng.choice(ROLE_POOL)
        source = _tree(
            *(Block(kind=BlockKind.PARAGRAPH, text=t, role=role) for t in texts)
        )
        edited = list(texts)
        edited[1] = edited[1] + " " + "".join(rng.choice(alphabet) for _ in range(4))
        test = _tree(
            *(Block(kind=BlockKind.PARAGRAPH, text=t, role=role) for t in edited)
        )
        comparison = compare(source, test)
        annotated = render_inplace(comparison, CRITIC, syntax="text", roles=roles)
        canonical = render_inplace(
            compare(test, test), CRITIC, syntax="text", roles=roles
        )
        assert cm.accept_all(annotated, roles=roles) == cm.accept_all(
            canonical, roles=roles
        )
        assert cm.accept_all(canonical, roles=roles) == [
            t.strip() for t in edited if t.strip()
        ]
