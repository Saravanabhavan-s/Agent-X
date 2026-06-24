from __future__ import annotations

import re
from pathlib import Path

from agentx.intelligence.models import Import, Symbol

_SYMBOL_PATTERNS = [
    # def name / func name / function name / fn name
    re.compile(r"^\s*(?:export\s+)?(?:async\s+)?(?:def|func|function|fn)\s+([A-Za-z_]\w*)", re.MULTILINE),
    # class Name / struct Name / interface Name
    re.compile(r"^\s*(?:export\s+)?(?:pub\s+)?(?:class|struct|interface|trait|enum)\s+([A-Za-z_]\w*)", re.MULTILINE),
]

_EXPORT_PATTERN = re.compile(r"^\s*export\s+", re.MULTILINE)

_IMPORT_PATTERNS = [
    re.compile(r"^\s*import\s+['\"]?([^\s'\"]+)['\"]?", re.MULTILINE),
    # require with parens: require("mod")
    re.compile(r"^\s*require\s*\(\s*['\"]([^'\"]+)['\"]\s*\)", re.MULTILINE),
    # require without parens: require "mod" / require_relative "mod"
    re.compile(r"^\s*require(?:_relative)?\s+['\"]([^'\"]+)['\"]", re.MULTILINE),
    re.compile(r"^\s*use\s+([A-Za-z_:][^\s;]*)", re.MULTILINE),
    re.compile(r"^\s*include\s+['\"]?([^\s'\"]+)['\"]?", re.MULTILINE),
    re.compile(r"^\s*from\s+([^\s]+)\s+import", re.MULTILINE),
    re.compile(r"^\s*#include\s+[<\"]([^>\"]+)[>\"]", re.MULTILINE),
]


def _kind_from_match(line: str) -> str:
    line = line.lstrip()
    if re.match(r"(class|struct)\b", line):
        return "class"
    if re.match(r"(interface|trait)\b", line):
        return "interface"
    if re.match(r"(enum)\b", line):
        return "variable"
    return "unknown"


def parse(file_path: str, repo_path: str) -> tuple[list[Symbol], list[Import]]:
    try:
        text = Path(file_path).read_text(encoding="utf-8", errors="replace")
    except Exception:
        return [], []

    symbols: list[Symbol] = []
    imports: list[Import] = []

    try:
        lines = text.splitlines()

        # Symbols
        for pattern in _SYMBOL_PATTERNS:
            for m in pattern.finditer(text):
                name = m.group(1)
                line_num = text[:m.start()].count("\n") + 1
                line_text = lines[line_num - 1] if line_num <= len(lines) else ""
                kind = _kind_from_match(line_text)
                is_exported = bool(_EXPORT_PATTERN.match(line_text.lstrip()))
                symbols.append(Symbol(
                    name=name,
                    kind=kind,
                    file_path=file_path,
                    line_start=line_num,
                    line_end=line_num,
                    signature=line_text.strip(),
                    docstring=None,
                    is_exported=is_exported,
                ))

        # Imports
        for pattern in _IMPORT_PATTERNS:
            for m in pattern.finditer(text):
                mod = m.group(1).strip().rstrip(";")
                if mod:
                    imports.append(Import(
                        source_file=file_path,
                        imported_from=mod,
                        imported_names=[],
                        is_relative=mod.startswith(".") or mod.startswith("/"),
                    ))
    except Exception:
        pass

    return symbols, imports
