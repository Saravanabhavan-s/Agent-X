from __future__ import annotations

from pathlib import Path

import pytest

from agentx.intelligence.parsers.python_parser import parse


SAMPLE_PY = '''\
"""Module docstring."""
import os
import sys as system
from pathlib import Path
from . import utils
from ..models import User

MAX_SIZE = 100
_private_var = "secret"


class MyClass:
    """A class."""

    def public_method(self, x: int) -> int:
        """Method doc."""
        return x + 1

    def _private_method(self):
        pass


def top_level_func(a, b):
    """Func doc."""
    return a + b


async def async_func():
    pass
'''


def test_symbols_extracted(tmp_path: Path) -> None:
    f = tmp_path / "sample.py"
    f.write_text(SAMPLE_PY)
    symbols, _ = parse(str(f), str(tmp_path))

    names = {s.name for s in symbols}
    assert "MyClass" in names
    assert "public_method" in names
    assert "_private_method" in names
    assert "top_level_func" in names
    assert "async_func" in names
    assert "MAX_SIZE" in names
    assert "_private_var" in names


def test_symbol_kinds(tmp_path: Path) -> None:
    f = tmp_path / "sample.py"
    f.write_text(SAMPLE_PY)
    symbols, _ = parse(str(f), str(tmp_path))

    by_name = {s.name: s for s in symbols}
    assert by_name["MyClass"].kind == "class"
    assert by_name["public_method"].kind == "method"
    assert by_name["top_level_func"].kind == "function"
    assert by_name["async_func"].kind == "function"
    assert by_name["MAX_SIZE"].kind == "const"
    assert by_name["_private_var"].kind == "variable"


def test_is_exported(tmp_path: Path) -> None:
    f = tmp_path / "sample.py"
    f.write_text(SAMPLE_PY)
    symbols, _ = parse(str(f), str(tmp_path))

    by_name = {s.name: s for s in symbols}
    assert by_name["MyClass"].is_exported is True
    assert by_name["_private_method"].is_exported is False
    assert by_name["MAX_SIZE"].is_exported is True
    assert by_name["_private_var"].is_exported is False


def test_imports_extracted(tmp_path: Path) -> None:
    f = tmp_path / "sample.py"
    f.write_text(SAMPLE_PY)
    _, imports = parse(str(f), str(tmp_path))

    sources = {i.imported_from for i in imports}
    assert "os" in sources
    assert any("pathlib" in s for s in sources)


def test_relative_import_is_relative(tmp_path: Path) -> None:
    f = tmp_path / "sample.py"
    f.write_text(SAMPLE_PY)
    _, imports = parse(str(f), str(tmp_path))

    rel = [i for i in imports if i.is_relative]
    assert len(rel) >= 1


def test_never_crashes_on_bad_file(tmp_path: Path) -> None:
    f = tmp_path / "bad.py"
    f.write_bytes(b"\x00\xff\xfe garbage \x80")
    syms, imps = parse(str(f), str(tmp_path))
    assert isinstance(syms, list)
    assert isinstance(imps, list)


def test_empty_file(tmp_path: Path) -> None:
    f = tmp_path / "empty.py"
    f.write_text("")
    syms, imps = parse(str(f), str(tmp_path))
    assert syms == []
    assert imps == []


def test_line_numbers(tmp_path: Path) -> None:
    f = tmp_path / "sample.py"
    f.write_text(SAMPLE_PY)
    symbols, _ = parse(str(f), str(tmp_path))

    by_name = {s.name: s for s in symbols}
    cls = by_name["MyClass"]
    assert cls.line_start >= 1
    assert cls.line_end >= cls.line_start
