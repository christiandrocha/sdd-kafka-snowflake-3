"""Minimal, dependency-free reader for the repo's own Terraform files.

Good enough for static guards on code we format ourselves (terraform fmt):
top-level ``resource`` / ``provider`` / ``variable`` blocks, brace-matched, with
``#`` comments stripped. Not a general HCL parser.
"""

from __future__ import annotations

import re
from pathlib import Path

_BLOCK_START = re.compile(r'^(resource|provider|variable)\s+"([^"]+)"(?:\s+"([^"]+)")?\s*\{', re.M)


def strip_comments(text: str) -> str:
    return re.sub(r"(?m)#.*$", "", text)


def blocks(root: Path, kind: str) -> dict[str, str]:
    """Return {"type.name": body} for resources, {alias: body} for providers, {name: body} else."""
    found: dict[str, str] = {}
    for path in sorted(root.glob("*.tf")):
        text = strip_comments(path.read_text())
        for match in _BLOCK_START.finditer(text):
            if match.group(1) != kind:
                continue
            depth, i = 0, match.end() - 1
            while True:
                ch = text[i]
                depth += ch == "{"
                depth -= ch == "}"
                i += 1
                if depth == 0:
                    break
            body = text[match.end() : i - 1]
            if kind == "resource":
                key = f"{match.group(2)}.{match.group(3)}"
            elif kind == "provider":
                alias = re.search(r'alias\s*=\s*"([^"]+)"', body)
                key = alias.group(1) if alias else "<default>"
            else:
                key = match.group(2)
            assert key not in found, f"duplicate {kind} {key} in {root}"
            found[key] = body
    return found


def provider_alias(body: str) -> str | None:
    match = re.search(r"^\s*provider\s*=\s*snowflake\.(\w+)", body, re.M)
    return match.group(1) if match else None
