"""Python Executor — Wave 11.C migration."""

from __future__ import annotations

import multiprocessing
import os
import time
from typing import Any

from services.plugin import NodeContext, NodeUserError, Operation

from .._base import CodeExecutorBase, CodeExecutorParams


# Names available in the sandbox namespace -- kept here so the
# error-handler can list them when the LLM tries `import X` and hits
# the "no __import__" wall.
_SANDBOX_NAMES = "math, json, datetime, timedelta, re, random, Counter, defaultdict"


def _execute_user_code(code: str, input_data: dict[str, Any], workspace_dir: str) -> dict[str, Any]:
    import datetime as datetime_module
    import io
    import json as json_module
    import math
    import random as random_module
    import re as re_module
    from collections import Counter, defaultdict

    stdout_capture = io.StringIO()

    def captured_print(*args, **kwargs):
        kwargs["file"] = stdout_capture
        print(*args, **kwargs)

    safe_builtins = {
        "abs": abs,
        "all": all,
        "any": any,
        "bool": bool,
        "dict": dict,
        "enumerate": enumerate,
        "filter": filter,
        "float": float,
        "int": int,
        "len": len,
        "list": list,
        "map": map,
        "max": max,
        "min": min,
        "print": captured_print,
        "range": range,
        "round": round,
        "set": set,
        "sorted": sorted,
        "str": str,
        "sum": sum,
        "tuple": tuple,
        "type": type,
        "zip": zip,
        "True": True,
        "False": False,
        "None": None,
        # Pre-injected modules — match the documented sandbox contract
        # (skill docs, CLAUDE.md). No __import__: callers reference these
        # by name, e.g. ``datetime.datetime.now()`` not ``import datetime``.
        "math": math,
        "json": json_module,
        "datetime": datetime_module,
        "timedelta": datetime_module.timedelta,
        "re": re_module,
        "random": random_module,
        "Counter": Counter,
        "defaultdict": defaultdict,
    }
    namespace = {
        "__builtins__": safe_builtins,
        "input_data": input_data,
        "workspace_dir": workspace_dir,
        "output": None,
    }
    try:
        exec(code, namespace)  # noqa: S102 — sandboxed namespace in a child process
    except Exception as exc:
        err_type = type(exc).__name__
        err_msg = str(exc)

        if isinstance(exc, ImportError) and "__import__" in err_msg:
            raise NodeUserError(
                "Python sandbox does not allow `import` statements. "
                f"These names are pre-injected and ready to use: {_SANDBOX_NAMES}. "
                "Reference them directly -- e.g. `math.sqrt(4)`, "
                "`json.dumps(x)`, `datetime.datetime.now()`. "
                "If you need a module not on the list, drop the "
                "`import` and use process_manager to run a Python "
                "script with full PATH access instead."
            ) from exc

        line_info = ""
        traceback = exc.__traceback__
        while traceback:
            if traceback.tb_frame.f_code.co_filename == "<string>":
                line_info = f" at line {traceback.tb_lineno}"
                break
            traceback = traceback.tb_next

        captured = stdout_capture.getvalue()
        suffix = f"\n\nstdout before error:\n{captured}" if captured else ""
        raise NodeUserError(f"{err_type}{line_info}: {err_msg}{suffix}") from exc

    return {
        "output": namespace.get("output"),
        "console_output": stdout_capture.getvalue(),
    }


def _python_executor_worker(
    code: str,
    input_data: dict[str, Any],
    workspace_dir: str,
    result_pipe: Any,
) -> None:
    try:
        result_pipe.send(("ok", _execute_user_code(code, input_data, workspace_dir)))
    except NodeUserError as exc:
        result_pipe.send(("user_error", str(exc)))
    except BaseException as exc:  # noqa: BLE001
        result_pipe.send(("user_error", f"{type(exc).__name__}: {exc}"))
    finally:
        result_pipe.close()


class PythonExecutorNode(CodeExecutorBase):
    type = "pythonExecutor"
    display_name = "Python Executor"
    subtitle = "Run Python"
    description = "Execute trusted Python code for calculations, data processing, and automation"
    tool_name = "python_code"
    tool_description = "Execute trusted Python code for calculations, data processing, and automation. For untrusted code use sandboxed_python. Available: math, json, datetime, Counter, defaultdict. Set output variable with result."

    @Operation("execute")
    async def execute_op(self, ctx: NodeContext, params: CodeExecutorParams) -> Any:
        """Inlined from handlers/code.py (Wave 11.D.2).

        Executes user code in a restricted namespace with stdout capture.
        ``input_data`` exposes ``connected_outputs`` so upstream node
        results are reachable; ``workspace_dir`` is the per-workflow
        scratch directory.
        """
        if not params.code.strip():
            raise NodeUserError("No code provided")

        input_data = ctx.raw.get("connected_outputs") or {}
        mp_context = multiprocessing.get_context("fork" if hasattr(os, "fork") else "spawn")
        result_pipe, child_pipe = mp_context.Pipe(duplex=False)
        process = mp_context.Process(
            target=_python_executor_worker,
            args=(params.code, input_data, ctx.workspace_dir or "", child_pipe),
        )

        process.start()
        child_pipe.close()
        deadline = time.monotonic() + params.timeout
        message: tuple[str, Any] | None = None
        try:
            while True:
                remaining = deadline - time.monotonic()
                if result_pipe.poll(max(0.0, min(0.05, remaining))):
                    try:
                        message = result_pipe.recv()
                    except EOFError:
                        message = None
                    break
                if not process.is_alive():
                    break
                if remaining <= 0:
                    process.terminate()
                    process.join(timeout=1)
                    if process.is_alive():
                        process.kill()
                        process.join(timeout=1)
                    raise NodeUserError(f"Python execution timed out after {params.timeout}s")

            process.join(timeout=1)
            if message is None:
                raise NodeUserError(f"Python execution failed without a result (exit code {process.exitcode})")
        finally:
            result_pipe.close()
            if process.is_alive():
                process.terminate()
                process.join(timeout=1)

        status, payload = message
        if status == "ok":
            return payload
        raise NodeUserError(str(payload))
