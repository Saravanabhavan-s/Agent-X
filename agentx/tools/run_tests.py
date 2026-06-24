from __future__ import annotations

from typing import Any

from pydantic import BaseModel

from agentx.tools.base import Risk, ToolContext, ToolResult, register


class RunTestsArgs(BaseModel):
    path: str = "."
    extra_args: list[str] = []


class RunTestsTool:
    name = "run_tests"
    description = (
        "Run pytest in the workspace. "
        "`path` is the workspace-relative directory or file to test (default: entire workspace). "
        "`extra_args` are passed verbatim to pytest after the path."
    )
    risk = Risk.SAFE
    input_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "path": {"type": "string", "default": "."},
            "extra_args": {
                "type": "array",
                "items": {"type": "string"},
                "default": [],
            },
        },
        "required": [],
    }

    async def run(self, args: BaseModel, ctx: ToolContext) -> ToolResult:
        assert isinstance(args, RunTestsArgs)
        if ctx.sandbox is None:
            return ToolResult(ok=False, observation="No sandbox available — cannot run tests.")

        cmd = ["python", "-m", "pytest", args.path, "-v", "--tb=short", "--no-header"]
        cmd.extend(args.extra_args)

        result = await ctx.sandbox.run(cmd, cwd=ctx.workspace, timeout=120.0)

        output = result.stdout + (("\n" + result.stderr) if result.stderr.strip() else "")
        passed = result.ok

        return ToolResult(
            ok=passed,
            observation=output or "(no output)",
            data={"returncode": result.returncode, "stdout": result.stdout, "stderr": result.stderr},
        )


run_tests = RunTestsTool()
register(run_tests)
