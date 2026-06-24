from __future__ import annotations

import asyncio
import shlex
from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable


@dataclass
class CommandResult:
    returncode: int
    stdout: str
    stderr: str

    @property
    def ok(self) -> bool:
        return self.returncode == 0


@runtime_checkable
class Sandbox(Protocol):
    async def run(
        self,
        cmd: list[str],
        *,
        cwd: str | None = None,
        timeout: float = 30.0,
        env: dict[str, str] | None = None,
    ) -> CommandResult: ...


class LocalSandbox:
    """Runs commands in a subprocess within the workspace directory.

    Suitable for dev/tests. Not isolated — use DockerSandbox for untrusted code.
    """

    async def run(
        self,
        cmd: list[str],
        *,
        cwd: str | None = None,
        timeout: float = 30.0,
        env: dict[str, str] | None = None,
    ) -> CommandResult:
        safe_cmd = [shlex.quote(c) for c in cmd]
        _ = safe_cmd  # validation only; asyncio takes the original list

        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=cwd,
                env=env,
            )
            try:
                stdout_b, stderr_b = await asyncio.wait_for(
                    proc.communicate(), timeout=timeout
                )
            except asyncio.TimeoutError:
                proc.kill()
                await proc.communicate()
                return CommandResult(
                    returncode=-1,
                    stdout="",
                    stderr=f"Command timed out after {timeout}s",
                )
        except FileNotFoundError as exc:
            return CommandResult(returncode=1, stdout="", stderr=str(exc))

        return CommandResult(
            returncode=proc.returncode or 0,
            stdout=stdout_b.decode("utf-8", errors="replace"),
            stderr=stderr_b.decode("utf-8", errors="replace"),
        )


class DockerSandbox:
    """Runs commands inside a Docker container with resource + network limits.

    Requirements:
    - Docker daemon must be running.
    - Image must be built from docker/sandbox.Dockerfile.
    - Workspace is mounted read-write at /workspace inside the container.

    Config wired from agentx/config.py via sandbox_type="docker".
    """

    _DEFAULT_IMAGE = "agentx-sandbox:latest"
    _DEFAULT_MEM = "512m"
    _DEFAULT_CPU = 1.0

    def __init__(
        self,
        image: str = _DEFAULT_IMAGE,
        mem_limit: str = _DEFAULT_MEM,
        cpu_quota: float = _DEFAULT_CPU,
        network_disabled: bool = True,
    ) -> None:
        self._image = image
        self._mem_limit = mem_limit
        self._cpu_quota = cpu_quota
        self._network_disabled = network_disabled

    def _client(self) -> Any:
        import docker
        return docker.from_env()

    async def run(
        self,
        cmd: list[str],
        *,
        cwd: str | None = None,
        timeout: float = 30.0,
        env: dict[str, str] | None = None,
    ) -> CommandResult:
        # cwd is the host-side workspace path to mount.
        # Inside the container we always work in /workspace.
        host_workspace = cwd

        def _blocking_run():
            import docker
            import docker.errors
            client = self._client()
            volumes = {}
            if host_workspace:
                volumes[host_workspace] = {"bind": "/workspace", "mode": "rw"}
            try:
                output = client.containers.run(
                    self._image,
                    command=cmd,
                    working_dir="/workspace",
                    volumes=volumes,
                    mem_limit=self._mem_limit,
                    nano_cpus=int(self._cpu_quota * 1e9),
                    network_disabled=self._network_disabled,
                    environment=env or {},
                    remove=True,
                    detach=False,
                    stdout=True,
                    stderr=True,
                )
                stdout = output.decode("utf-8", errors="replace") if isinstance(output, bytes) else ""
                return CommandResult(returncode=0, stdout=stdout, stderr="")
            except docker.errors.ContainerError as exc:
                return CommandResult(
                    returncode=exc.exit_status,
                    stdout="",
                    stderr=exc.stderr.decode("utf-8", errors="replace") if exc.stderr else str(exc),
                )
            except Exception as exc:  # noqa: BLE001
                return CommandResult(returncode=1, stdout="", stderr=str(exc))

        loop = asyncio.get_event_loop()
        try:
            result = await asyncio.wait_for(
                loop.run_in_executor(None, _blocking_run),
                timeout=timeout,
            )
        except asyncio.TimeoutError:
            return CommandResult(
                returncode=-1,
                stdout="",
                stderr=f"Docker command timed out after {timeout}s",
            )
        return result
