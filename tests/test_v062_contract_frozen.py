"""The 0.6.2 compatibility contract, pinned byte for byte.

ADR-0003 makes the 0.6 test suite the compatibility contract for 1.0: it has to
pass *unmodified*. This module is what "unmodified" means to a machine. It pins,
by SHA-256, every file that v0.6.2 shipped under ``tests/``:

- the 12 test modules;
- ``tests/corpus/regenerate_goldens.py``;
- the ``source.txt``, ``test.txt`` and ``processor.txt`` of the 7 golden cases
  (15 files);
- the 42 golden files, 6 markdown styles for each of the 7 cases, which are the
  M0 oracle the ``Redlines`` facade has to reproduce byte for byte;
- the 4 fixtures under ``tests/documents/``.

The digests are written out below, so the check needs neither git nor the
network, and a file cannot be edited and take its own pin along unnoticed: the
change shows in this file's diff. Each line of a table is ``shasum -a 256``
output for a repository-relative path.

Which bytes. For every file except eight of the modules, the pin is the v0.6.2
tag: ``git show v0.6.2:<path> | shasum -a 256`` prints the same digest. Eight of
the twelve modules were edited after the tag, and their pins are the bytes at
the M3 base (``e3b8e01``). No assertion in any of them was weakened or removed:

- ``black`` formatting only (``0e6ba7d``, the ASTs are identical):
  ``test_autojunk.py``, ``test_cleanup.py``, ``test_cli.py``,
  ``test_error_messages.py``, ``test_nupunkt_processor.py`` and
  ``test_redline.py``;
- additive edits: ``test_corpus.py`` (``NOT_GOLDEN_CASES``, so the fixture
  directories that M1 and M2 added under ``tests/corpus/`` are not mistaken for
  golden cases) and ``test_examples.py`` (``TestCustomReader``, and
  ``custom_reader.py`` in the set of exercised examples).

The other direction, the pristine v0.6.2 tests run against the current code, is
the ``compat-v062`` job in ``.github/workflows/python-package.yml``.

Line endings. The pins assume LF. ``tests/corpus/**`` is ``-text`` in
``.gitattributes``, so git never translates it; the modules and
``tests/documents/`` are not, so a checkout with ``core.autocrlf=true`` changes
their bytes and fails here. CI runs on Linux.

If a test here fails, revert the edit. Sentences in the pinned files that look
stale ("regenerate the goldens with ...", "reused by M4") stay stale on purpose:
following that advice would rewrite the oracle from the code it is meant to
check, and the failure here is what stops it. A formatter run over ``tests/`` trips
these tests too (six of the modules differ from the tag only because black was
run once, and a new black release could do it again): do not commit its changes to
the pinned files.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent

# The 12 test modules, as they stand at the M3 base (e3b8e01). Eight of them
# differ from the v0.6.2 tag; see the module docstring.
_MODULES = """
2ff1a9db9149eea1f5b8d9b5349ccab8308b210265dd8456ec9eff634c01f34b  tests/test_autojunk.py
0ff2abacd05061ff124b468b1832b75577d52f21922b4d6f54a2b97b5f34b27b  tests/test_changes_api.py
594f6868daa52ad70d94cb98ec11cc34a4496a1e56237b37c67fa1631c76534e  tests/test_cleanup.py
81a3b478daad5701db3a7cf1efc002397d75620b2aa5189d647ac5d95f77a942  tests/test_cli.py
fe91bfda9187e8171fde9bb3207cf61e6e278d050ce731adb992098293124551  tests/test_corpus.py
0f154aed20f1261139479503ff57f7f29975f0a81efe21f5c2dc9532e9900bdb  tests/test_document.py
7e3f7ae6dc4ed91437d806b470d1262ef3e864b7f0e9b9c476e4598d3f100b5a  tests/test_error_messages.py
2ec6d7180d19257e0f4bc8d2a0aafc39c8fc44dddacbee6cad41a9933ad0347a  tests/test_examples.py
8bcbc76bcbc5448975e498e2df378e94de72081b3fa4d938e40638016bdc73ba  tests/test_json_output.py
3e17b7b0f87fbe465bae49e7c26789dd0314f0f7384d6e27025523f8c1c7d93d  tests/test_nupunkt_processor.py
ad7712d4a69082e5dc33d450e34e35dde56d54b87d2c9c16fc63ef32af1b4219  tests/test_pdf.py
d823c61efa79062d93d40d5020e13e4cb3031029394275093c78815129be9558  tests/test_redline.py
"""

# source.txt and test.txt of each of the 7 golden cases, and the one
# processor.txt (sentence_paragraphs: "nupunkt"). Equal to the v0.6.2 tag.
_CASE_INPUTS = """
797b1115d9abb4c621fd7bb7254c5dcf47d8beaef78b6e92a2b0e53fd32a93d1  tests/corpus/course_lesson6/source.txt
55b2819cf65ab534cf8703dd85df3c1417f84af95967a90206d9eb7a8bda60ea  tests/corpus/course_lesson6/test.txt
2c330e4a205e28a79419db382d2c18784bf4af43a1e472629f45c40d46dede31  tests/corpus/multi_paragraph/source.txt
383d0ed5010d8e3c2f9028785f83082801f385d2e1da43e906f7836da4a0676d  tests/corpus/multi_paragraph/test.txt
81e816c6af9c960a47d9c7b58848c398b0c9f28450550c37f19413bdb6b6002b  tests/corpus/punctuation_merge/source.txt
c09bc54c6fce497cfbce3c5c135400039e161349f3a950e661732b97c7cf0a67  tests/corpus/punctuation_merge/test.txt
ef537f25c895bfa782526529a9b63d97aa631564d5d789c2b765448c8635fb6c  tests/corpus/readme_quickstart/source.txt
7a1e07d5d92a92af251750218814ec03b72ef2f6941e0cc7bb27b181c37c4e3c  tests/corpus/readme_quickstart/test.txt
e6142c609eb5a778e3b9d7f7f848aa6d37a03814a9a8d38dc4e9170254c17922  tests/corpus/repetitive_schedule/source.txt
9f8c3879d4bededddc20f0910a29fe7d7d75ba2d003bdd13be61185e7b98dbbe  tests/corpus/repetitive_schedule/test.txt
58b339a18ade3c95309ec045350ef914ea2b7e680215faa4a6a4559c4ca270d9  tests/corpus/sentence_paragraphs/processor.txt
39415f70f5729298f03aa3a4500f5dfc1d709846076a336bc0436857123a135c  tests/corpus/sentence_paragraphs/source.txt
77512c0c1224b03f349e54862d7c10e2e4d0ec49d04fa0c41c781b4dadcc80dc  tests/corpus/sentence_paragraphs/test.txt
3a448835449030d2fdc65f44f50cbb340c7b9d5ee1d8232b269e46ebce327941  tests/corpus/whitespace_after_equal/source.txt
8b772e71d6b3dd9c4cc1ffd400c4d84cf0c1129532d878631c30041c9e5a4f81  tests/corpus/whitespace_after_equal/test.txt
"""

# The 42 goldens: 7 cases x 6 markdown styles. Equal to the v0.6.2 tag.
_GOLDENS = """
dd050d859084d7942a89df08d249c2c8ecca8d2371f1d5832c69bdb842eed25f  tests/corpus/course_lesson6/golden/bbcode.md
cb97083c546cd1dc33718ff4a14369d34d4fa07100edb146cc3d2dc504f65b01  tests/corpus/course_lesson6/golden/ghfm.md
dfe171be5b315388aa8b620ecc153ca691bcb805cece29a5360209b6ee0f5f19  tests/corpus/course_lesson6/golden/none.md
3b21a482b695bc1fe1c39b718eaefa550b8f1c1c0b8ee52ba5475fe7f8a9b8dd  tests/corpus/course_lesson6/golden/red.md
c63b7a45d6de1c8b6301be4872fcb5bf4e71c8c935191225cc2f9dc7fdbc2278  tests/corpus/course_lesson6/golden/red_green.md
0a0b0b1b133ab04dd4d962b3697134e970960b5ae65d630e5f35e4d55043a390  tests/corpus/course_lesson6/golden/streamlit.md
28f14e024c4f218b9330c7a500f8476bfd34e0518e2eb4e410306668e7ddac56  tests/corpus/multi_paragraph/golden/bbcode.md
87c83bc3c9fbbafd967c4dab444f39bb7212222af6d7b563da90bce400388b90  tests/corpus/multi_paragraph/golden/ghfm.md
b42e5fc410f68f4835cce61e951f8d69d069fd382c70b44549fb6aaabce0099e  tests/corpus/multi_paragraph/golden/none.md
a89e366a051f5327a36435f0725423bfbadd8c6a26f136231da744e641154801  tests/corpus/multi_paragraph/golden/red.md
80bb66acc6c3f3e83b08908314e7cb12aefec70079ea0cfceb58ee86365ed739  tests/corpus/multi_paragraph/golden/red_green.md
1a6fe351e3ce83e44325751566d409bc093dd3ae51571f86352c810b97c0d98d  tests/corpus/multi_paragraph/golden/streamlit.md
d8162cfff63ab23be5da163e16e61138d5dc416c342f5d9e35f0df1bc23f8bfe  tests/corpus/punctuation_merge/golden/bbcode.md
e95f2ec5175c06f0e266a106aa3f1980045ae95581e9d266a375bd021fcf477b  tests/corpus/punctuation_merge/golden/ghfm.md
be11437a207a6c01d965c6bf2c7a51e5dfb54682a3208cf440dbdf17b01238c5  tests/corpus/punctuation_merge/golden/none.md
ce2d78a7ce3ea65cefbac0a31d1879006cd530061835957f4a54ed59414e9c8b  tests/corpus/punctuation_merge/golden/red.md
23b52ae5b496bf9d040b4283ecdc4e56417c18b0d0b5bd32f9863385f89813b2  tests/corpus/punctuation_merge/golden/red_green.md
a60ed848c25e6570fdc823cacdf06bfd3c530584271f2cebf7d32403af5217e7  tests/corpus/punctuation_merge/golden/streamlit.md
528de2da05ce44a270f8cc2566cb24af212ee3f7de79b274bd2bce8cfbe1482c  tests/corpus/readme_quickstart/golden/bbcode.md
90241ac9376695cb6bf7fde4220f1e3c91c3454865f7526c83dd7f430a4bdfe4  tests/corpus/readme_quickstart/golden/ghfm.md
f9fe6fdfa7cc9a7b134beed8ca30c3c9ea6b66f42f22e83a647ce9f8129810fe  tests/corpus/readme_quickstart/golden/none.md
5c11092492bfd28f795d16f791d301ece4fc8e699a164b886ea223840093b0b3  tests/corpus/readme_quickstart/golden/red.md
4d4da5c1be61be81c2ff8e0b70f3a1b87f8023bf9b13a673b383476239894644  tests/corpus/readme_quickstart/golden/red_green.md
ef1e73304ca7985d89acccd9fdb5db685d1ed0a79e7a58c100ef557d76359135  tests/corpus/readme_quickstart/golden/streamlit.md
e76f507e2bd19ceb53a3722c120721a04243d7cb02ea453f93d6b2df769a3392  tests/corpus/repetitive_schedule/golden/bbcode.md
0ff05f623cc672294b75ae6f808add1254d604b6beb7734a3f124a2f4e6f7c19  tests/corpus/repetitive_schedule/golden/ghfm.md
feb1f42530f1221391fe8b79a013a83669b2673d89b9d01b25d101ef5f3d5546  tests/corpus/repetitive_schedule/golden/none.md
96c8166379348d4798acfa1301505c6863d78d0f994d2787a4862596547d0af0  tests/corpus/repetitive_schedule/golden/red.md
4afdc00c7d1a4520d27bc4ee61470c4950c279ffcbf8159bb8a007fddf7cc5f3  tests/corpus/repetitive_schedule/golden/red_green.md
9a5387ffe9618ca1c1c8b13a94c8620eec8286d494078a12ccd5419d28d16fab  tests/corpus/repetitive_schedule/golden/streamlit.md
81de58124338a3f823a2daacd219e7549d0250bb79ae594c988d672f05536786  tests/corpus/sentence_paragraphs/golden/bbcode.md
01a9df7f95dcacf198b94d4afebc8363bafb4f757f004abf223287131d710739  tests/corpus/sentence_paragraphs/golden/ghfm.md
6fe0c4554f04788173be3d3f9a935c9498c2191a971065c843a6a0c1857dbeec  tests/corpus/sentence_paragraphs/golden/none.md
4ffc186085eeba077148ed685b9fc9524e8779199f69fddbd843ad5a8c37016d  tests/corpus/sentence_paragraphs/golden/red.md
736c0e5684ee0b900460e2ab1b8cb8e60abe2ea6cb60fc7b7aad3a1f62609aaa  tests/corpus/sentence_paragraphs/golden/red_green.md
63eea89c1c53c645428e8872c18aed73e32b7c0454f8a217e86e41cbc2047b75  tests/corpus/sentence_paragraphs/golden/streamlit.md
882c7fe1caf982ed7e974f8f4261111c50e6694c16fdfeaf7b906739ba1d7f7b  tests/corpus/whitespace_after_equal/golden/bbcode.md
ac0ee6fe4598063e576f6f050663142b68b8eb9b0ae6f4b13c028a6ce3dd5ad0  tests/corpus/whitespace_after_equal/golden/ghfm.md
fee9b2a92e498ff1f385a3c7ad4993484720a99a47722e0b6ed6cdb0791d6c71  tests/corpus/whitespace_after_equal/golden/none.md
cc35937fc97a7089e6ca5e47f9a5908451ca3993cf321e84733531c260bdc762  tests/corpus/whitespace_after_equal/golden/red.md
273f785421b47f45e233aadf1a62c2c317e0272edc96f6bca3eaf1465ce2834b  tests/corpus/whitespace_after_equal/golden/red_green.md
6515f59fe3b201b09144e645b75780055c57bce5bfaa3c198ffb30f55b2333fa  tests/corpus/whitespace_after_equal/golden/streamlit.md
"""

# The fixtures of tests/test_document.py and tests/test_pdf.py. Equal to the
# v0.6.2 tag.
_DOCUMENTS = """
891827f49bfc9c32262b4ed4b43fdeff4fe6c17a0e9b5cbf6c1dd0ac756083aa  tests/documents/PDFFile/source.pdf
6731fcdd2c24c5ba29686ec163b707b347e72520591d85ce29934c870dd33a6f  tests/documents/PDFFile/test.pdf
ef537f25c895bfa782526529a9b63d97aa631564d5d789c2b765448c8635fb6c  tests/documents/PlainTextFile/source.txt
7a1e07d5d92a92af251750218814ec03b72ef2f6941e0cc7bb27b181c37c4e3c  tests/documents/PlainTextFile/test.txt
"""

# The script that wrote the goldens. It is never run again: it would rewrite
# the oracle from the code under test. Equal to the v0.6.2 tag.
_REGENERATE = """
923b3c6aa6f46e95f57193b0642850d9de87aa778325418e917a575888e1c533  tests/corpus/regenerate_goldens.py
"""


def _parse(table: str) -> dict[str, str]:
    """Read ``<sha256 hex digest>  <repository-relative path>`` lines."""
    pins: dict[str, str] = {}
    for line in table.strip().splitlines():
        digest, path = line.split("  ", 1)
        assert path not in pins, f"{path} is pinned twice"
        pins[path] = digest
    return pins


MODULES = _parse(_MODULES)
CASE_INPUTS = _parse(_CASE_INPUTS)
GOLDENS = _parse(_GOLDENS)
DOCUMENTS = _parse(_DOCUMENTS)
REGENERATE = _parse(_REGENERATE)

PINNED = {**MODULES, **CASE_INPUTS, **GOLDENS, **DOCUMENTS, **REGENERATE}

GOLDEN_CASES = (
    "course_lesson6",
    "multi_paragraph",
    "punctuation_merge",
    "readme_quickstart",
    "repetitive_schedule",
    "sentence_paragraphs",
    "whitespace_after_equal",
)
STYLES = ("red_green", "none", "red", "ghfm", "bbcode", "streamlit")

# `git ls-tree -r v0.6.2 --name-only tests/ | grep 'tests/test_.*\.py$'`
MODULE_PATHS = {
    "tests/test_autojunk.py",
    "tests/test_changes_api.py",
    "tests/test_cleanup.py",
    "tests/test_cli.py",
    "tests/test_corpus.py",
    "tests/test_document.py",
    "tests/test_error_messages.py",
    "tests/test_examples.py",
    "tests/test_json_output.py",
    "tests/test_nupunkt_processor.py",
    "tests/test_pdf.py",
    "tests/test_redline.py",
}
# `git ls-tree -r v0.6.2 --name-only tests/documents/`
DOCUMENT_PATHS = {
    "tests/documents/PDFFile/source.pdf",
    "tests/documents/PDFFile/test.pdf",
    "tests/documents/PlainTextFile/source.txt",
    "tests/documents/PlainTextFile/test.txt",
}


@pytest.mark.parametrize("path", sorted(PINNED))
def test_pinned_file_is_unchanged(path: str) -> None:
    contract = (
        f"{path} is part of the 0.6.2 compatibility contract (ADR-0003) and "
        f"must not be edited in M3."
    )
    file = REPO_ROOT / path
    assert file.is_file(), f"{contract} It is missing."

    actual = hashlib.sha256(file.read_bytes()).hexdigest()
    origin = "the M3 base (e3b8e01)" if path in MODULES else "the v0.6.2 tag"

    assert actual == PINNED[path], (
        f"{contract}\n"
        f"  pinned (from {origin}): {PINNED[path]}\n"
        f"  found:                  {actual}\n"
        f"Revert the edit; do not update the pin."
    )


def test_the_tables_cover_the_whole_0_6_2_tree() -> None:
    """A pin removed to make a failure go away would be a silent way out of the
    contract, so the shape of the tables is itself pinned."""
    assert set(GOLDENS) == {
        f"tests/corpus/{case}/golden/{style}.md"
        for case in GOLDEN_CASES
        for style in STYLES
    }
    assert set(CASE_INPUTS) == {
        f"tests/corpus/{case}/{name}.txt"
        for case in GOLDEN_CASES
        for name in ("source", "test")
    } | {"tests/corpus/sentence_paragraphs/processor.txt"}
    # Exact sets, not counts: replacing one pin with another file's would keep
    # the count and drop a module out of the contract.
    assert set(MODULES) == MODULE_PATHS
    assert set(DOCUMENTS) == DOCUMENT_PATHS
    assert set(REGENERATE) == {"tests/corpus/regenerate_goldens.py"}
    # 12 modules + 15 case inputs + 42 goldens + 4 documents + 1 script: every
    # file `git ls-tree -r v0.6.2 --name-only tests/` lists.
    assert len(PINNED) == 74
