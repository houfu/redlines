# NOTICE

This directory carries a prepared excerpt of Common Paper's **Cloud Service Agreement** standard
agreement, licensed under the Creative Commons Attribution 4.0 International licence.

- Upstream repository: https://github.com/CommonPaper/CSA
- File: `CSA.md`
- Tags compared: `1.0` (source) to `1.1` (test)
- Licence: CC BY 4.0 -- https://creativecommons.org/licenses/by/4.0/

**Attribution.** Common Paper Cloud Service Agreement, copyright Common Paper, Inc., licensed under
CC BY 4.0 (https://creativecommons.org/licenses/by/4.0/).

**What was changed from the upstream text.** `benchmark/prepare.py` applied the following,
deterministic normalisations to both `source.md` and `test.md`, and nothing else -- no clause
was reworded and no content was added or removed: `strip_inline_html`. See
`prepare_manifest.json` in this directory for the exact record, and
`benchmark/prepare.py`'s module docstring for why each one is needed. The prepared text, not
the upstream file, is what is committed and what `labels.yaml`'s digests anchor to.

This NOTICE, and the CC BY 4.0 licence terms it names, travel with `source.md` and `test.md`
wherever this directory is redistributed. `redlines` itself remains MIT-licensed; committing
these two files does not change that.
