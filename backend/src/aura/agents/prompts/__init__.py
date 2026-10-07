"""Versioned prompt templates (harness categories 2 and 9).

Each role's prompt lives in a file `<template_id>@v<N>.md` in this directory: a front matter
block (id, version, role) and sections `## goal`, `## backstory`, `## task`,
`## expected_output`. A template is immutable once released: changing what a model is told
means adding the next version and pointing ACTIVE at it. manifest.json pins every released
file's sha256 (over its text with LF line endings), and a test fails when a file's content no
longer matches its pin, so an edit without a version bump cannot slip through.

agent_run.prompt_template_id records "<id>@v<N>"; GET /api/prompts lists the registry.
"""
import hashlib
import json
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

PROMPTS_DIR = Path(__file__).resolve().parent
MANIFEST = PROMPTS_DIR / "manifest.json"
_NAME = re.compile(r"^(?P<id>[a-z0-9_.]+)@v(?P<version>[0-9]+)\.md$")

# The version in use for each template id.
ACTIVE = {"crew.researcher": 1, "crew.drafter": 1, "crew.reviewer": 1,
          "classify_document": 2, "extract_financials": 1}


@dataclass(frozen=True)
class PromptTemplate:
    template_id: str
    version: int
    role: str
    goal: str
    backstory: str
    task: str
    expected_output: str
    sha256: str
    path: str

    @property
    def ref(self) -> str:
        return f"{self.template_id}@v{self.version}"


def normalised_text(path: Path) -> str:
    return path.read_text(encoding="utf-8").replace("\r\n", "\n")


def file_sha256(path: Path) -> str:
    return hashlib.sha256(normalised_text(path).encode("utf-8")).hexdigest()


def _parse(path: Path) -> PromptTemplate:
    text = normalised_text(path)
    m = re.match(r"^---\n(.*?)\n---\n(.*)$", text, re.S)
    if not m:
        raise ValueError(f"{path.name}: missing front matter")
    meta = dict(line.split(":", 1) for line in m.group(1).splitlines() if ":" in line)
    meta = {k.strip(): v.strip() for k, v in meta.items()}
    sections: dict[str, list[str]] = {}
    current = None
    for line in m.group(2).split("\n"):
        header = re.match(r"^## (\w+)\s*$", line)
        if header:
            current = header.group(1)
            sections[current] = []
        elif current is not None:
            sections[current].append(line)
    body = {k: "\n".join(v).strip("\n") for k, v in sections.items()}
    name = _NAME.match(path.name)
    if not name or name.group("id") != meta.get("id") \
            or name.group("version") != meta.get("version"):
        raise ValueError(f"{path.name}: file name and front matter disagree")
    return PromptTemplate(template_id=meta["id"], version=int(meta["version"]),
                          role=meta["role"], goal=body["goal"], backstory=body["backstory"],
                          task=body["task"], expected_output=body["expected_output"],
                          sha256=file_sha256(path), path=path.name)


@lru_cache
def all_templates() -> tuple[PromptTemplate, ...]:
    return tuple(sorted((_parse(p) for p in PROMPTS_DIR.glob("*@v*.md")),
                        key=lambda t: (t.template_id, t.version)))


def get(template_id: str, version: int | None = None) -> PromptTemplate:
    version = version if version is not None else ACTIVE[template_id]
    for t in all_templates():
        if t.template_id == template_id and t.version == version:
            return t
    raise KeyError(f"{template_id}@v{version}")


def manifest() -> dict[str, str]:
    return json.loads(MANIFEST.read_text(encoding="utf-8"))


def drift() -> list[str]:
    """Templates whose content differs from their pinned hash, or that are not pinned."""
    pinned = manifest()
    problems = []
    for t in all_templates():
        if t.ref not in pinned:
            problems.append(f"{t.ref} is not pinned in manifest.json")
        elif pinned[t.ref] != t.sha256:
            problems.append(f"{t.ref} changed without a version bump (sha256 {t.sha256} != "
                            f"pinned {pinned[t.ref]})")
    present = {t.ref for t in all_templates()}
    problems += [f"{ref} is pinned but its file is missing" for ref in pinned
                 if ref not in present]
    return problems
