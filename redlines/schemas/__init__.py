"""Empty on purpose.

A real package (not a namespace package), so
``importlib.resources.files("redlines.schemas")`` resolves the same way under
every installer and under Pyodide, exactly as ``redlines.profiles`` does for
``schema.json`` (`redlines.profiles.profile_schema_text`).
"""

from __future__ import annotations
