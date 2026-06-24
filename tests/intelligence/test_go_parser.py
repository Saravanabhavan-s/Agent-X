from __future__ import annotations

from pathlib import Path

from agentx.intelligence.parsers.go_parser import parse


SAMPLE_GO = '''\
package main

import (
    "fmt"
    "os"
    mylib "github.com/user/mylib"
)

const MaxSize = 100
const internalConst = "hidden"

var globalVar int

type User struct {
    Name string
    age  int
}

type UserService interface {
    GetUser(id string) *User
}

func NewUser(name string) *User {
    return &User{Name: name}
}

func (u *User) GetName() string {
    return u.Name
}

func internalHelper() {
    fmt.Println("internal")
}
'''


def test_symbols_extracted(tmp_path: Path) -> None:
    go_mod = tmp_path / "go.mod"
    go_mod.write_text("module example.com/myapp\n\ngo 1.21\n")
    f = tmp_path / "main.go"
    f.write_text(SAMPLE_GO)
    symbols, _ = parse(str(f), str(tmp_path))
    names = {s.name for s in symbols}
    assert "User" in names
    assert "UserService" in names
    assert "NewUser" in names
    assert "GetName" in names


def test_struct_kind(tmp_path: Path) -> None:
    f = tmp_path / "main.go"
    f.write_text(SAMPLE_GO)
    symbols, _ = parse(str(f), str(tmp_path))
    by_name = {s.name: s for s in symbols}
    assert by_name["User"].kind == "struct"


def test_interface_kind(tmp_path: Path) -> None:
    f = tmp_path / "main.go"
    f.write_text(SAMPLE_GO)
    symbols, _ = parse(str(f), str(tmp_path))
    by_name = {s.name: s for s in symbols}
    assert by_name["UserService"].kind == "interface"


def test_method_kind(tmp_path: Path) -> None:
    f = tmp_path / "main.go"
    f.write_text(SAMPLE_GO)
    symbols, _ = parse(str(f), str(tmp_path))
    by_name = {s.name: s for s in symbols}
    assert by_name["GetName"].kind == "method"


def test_is_exported(tmp_path: Path) -> None:
    f = tmp_path / "main.go"
    f.write_text(SAMPLE_GO)
    symbols, _ = parse(str(f), str(tmp_path))
    by_name = {s.name: s for s in symbols}
    assert by_name["NewUser"].is_exported is True
    assert by_name["internalHelper"].is_exported is False
    assert by_name["MaxSize"].is_exported is True
    assert by_name["internalConst"].is_exported is False


def test_imports_extracted(tmp_path: Path) -> None:
    f = tmp_path / "main.go"
    f.write_text(SAMPLE_GO)
    _, imports = parse(str(f), str(tmp_path))
    sources = {i.imported_from for i in imports}
    assert "fmt" in sources
    assert "os" in sources
    assert "github.com/user/mylib" in sources


def test_never_crashes(tmp_path: Path) -> None:
    f = tmp_path / "bad.go"
    f.write_bytes(b"\x00\xff garbage {{{")
    syms, imps = parse(str(f), str(tmp_path))
    assert isinstance(syms, list)
    assert isinstance(imps, list)
