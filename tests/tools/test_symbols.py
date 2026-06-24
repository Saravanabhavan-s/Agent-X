from __future__ import annotations

from pathlib import Path

import pytest

from agentx.tools.symbols import SymbolsArgs, SymbolsTool, extract_symbols, find_references
from agentx.tools.base import ToolContext

pytest.importorskip("tree_sitter_python", reason="tree-sitter-python not installed")


@pytest.fixture()
def py_file(tmp_path: Path) -> Path:
    content = '''\
def add(a, b):
    return a + b

class Calculator:
    def multiply(self, a, b):
        return a * b

    def divide(self, a, b):
        return a / b

MY_CONST = 42
'''
    p = tmp_path / "calc.py"
    p.write_text(content)
    return p


@pytest.fixture()
def js_file(tmp_path: Path) -> Path:
    content = '''\
function greet(name) {
    return "Hello " + name;
}

class Greeter {
    greet(name) {
        return greet(name);
    }
}
'''
    p = tmp_path / "greet.js"
    p.write_text(content)
    return p


# ---------------------------------------------------------------------------
# extract_symbols — Python
# ---------------------------------------------------------------------------

def test_extract_python_functions(py_file):
    symbols = extract_symbols(str(py_file))
    kinds = {s["name"]: s["kind"] for s in symbols}
    assert kinds["add"] == "function"


def test_extract_python_class(py_file):
    symbols = extract_symbols(str(py_file))
    kinds = {s["name"]: s["kind"] for s in symbols}
    assert kinds["Calculator"] == "class"


def test_extract_python_methods(py_file):
    symbols = extract_symbols(str(py_file))
    kinds = {s["name"]: s["kind"] for s in symbols}
    assert kinds["multiply"] == "method"
    assert kinds["divide"] == "method"


def test_extract_python_line_numbers(py_file):
    symbols = extract_symbols(str(py_file))
    add_sym = next(s for s in symbols if s["name"] == "add")
    assert add_sym["line"] == 1


def test_extract_unsupported_extension(tmp_path):
    p = tmp_path / "data.csv"
    p.write_text("a,b,c\n1,2,3\n")
    symbols = extract_symbols(str(p))
    assert symbols == []


# ---------------------------------------------------------------------------
# extract_symbols — JavaScript
# ---------------------------------------------------------------------------

def test_extract_js_function(js_file):
    pytest.importorskip("tree_sitter_javascript", reason="tree-sitter-javascript not installed")
    symbols = extract_symbols(str(js_file))
    kinds = {s["name"]: s["kind"] for s in symbols}
    assert kinds.get("greet") in ("function", "method")


def test_extract_js_class(js_file):
    pytest.importorskip("tree_sitter_javascript", reason="tree-sitter-javascript not installed")
    symbols = extract_symbols(str(js_file))
    kinds = {s["name"]: s["kind"] for s in symbols}
    assert kinds.get("Greeter") == "class"


# ---------------------------------------------------------------------------
# find_references
# ---------------------------------------------------------------------------

def test_find_references_returns_matches(tmp_path: Path):
    (tmp_path / "a.py").write_text("def foo(): pass\n")
    (tmp_path / "b.py").write_text("from a import foo\nfoo()\n")
    refs = find_references("foo", str(tmp_path))
    assert len(refs) >= 2


def test_find_references_no_match(tmp_path: Path):
    (tmp_path / "a.py").write_text("x = 1\n")
    refs = find_references("nonexistent_symbol_xyz", str(tmp_path))
    assert refs == []


def test_find_references_word_boundary(tmp_path: Path):
    # "foobar" should not match a search for "foo"
    (tmp_path / "a.py").write_text("foobar = 1\nfoo = 2\n")
    refs = find_references("foo", str(tmp_path))
    names = [m["line"].strip() for m in refs]
    # foobar line should not be returned as a "foo" reference
    assert any("foo = 2" in n for n in names)
    assert not any("foobar = 1" in n for n in names)


# ---------------------------------------------------------------------------
# SymbolsTool via run()
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_tool_extract_action(tmp_path, py_file):
    ctx = ToolContext(workspace=str(tmp_path), session_id="test")
    tool = SymbolsTool()
    result = await tool.run(SymbolsArgs(action="extract", path="calc.py"), ctx)
    assert result.ok
    assert "Calculator" in result.observation
    assert result.data["symbols"]


@pytest.mark.asyncio
async def test_tool_extract_missing_path(tmp_path):
    ctx = ToolContext(workspace=str(tmp_path), session_id="test")
    tool = SymbolsTool()
    result = await tool.run(SymbolsArgs(action="extract"), ctx)
    assert not result.ok


@pytest.mark.asyncio
async def test_tool_find_references_action(tmp_path):
    (tmp_path / "a.py").write_text("def my_func(): pass\n")
    (tmp_path / "b.py").write_text("my_func()\n")
    ctx = ToolContext(workspace=str(tmp_path), session_id="test")
    tool = SymbolsTool()
    result = await tool.run(SymbolsArgs(action="find_references", symbol_name="my_func"), ctx)
    assert result.ok
    assert len(result.data["matches"]) >= 2


@pytest.mark.asyncio
async def test_tool_path_escapes_workspace(tmp_path):
    ctx = ToolContext(workspace=str(tmp_path), session_id="test")
    tool = SymbolsTool()
    result = await tool.run(SymbolsArgs(action="extract", path="../../etc/passwd"), ctx)
    assert not result.ok
