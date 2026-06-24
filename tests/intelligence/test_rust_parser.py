from __future__ import annotations

from pathlib import Path

from agentx.intelligence.parsers.rust_parser import parse


SAMPLE_RS = '''\
use std::collections::HashMap;
use crate::models::User;
use serde::{Deserialize, Serialize};

pub const MAX_SIZE: usize = 100;
static INTERNAL: &str = "hidden";

pub struct UserStore {
    users: HashMap<String, User>,
}

pub trait Repository {
    fn get(&self, id: &str) -> Option<&User>;
}

impl UserStore {
    pub fn new() -> Self {
        Self { users: HashMap::new() }
    }

    pub fn get_user(&self, id: &str) -> Option<&User> {
        self.users.get(id)
    }
}

pub fn create_store() -> UserStore {
    UserStore::new()
}

fn internal_helper() {}
'''


def test_symbols_extracted(tmp_path: Path) -> None:
    f = tmp_path / "lib.rs"
    f.write_text(SAMPLE_RS)
    symbols, _ = parse(str(f), str(tmp_path))
    names = {s.name for s in symbols}
    assert "UserStore" in names
    assert "Repository" in names
    assert "create_store" in names


def test_struct_kind(tmp_path: Path) -> None:
    f = tmp_path / "lib.rs"
    f.write_text(SAMPLE_RS)
    symbols, _ = parse(str(f), str(tmp_path))
    by_name = {s.name: s for s in symbols}
    assert by_name["UserStore"].kind == "struct"


def test_trait_kind(tmp_path: Path) -> None:
    f = tmp_path / "lib.rs"
    f.write_text(SAMPLE_RS)
    symbols, _ = parse(str(f), str(tmp_path))
    by_name = {s.name: s for s in symbols}
    assert by_name["Repository"].kind == "interface"


def test_is_exported_pub(tmp_path: Path) -> None:
    f = tmp_path / "lib.rs"
    f.write_text(SAMPLE_RS)
    symbols, _ = parse(str(f), str(tmp_path))
    by_name = {s.name: s for s in symbols}
    assert by_name["UserStore"].is_exported is True
    assert by_name["internal_helper"].is_exported is False
    assert by_name["MAX_SIZE"].is_exported is True


def test_imports_extracted(tmp_path: Path) -> None:
    f = tmp_path / "lib.rs"
    f.write_text(SAMPLE_RS)
    _, imports = parse(str(f), str(tmp_path))
    sources = {i.imported_from for i in imports}
    assert any("std" in s for s in sources)
    assert any("crate" in s for s in sources)


def test_never_crashes(tmp_path: Path) -> None:
    f = tmp_path / "bad.rs"
    f.write_bytes(b"\x00 garbage {{{")
    syms, imps = parse(str(f), str(tmp_path))
    assert isinstance(syms, list)
    assert isinstance(imps, list)
