# -*- coding: utf-8 -*-
"""The twenty lines of ``ai_drama_engine.media`` that the AIGC labeller uses.

Vendored deliberately rather than imported. The original module is 31KB and
pulls in an engine config and a project loader behind it, none of which a
labelling step needs; depending on it would have made this package unusable
outside the workstation it grew up on.
"""
from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class CommandResult:
    command: tuple[str, ...]
    stdout: str
    stderr: str


class CommandRunner:
    """Run a command, raise with the tail of its output when it fails."""

    def run(self, command: list[str], cwd: Path, timeout: int = 3_600) -> CommandResult:
        result = subprocess.run(
            command, cwd=str(cwd), text=True, encoding="utf-8", errors="replace",
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=timeout,
            check=False)
        if result.returncode != 0:
            detail = ((result.stdout or "") + "\n" + (result.stderr or "")).strip()
            raise RuntimeError(
                f"command failed with exit {result.returncode}: "
                f"{subprocess.list2cmdline(command)}\n{detail[-8_000:]}")
        return CommandResult(tuple(command), result.stdout or "", result.stderr or "")
