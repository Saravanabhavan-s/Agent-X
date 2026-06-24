from __future__ import annotations

import shutil
import tempfile
from pathlib import Path

import pytest

from agentx.llm.fake import FakeModelClient
from agentx.llm.types import ToolCall
from agentx.runtime.sandbox import LocalSandbox
from agentx.runtime.workspace import Workspace


@pytest.fixture()
def tmp_workspace(tmp_path: Path) -> Workspace:
    return Workspace(str(tmp_path))


@pytest.fixture()
def toy_workspace(tmp_path: Path) -> Workspace:
    """Copy toy_repo into a fresh tmpdir so tests don't clobber the source."""
    src = Path(__file__).parent.parent / "toy_repo"
    dst = tmp_path / "toy_repo"
    shutil.copytree(src, dst)
    return Workspace(str(dst))


@pytest.fixture()
def sandbox() -> LocalSandbox:
    return LocalSandbox()


@pytest.fixture()
def fake_model() -> FakeModelClient:
    return FakeModelClient([])
