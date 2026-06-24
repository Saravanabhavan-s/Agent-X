from __future__ import annotations

from pathlib import Path

from agentx.intelligence.parsers.generic_parser import parse


SAMPLE_RUBY = '''\
require "net/http"
require_relative "./helper"

class DataProcessor
  def process(data)
    data.upcase
  end

  def validate(data)
    !data.nil?
  end
end

def standalone_func(x)
  x + 1
end
'''


def test_symbols_extracted(tmp_path: Path) -> None:
    f = tmp_path / "sample.rb"
    f.write_text(SAMPLE_RUBY)
    symbols, _ = parse(str(f), str(tmp_path))
    names = {s.name for s in symbols}
    assert "DataProcessor" in names


def test_imports_extracted(tmp_path: Path) -> None:
    f = tmp_path / "sample.rb"
    f.write_text(SAMPLE_RUBY)
    _, imports = parse(str(f), str(tmp_path))
    sources = {i.imported_from for i in imports}
    assert len(sources) >= 1


def test_never_crashes_on_binary(tmp_path: Path) -> None:
    f = tmp_path / "binary.bin"
    f.write_bytes(bytes(range(256)))
    syms, imps = parse(str(f), str(tmp_path))
    assert isinstance(syms, list)
    assert isinstance(imps, list)


def test_never_crashes_on_missing_file(tmp_path: Path) -> None:
    syms, imps = parse(str(tmp_path / "nonexistent.xyz"), str(tmp_path))
    assert syms == []
    assert imps == []


def test_empty_file(tmp_path: Path) -> None:
    f = tmp_path / "empty.php"
    f.write_text("")
    syms, imps = parse(str(f), str(tmp_path))
    assert isinstance(syms, list)
    assert isinstance(imps, list)


def test_c_include(tmp_path: Path) -> None:
    f = tmp_path / "main.c"
    f.write_text('#include <stdio.h>\n#include "mylib.h"\n\nvoid doThing() {}\n')
    _, imports = parse(str(f), str(tmp_path))
    sources = {i.imported_from for i in imports}
    assert "stdio.h" in sources or "mylib.h" in sources
