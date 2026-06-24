from __future__ import annotations

import pytest

# Skip entire module if Docker daemon is not reachable
try:
    import docker as _docker
    _client = _docker.from_env()
    _client.ping()
    _DOCKER_AVAILABLE = True
except Exception:
    _DOCKER_AVAILABLE = False

pytestmark = pytest.mark.skipif(
    not _DOCKER_AVAILABLE,
    reason="Docker daemon not available",
)

from agentx.runtime.sandbox import DockerSandbox


_IMAGE = "python:3.11-slim"  # use a known public image, not the project sandbox image


@pytest.fixture()
def sandbox() -> DockerSandbox:
    return DockerSandbox(image=_IMAGE, network_disabled=False)  # network needed to pull image


@pytest.mark.asyncio
async def test_command_runs(sandbox, tmp_path):
    result = await sandbox.run(
        ["python", "-c", "print('hello docker')"],
        cwd=str(tmp_path),
        timeout=60.0,
    )
    assert result.ok or "hello docker" in result.stdout


@pytest.mark.asyncio
async def test_nonzero_exit_captured(sandbox, tmp_path):
    result = await sandbox.run(
        ["python", "-c", "import sys; sys.exit(3)"],
        cwd=str(tmp_path),
        timeout=60.0,
    )
    assert not result.ok
    assert result.returncode == 3


@pytest.mark.asyncio
async def test_timeout_enforced(tmp_path):
    sb = DockerSandbox(image=_IMAGE, network_disabled=False)
    result = await sb.run(
        ["python", "-c", "import time; time.sleep(120)"],
        cwd=str(tmp_path),
        timeout=5.0,
    )
    assert result.returncode == -1
    assert "timed out" in result.stderr.lower()


@pytest.mark.asyncio
async def test_network_blocked(tmp_path):
    """With network_disabled=True, network access should fail."""
    sb = DockerSandbox(image=_IMAGE, network_disabled=True)
    result = await sb.run(
        ["python", "-c", "import urllib.request; urllib.request.urlopen('http://example.com')"],
        cwd=str(tmp_path),
        timeout=30.0,
    )
    # Expect failure due to no network
    assert not result.ok
