from __future__ import annotations

from pathlib import Path

import pytest

from agentx.intelligence.parsers.typescript_parser import parse


SAMPLE_TS = '''\
import { Foo, Bar } from "./models";
import React from "react";
import * as utils from "../utils";
import type { Config } from "config-pkg";

export interface UserInterface {
    name: string;
    age: number;
}

export type UserId = string;

export class UserService {
    private users: UserInterface[] = [];

    getUser(id: string): UserInterface | null {
        return null;
    }

    addUser(user: UserInterface): void {}
}

export function createUser(name: string): UserInterface {
    return { name, age: 0 };
}

export const MAX_USERS = 100;

const internalConst = "hidden";

export const helper = (x: number) => x * 2;
'''


def test_symbols_extracted(tmp_path: Path) -> None:
    f = tmp_path / "sample.ts"
    f.write_text(SAMPLE_TS)
    symbols, _ = parse(str(f), str(tmp_path))
    names = {s.name for s in symbols}
    assert "UserInterface" in names
    assert "UserService" in names
    assert "createUser" in names


def test_interface_kind(tmp_path: Path) -> None:
    f = tmp_path / "sample.ts"
    f.write_text(SAMPLE_TS)
    symbols, _ = parse(str(f), str(tmp_path))
    by_name = {s.name: s for s in symbols}
    assert by_name["UserInterface"].kind == "interface"


def test_class_kind(tmp_path: Path) -> None:
    f = tmp_path / "sample.ts"
    f.write_text(SAMPLE_TS)
    symbols, _ = parse(str(f), str(tmp_path))
    by_name = {s.name: s for s in symbols}
    assert by_name["UserService"].kind == "class"


def test_function_kind(tmp_path: Path) -> None:
    f = tmp_path / "sample.ts"
    f.write_text(SAMPLE_TS)
    symbols, _ = parse(str(f), str(tmp_path))
    by_name = {s.name: s for s in symbols}
    assert by_name["createUser"].kind == "function"


def test_imports_extracted(tmp_path: Path) -> None:
    f = tmp_path / "sample.ts"
    f.write_text(SAMPLE_TS)
    _, imports = parse(str(f), str(tmp_path))
    sources = {i.imported_from for i in imports}
    assert "./models" in sources
    assert "react" in sources


def test_relative_import(tmp_path: Path) -> None:
    f = tmp_path / "sample.ts"
    f.write_text(SAMPLE_TS)
    _, imports = parse(str(f), str(tmp_path))
    rel = [i for i in imports if i.is_relative]
    assert len(rel) >= 1


def test_never_crashes(tmp_path: Path) -> None:
    f = tmp_path / "bad.ts"
    f.write_bytes(b"\x00\xff garbage")
    syms, imps = parse(str(f), str(tmp_path))
    assert isinstance(syms, list)
    assert isinstance(imps, list)
