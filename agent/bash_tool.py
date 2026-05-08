"""Bash tool: ejecuta comandos shell en el sandbox y devuelve stdout/stderr/exit_code.

Usado tanto por el agente (como tool) como por el endpoint /shell del server
(para que el usuario también pueda ejecutar comandos desde la UI).
"""

from __future__ import annotations

import subprocess
from typing import Any

DEFAULT_TIMEOUT_S = 30.0
MAX_TIMEOUT_S = 120.0
MAX_STDOUT_BYTES = 10_000
MAX_STDERR_BYTES = 5_000


def execute_bash(command: str, timeout: float = DEFAULT_TIMEOUT_S) -> dict[str, Any]:
    """Ejecuta `command` con `bash -c`, captura stdout/stderr/exit_code.

    Trunca la salida si es muy grande para no inflar el contexto del modelo.
    """
    if not isinstance(command, str) or not command.strip():
        return {"stdout": "", "stderr": "", "exit_code": -1, "error": "comando vacío"}

    timeout = max(0.5, min(float(timeout), MAX_TIMEOUT_S))

    try:
        proc = subprocess.run(
            ["bash", "-c", command],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        return {"stdout": "", "stderr": "", "exit_code": -1, "error": f"timeout tras {timeout}s"}
    except FileNotFoundError:
        return {"stdout": "", "stderr": "", "exit_code": -1, "error": "bash no encontrado en PATH"}
    except Exception as e:  # noqa: BLE001
        return {"stdout": "", "stderr": "", "exit_code": -1, "error": f"{type(e).__name__}: {e}"}

    stdout, stderr = proc.stdout, proc.stderr
    if len(stdout) > MAX_STDOUT_BYTES:
        stdout = stdout[:MAX_STDOUT_BYTES] + (
            f"\n[…stdout truncado, {len(proc.stdout)} bytes total]"
        )
    if len(stderr) > MAX_STDERR_BYTES:
        stderr = stderr[:MAX_STDERR_BYTES] + (
            f"\n[…stderr truncado, {len(proc.stderr)} bytes total]"
        )

    return {
        "stdout": stdout,
        "stderr": stderr,
        "exit_code": proc.returncode,
        "error": None,
    }


def to_tool_result_content(result: dict[str, Any]) -> list[dict[str, Any]]:
    """Convierte el resultado a content blocks para el tool_result del modelo."""
    if result.get("error"):
        return [{"type": "text", "text": f"error: {result['error']}"}]

    parts: list[str] = [f"exit_code: {result['exit_code']}"]
    if result["stdout"]:
        parts.append(f"--- stdout ---\n{result['stdout']}")
    if result["stderr"]:
        parts.append(f"--- stderr ---\n{result['stderr']}")
    if not result["stdout"] and not result["stderr"]:
        parts.append("(sin salida)")
    return [{"type": "text", "text": "\n".join(parts)}]
