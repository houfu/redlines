"""Fetch and prepare the ten hand-labelled pairs (#142, ADR-0034 §1.11.5).

This is the first of the two human-labelling steps Section 3.3 of the M2 research document
describes: "what the workflow can prepare, so the human only does judgement". It clones each
Common Paper agreement repository at two named tags, and downloads two short public-domain
U.S. bills at two published stages each, normalises the text deterministically, and commits
the *prepared* text -- never re-derived at score time -- to
``benchmark/corpus/hand/<pair>/{source,test}.<ext>`` alongside a ``NOTICE.md`` stating the
licence and a ``prepare_manifest.json`` recording exactly what this script did, for
:mod:`benchmark.label` to read when it drafts ``labels.yaml``.

**Why real, licensed documents, and why these two sources.** ADR-0021's anti-self-marking
mitigation needs the hand-labelled tier to be material nobody here wrote or edited --
"labelling one's own edits is the softest possible test". Common Paper's standard agreements
are real legal documents, git-tagged, explicitly CC BY 4.0; U.S. bill versions are public
domain (17 U.S.C. Sec 105) and exercise the plain-text ``contract`` profile's ``SEC.``
numbering rather than another SaaS contract. Both are checked, both are committed under
their own terms, and neither is a customer document or a repository-owned one (ADR-0034 D-9).

**The one hazard this script exists to fix.** Common Paper's older agreement tags carry
clause numbers as literal text ("1.1 <span class="header_3">Access and Use.</span>"); its
newer tags carry the same numbers only in an ``id`` attribute on the same span
("1. <span class="header_3" id="1.1">Access and Use.</span>"), because the *markdown* list
marker itself is stripped before label matching (``redlines/profiles/builtin/markdown.yaml``'s
own comment: "since markdown's own ordered lists renumber themselves"). Left alone, every
clause in a newer-tagged file would carry no label at all, and the label alignment pass would
have nothing to match newer-tagged clauses against. ``promote_span_ids_to_labels`` below fixes
this by turning the ``id`` back into the literal text a labelled clause needs, and a top-level
``header_2`` id becomes a nested ATX ``##`` heading instead, matching the shape the *older*
tags already use for their section headings. ``strip_inline_html`` then removes what is left
of every decorative span (``keyterms_link``, ``coverpage_link``, ``orderform_link``, ...) on
both sides of every pair, because Common Paper's markdown carries these in every tag, old and
new alike.

**Every normalisation actually applied is recorded**, never silently: each function below
returns whether it changed anything, and only the names that did anything to *this* pair's
text land in its ``prepare_manifest.json`` and, from there, in ``labels.yaml``'s
``provenance.normalisations`` (ADR-0034). A pair whose two tags already carry comparable
labels -- most of the Common Paper repos never adopted the ``id`` attribute at all -- records
only ``strip_inline_html``.

**Network access.** This script clones each Common Paper repository with the system ``git``
and fetches each bill version with the system ``curl`` rather than :mod:`urllib.request`:
several sandboxed Python installs on this project's contributors' machines carry no CA bundle
of their own (a known ``python.org`` installer gap), while the system ``curl`` already trusts
the OS keychain. Both are already assumed available -- ``git`` throughout this repository's own
tooling, ``curl`` alongside it -- so this adds no new dependency, only a second already-assumed
binary. Nothing here is stdlib-import-only, unlike the rest of :mod:`benchmark`, and that is
fine: this script is dev-only, run by hand, and never imported by a test or by CI (mirroring
``benchmark/fetch_neurotic.py``'s own rule) -- only its *output* is committed and checked.

**Run it**::

    uv run python -m benchmark.prepare                 # fetch and prepare every pair
    uv run python -m benchmark.prepare --pair csa-1.0-to-1.1   # just one, for a retry

Re-running is idempotent and deterministic: the same tag pair or bill versions always produce
byte-identical prepared text, so a re-run without upstream changes touches nothing.
"""

from __future__ import annotations

import argparse
import dataclasses
import hashlib
import html
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Final

HAND_CORPUS: Final[Path] = Path(__file__).parent / "corpus" / "hand"

CC_BY_4_0_URL: Final[str] = "https://creativecommons.org/licenses/by/4.0/"

# --------------------------------------------------------------------------
# Pair inventory
# --------------------------------------------------------------------------


@dataclasses.dataclass(frozen=True, slots=True)
class CommonPaperPair:
    """One before/after tag pair from a Common Paper standard-agreement repository."""

    pair_id: str
    repo: str  # e.g. "CSA" -- github.com/CommonPaper/<repo>
    path_in_repo: str  # the markdown file's path within the repo
    source_tag: str
    test_tag: str
    display_name: str  # e.g. "Cloud Service Agreement"


@dataclasses.dataclass(frozen=True, slots=True)
class GovInfoPair:
    """One before/after version pair of a U.S. bill, from govinfo.gov."""

    pair_id: str
    congress: int
    bill_type: str  # "hr"
    bill_number: int
    source_version: str  # govinfo's version code, e.g. "ih"
    source_version_name: str  # e.g. "Introduced in House"
    test_version: str
    test_version_name: str
    display_name: str


COMMON_PAPER_PAIRS: Final[tuple[CommonPaperPair, ...]] = (
    CommonPaperPair(
        pair_id="csa-1.0-to-1.1",
        repo="CSA",
        path_in_repo="CSA.md",
        source_tag="1.0",
        test_tag="1.1",
        display_name="Cloud Service Agreement",
    ),
    CommonPaperPair(
        pair_id="csa-1.1-to-2.0",
        repo="CSA",
        path_in_repo="CSA.md",
        source_tag="1.1",
        test_tag="2.0",
        display_name="Cloud Service Agreement",
    ),
    CommonPaperPair(
        pair_id="dpa-1.0-to-1.1",
        repo="DPA",
        path_in_repo="DPA.md",
        source_tag="1.0",
        test_tag="1.1",
        display_name="Data Processing Agreement",
    ),
    CommonPaperPair(
        pair_id="sla-1.0-to-2.0",
        repo="SLA",
        path_in_repo="sla.md",
        source_tag="1.0",
        test_tag="2.0",
        display_name="Service Level Agreement",
    ),
    CommonPaperPair(
        pair_id="design-partner-agreement-1.0-to-1.1",
        repo="Design-Partner-Agreement",
        path_in_repo="design-partner-agreement.md",
        source_tag="1.0",
        test_tag="1.1",
        display_name="Design Partner Agreement",
    ),
    CommonPaperPair(
        pair_id="psa-1.0-to-1.1",
        repo="PSA",
        path_in_repo="psa.md",
        source_tag="1.0",
        test_tag="1.1",
        display_name="Professional Services Agreement",
    ),
    CommonPaperPair(
        pair_id="partnership-agreement-1.0-to-1.1",
        repo="Partnership-Agreement",
        path_in_repo="Partnership-Agreement.md",
        source_tag="1.0",
        test_tag="1.1",
        display_name="Partnership Agreement",
    ),
    CommonPaperPair(
        pair_id="pilot-agreement-1.0-to-1.1",
        repo="Pilot-Agreement",
        path_in_repo="Pilot-Agreement.md",
        source_tag="1.0",
        test_tag="1.1",
        display_name="Pilot Agreement",
    ),
)

GOVINFO_PAIRS: Final[tuple[GovInfoPair, ...]] = (
    GovInfoPair(
        pair_id="govinfo-hr7385-ih-to-eh",
        congress=118,
        bill_type="hr",
        bill_number=7385,
        source_version="ih",
        source_version_name="Introduced in House",
        test_version="eh",
        test_version_name="Engrossed in House",
        display_name=(
            'H.R. 7385 (118th Congress) -- designating the "John Mercer Langston '
            'Post Office Building"'
        ),
    ),
    GovInfoPair(
        pair_id="govinfo-hr4668-ih-to-rh",
        congress=118,
        bill_type="hr",
        bill_number=4668,
        source_version="ih",
        source_version_name="Introduced in House",
        test_version="rh",
        test_version_name="Reported in House",
        display_name="H.R. 4668 (118th Congress) -- POST IT Act of 2023",
    ),
)

ALL_PAIR_IDS: Final[tuple[str, ...]] = tuple(
    [pair.pair_id for pair in COMMON_PAPER_PAIRS]
    + [pair.pair_id for pair in GOVINFO_PAIRS]
)

# --------------------------------------------------------------------------
# Normalisations -- each returns (new_text, changed); see the module docstring.
# --------------------------------------------------------------------------

# A ``header_N`` span, optionally carrying the ``id`` a newer Common Paper tag encodes its
# clause number in. Matches across the (rare) span whose inner text itself contains a
# newline, hence DOTALL; spans never nest in this corpus, so a non-greedy inner match is safe.
_HEADER_SPAN_RE = re.compile(
    r'<span\s+class="header_(?P<level>\d+)"(?:\s+id="(?P<id>[^"]+)")?\s*>'
    r"(?P<inner>.*?)</span>",
    re.DOTALL,
)

_ANY_SPAN_TAG_RE = re.compile(r"</?span\b[^>]*>")


def promote_span_ids_to_labels(text: str) -> tuple[str, bool]:
    """Turn a ``header_N`` span's ``id`` attribute into a literal label prefix.

    A top-level ``header_2`` id becomes a nested ATX ``## `` heading marker, matching the
    shape a Common Paper's own older tags already write their section headings in ("1. ##
    Service"). Any deeper ``header_N`` (``N >= 3``) becomes ``"{id}. "`` prepended to the
    span's own text, matching the literal decimal clauses an older tag writes directly
    ("1.1 Access and Use."). A ``header_N`` span with no ``id`` is left completely untouched
    -- there is nothing to promote, and `strip_inline_html` removes its tags next.

    :param text: the document text to scan.
    :return: the transformed text, and whether anything was actually promoted.
    """
    changed = False

    def replace(match: re.Match[str]) -> str:
        nonlocal changed
        id_value = match.group("id")
        if id_value is None:
            return match.group(0)
        changed = True
        inner = match.group("inner")
        level = int(match.group("level"))
        if level == 2:
            return f"## {inner}"
        return f"{id_value}. {inner}"

    new_text = _HEADER_SPAN_RE.sub(replace, text)
    return new_text, changed


def strip_inline_html(text: str) -> tuple[str, bool]:
    """Remove every ``<span ...>``/``</span>`` tag, keeping the text between them.

    Common Paper's markdown wraps defined terms and cross-references in decorative spans
    (``keyterms_link``, ``coverpage_link``, ``orderform_link``, ``sample_link``, ...) in
    every tag, old and new alike; none of it is meaningful to a document reader, and left in
    place it would show up as literal text inside every block. Runs after
    `promote_span_ids_to_labels`, so a labelled span's promoted prefix survives and only its
    tags are removed here along with everything else.

    :param text: the document text to scan.
    :return: the transformed text, and whether any tag was actually removed.
    """
    new_text = _ANY_SPAN_TAG_RE.sub("", text)
    return new_text, new_text != text


# Recorded in this fixed order in ``provenance.normalisations``, matching the order the
# research document's own example labels file uses -- cosmetic, but a stable order means two
# runs that applied the same normalisations produce byte-identical manifests.
_NORMALISATION_ORDER: Final[tuple[str, ...]] = (
    "extract_preformatted_text",
    "strip_inline_html",
    "promote_span_ids_to_labels",
)


def _order_normalisations(names: set[str]) -> list[str]:
    return [name for name in _NORMALISATION_ORDER if name in names]


def normalise_markdown(text: str) -> tuple[str, set[str]]:
    """Apply both Common Paper normalisations, in the order that makes them compose.

    :param text: one side's raw upstream markdown.
    :return: the prepared text, and the set of normalisation names that changed anything.
    """
    applied: set[str] = set()
    text, promoted = promote_span_ids_to_labels(text)
    if promoted:
        applied.add("promote_span_ids_to_labels")
    text, stripped = strip_inline_html(text)
    if stripped:
        applied.add("strip_inline_html")
    return text, applied


_PRE_BLOCK_RE = re.compile(r"<pre>(.*)</pre>", re.DOTALL)


def extract_preformatted_text(page_html: str) -> tuple[str, bool]:
    """Pull the plain-text bill out of govinfo's ``<html><body><pre>...</pre>`` wrapper.

    govinfo serves each bill version as pre-formatted plain text -- GPO's own fixed-width
    layout, ``SEC. 101.`` numbering included -- wrapped in a single ``<pre>`` element with
    HTML entities escaped. This unwraps it and unescapes the entities; there is no other
    markup inside a bill page to strip.

    :param page_html: the fetched page's raw HTML.
    :return: the plain bill text, and whether a ``<pre>`` block was actually found (``False``
        only if govinfo's page shape changed and this needs a look).
    """
    match = _PRE_BLOCK_RE.search(page_html)
    if match is None:
        return page_html, False
    return html.unescape(match.group(1)), True


# --------------------------------------------------------------------------
# Fetching
# --------------------------------------------------------------------------


class PrepareError(RuntimeError):
    """Fetching or preparing a pair failed; the message says which pair and why."""


def _run(command: list[str]) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(command, capture_output=True, text=True)
    if result.returncode != 0:
        raise PrepareError(
            f"command failed ({result.returncode}): {' '.join(command)}\n{result.stderr}"
        )
    return result


def _clone_common_paper_repo(repo: str, workdir: Path) -> Path:
    """Clone ``CommonPaper/<repo>`` (full history, so every tag resolves) into ``workdir``."""
    dest = workdir / repo
    if dest.exists():
        return dest
    _run(["git", "clone", "--quiet", f"https://github.com/CommonPaper/{repo}.git", str(dest)])
    return dest


def _show_at_tag(clone_dir: Path, tag: str, path_in_repo: str) -> str:
    result = _run(["git", "-C", str(clone_dir), "show", f"{tag}:{path_in_repo}"])
    return result.stdout


def fetch_common_paper_side(pair: CommonPaperPair, tag: str, clones_dir: Path) -> str:
    """Return the raw upstream markdown for `pair`'s repository at `tag`."""
    clone_dir = _clone_common_paper_repo(pair.repo, clones_dir)
    return _show_at_tag(clone_dir, tag, pair.path_in_repo)


def govinfo_url(pair: GovInfoPair, version: str) -> str:
    """The govinfo.gov URL for one version of one bill."""
    package = f"BILLS-{pair.congress}{pair.bill_type}{pair.bill_number}{version}"
    return f"https://www.govinfo.gov/content/pkg/{package}/html/{package}.htm"


def fetch_govinfo_page(url: str) -> str:
    """Fetch one govinfo.gov page with the system ``curl`` (see the module docstring)."""
    result = _run(["curl", "-fsSL", url])
    return result.stdout


# --------------------------------------------------------------------------
# Preparing one pair
# --------------------------------------------------------------------------


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _write_manifest(
    pair_dir: Path,
    *,
    pair_id: str,
    kind: str,
    origin: str,
    licence: str,
    attribution: str,
    normalisations: list[str],
    source_file: str,
    test_file: str,
    format_: str,
    profile: str,
) -> None:
    manifest = {
        "pair": pair_id,
        "kind": kind,
        "origin": origin,
        "licence": licence,
        "attribution": attribution,
        "prepared_by": "benchmark/prepare.py",
        "normalisations": normalisations,
        "source_file": source_file,
        "test_file": test_file,
        "format": format_,
        "profile": profile,
    }
    (pair_dir / "prepare_manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


_COMMON_PAPER_NOTICE = """\
# NOTICE

This directory carries a prepared excerpt of Common Paper's **{display_name}** standard
agreement, licensed under the Creative Commons Attribution 4.0 International licence.

- Upstream repository: https://github.com/CommonPaper/{repo}
- File: `{path_in_repo}`
- Tags compared: `{source_tag}` (source) to `{test_tag}` (test)
- Licence: CC BY 4.0 -- {licence_url}

**Attribution.** Common Paper {display_name}, copyright Common Paper, Inc., licensed under
CC BY 4.0 ({licence_url}).

**What was changed from the upstream text.** `benchmark/prepare.py` applied the following,
deterministic normalisations to both `source.md` and `test.md`, and nothing else -- no clause
was reworded and no content was added or removed: {normalisations_prose}. See
`prepare_manifest.json` in this directory for the exact record, and
`benchmark/prepare.py`'s module docstring for why each one is needed. The prepared text, not
the upstream file, is what is committed and what `labels.yaml`'s digests anchor to.

This NOTICE, and the CC BY 4.0 licence terms it names, travel with `source.md` and `test.md`
wherever this directory is redistributed. `redlines` itself remains MIT-licensed; committing
these two files does not change that.
"""

_GOVINFO_NOTICE = """\
# NOTICE

This directory carries U.S. federal legislative bill text retrieved from
[govinfo.gov](https://www.govinfo.gov/), published by the U.S. Government Publishing Office.

- Bill: {display_name}
- Versions compared: {source_version_name} (`{source_version}`, source) to
  {test_version_name} (`{test_version}`, test)
- Source URLs:
  - {source_url}
  - {test_url}

**Public domain notice.** Works of the United States Government are not subject to copyright
protection in the United States (17 U.S.C. Sec 105). No licence is required to reproduce or
reuse this text, and none is asserted here.

**What was changed from the published text.** `benchmark/prepare.py` applied the following,
deterministic normalisations to both `source.txt` and `test.txt`, and nothing else: {normalisations_prose}.
See `prepare_manifest.json` in this directory for the exact record.
"""


def _normalisations_prose(names: list[str]) -> str:
    if not names:
        return "none -- the fetched text needed no changes"
    return ", ".join(f"`{name}`" for name in names)


def prepare_common_paper_pair(pair: CommonPaperPair, clones_dir: Path) -> Path:
    """Fetch, normalise and commit one Common Paper tag pair. Returns the pair's directory."""
    source_raw = fetch_common_paper_side(pair, pair.source_tag, clones_dir)
    test_raw = fetch_common_paper_side(pair, pair.test_tag, clones_dir)
    source_text, source_applied = normalise_markdown(source_raw)
    test_text, test_applied = normalise_markdown(test_raw)
    normalisations = _order_normalisations(source_applied | test_applied)

    pair_dir = HAND_CORPUS / pair.pair_id
    pair_dir.mkdir(parents=True, exist_ok=True)
    (pair_dir / "source.md").write_text(source_text, encoding="utf-8")
    (pair_dir / "test.md").write_text(test_text, encoding="utf-8")

    origin = f"CommonPaper/{pair.repo} tags {pair.source_tag} and {pair.test_tag}"
    attribution = (
        f"Common Paper {pair.display_name}, copyright Common Paper, Inc., CC BY 4.0"
    )
    notice = _COMMON_PAPER_NOTICE.format(
        display_name=pair.display_name,
        repo=pair.repo,
        path_in_repo=pair.path_in_repo,
        source_tag=pair.source_tag,
        test_tag=pair.test_tag,
        licence_url=CC_BY_4_0_URL,
        normalisations_prose=_normalisations_prose(normalisations),
    )
    (pair_dir / "NOTICE.md").write_text(notice, encoding="utf-8")

    _write_manifest(
        pair_dir,
        pair_id=pair.pair_id,
        kind="hand",
        origin=origin,
        licence="CC-BY-4.0",
        attribution=attribution,
        normalisations=normalisations,
        source_file="source.md",
        test_file="test.md",
        format_="markdown",
        profile="markdown",
    )
    return pair_dir


def prepare_govinfo_pair(pair: GovInfoPair) -> Path:
    """Fetch, normalise and commit one govinfo bill version pair. Returns the pair's directory."""
    source_url = govinfo_url(pair, pair.source_version)
    test_url = govinfo_url(pair, pair.test_version)
    source_page = fetch_govinfo_page(source_url)
    test_page = fetch_govinfo_page(test_url)

    source_text, source_found = extract_preformatted_text(source_page)
    test_text, test_found = extract_preformatted_text(test_page)
    if not (source_found and test_found):
        raise PrepareError(
            f"{pair.pair_id}: expected a <pre> block in the govinfo page; "
            "the page shape may have changed"
        )
    normalisations = _order_normalisations({"extract_preformatted_text"})

    pair_dir = HAND_CORPUS / pair.pair_id
    pair_dir.mkdir(parents=True, exist_ok=True)
    (pair_dir / "source.txt").write_text(source_text, encoding="utf-8")
    (pair_dir / "test.txt").write_text(test_text, encoding="utf-8")

    origin = (
        f"govinfo.gov {pair.congress}th Congress {pair.bill_type.upper()} "
        f"{pair.bill_number}, versions {pair.source_version} and {pair.test_version}"
    )
    notice = _GOVINFO_NOTICE.format(
        display_name=pair.display_name,
        source_version_name=pair.source_version_name,
        source_version=pair.source_version,
        test_version_name=pair.test_version_name,
        test_version=pair.test_version,
        source_url=source_url,
        test_url=test_url,
        normalisations_prose=_normalisations_prose(normalisations),
    )
    (pair_dir / "NOTICE.md").write_text(notice, encoding="utf-8")

    _write_manifest(
        pair_dir,
        pair_id=pair.pair_id,
        kind="hand",
        origin=origin,
        licence="public-domain-17-usc-105",
        attribution="",
        normalisations=normalisations,
        source_file="source.txt",
        test_file="test.txt",
        format_="text",
        profile="contract",
    )
    return pair_dir


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--pair",
        action="append",
        dest="pairs",
        choices=ALL_PAIR_IDS,
        help="prepare only this pair (repeatable); default is every pair",
    )
    args = parser.parse_args(argv)
    wanted = set(args.pairs) if args.pairs else set(ALL_PAIR_IDS)

    HAND_CORPUS.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="redlines-benchmark-prepare-") as tmp:
        clones_dir = Path(tmp)
        for cp_pair in COMMON_PAPER_PAIRS:
            if cp_pair.pair_id not in wanted:
                continue
            print(f"preparing {cp_pair.pair_id} ...", file=sys.stderr)
            prepare_common_paper_pair(cp_pair, clones_dir)
        for gi_pair in GOVINFO_PAIRS:
            if gi_pair.pair_id not in wanted:
                continue
            print(f"preparing {gi_pair.pair_id} ...", file=sys.stderr)
            prepare_govinfo_pair(gi_pair)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
