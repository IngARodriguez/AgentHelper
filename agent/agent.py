"""Shim de retrocompatibilidad. El código real vive en `agent.core.*`.

Lo mantenemos para que `from agent.agent import run_agent` (telegram_bot) y
cualquier otro consumidor externo sigan funcionando sin cambios.
"""

from __future__ import annotations

from .core.loop import run_agent
from .core.prompts import SYSTEM_PROMPT
from .core.tools import TOOLS

__all__ = ["run_agent", "SYSTEM_PROMPT", "TOOLS"]
