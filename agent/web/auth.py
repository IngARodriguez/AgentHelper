"""Auth opcional para /api/*. Si API_TOKEN está vacío, no se exige nada."""

from __future__ import annotations

from fastapi import HTTPException

from ..config import API_TOKEN


def check_api_auth(authorization: str | None) -> None:
    """Si API_TOKEN está definido, exige Authorization: Bearer <token>."""
    if not API_TOKEN:
        return
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="falta Authorization: Bearer <token>")
    token = authorization[len("Bearer "):].strip()
    if token != API_TOKEN:
        raise HTTPException(status_code=403, detail="token inválido")
