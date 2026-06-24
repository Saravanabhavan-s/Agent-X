from __future__ import annotations

from pathlib import Path

from agentx.intelligence.parsers.javascript_parser import parse


SAMPLE_JS = '''\
const express = require("express");
const { helper } = require("./utils");

class Router {
    constructor() {}
    handle(req, res) {}
}

function createApp() {
    return express();
}

module.exports = { createApp };
exports.Router = Router;
'''


def test_symbols_extracted(tmp_path: Path) -> None:
    f = tmp_path / "app.js"
    f.write_text(SAMPLE_JS)
    symbols, _ = parse(str(f), str(tmp_path))
    names = {s.name for s in symbols}
    assert "Router" in names
    assert "createApp" in names


def test_commonjs_exports(tmp_path: Path) -> None:
    f = tmp_path / "app.js"
    f.write_text(SAMPLE_JS)
    symbols, _ = parse(str(f), str(tmp_path))
    exported = {s.name for s in symbols if s.is_exported}
    assert "createApp" in exported
    assert "Router" in exported


def test_require_imports(tmp_path: Path) -> None:
    f = tmp_path / "app.js"
    f.write_text(SAMPLE_JS)
    _, imports = parse(str(f), str(tmp_path))
    sources = {i.imported_from for i in imports}
    assert "express" in sources
    assert "./utils" in sources


def test_never_crashes(tmp_path: Path) -> None:
    f = tmp_path / "bad.js"
    f.write_bytes(b"\x00 garbage }{")
    syms, imps = parse(str(f), str(tmp_path))
    assert isinstance(syms, list)
    assert isinstance(imps, list)
