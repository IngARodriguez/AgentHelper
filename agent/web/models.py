"""Modelos Pydantic para bodies de los endpoints."""

from __future__ import annotations

from pydantic import BaseModel


class TaskBody(BaseModel):
    task: str


class ShellBody(BaseModel):
    command: str
    timeout: float = 30.0


class InjectBody(BaseModel):
    message: str


class ResumeBody(BaseModel):
    task: str = ""  # opcional: instrucción nueva al reanudar
