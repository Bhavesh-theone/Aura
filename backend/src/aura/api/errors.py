"""Map core domain errors to HTTP responses."""
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from aura.core.domain.errors import (Conflict, Forbidden, GuardBlocked, InvalidTransition,
                                     NotFound, RateLimited, RuleViolation)
from aura.core.domain.ingest import CorruptDocument, DocumentTooLarge, UnsupportedFormat


def evaluation_out(ev) -> dict:
    return {"guard_name": ev.guard_name, "result": ev.result, "detail": ev.detail,
            "severity": ev.severity.value, "description": ev.description,
            "overridden_by": ev.overridden_by, "override_role": ev.override_role}


def register_error_handlers(app: FastAPI) -> None:
    def simple(status_code: int):
        def handler(_: Request, exc: Exception) -> JSONResponse:
            return JSONResponse({"detail": str(exc)}, status_code=status_code)
        return handler

    app.add_exception_handler(NotFound, simple(404))
    app.add_exception_handler(Conflict, simple(409))
    app.add_exception_handler(RuleViolation, simple(422))
    app.add_exception_handler(Forbidden, simple(403))
    # Ingestion (more specific than RuleViolation/DomainError, so these win).
    app.add_exception_handler(UnsupportedFormat, simple(415))
    app.add_exception_handler(DocumentTooLarge, simple(413))
    app.add_exception_handler(CorruptDocument, simple(422))

    def blocked(_: Request, exc: Exception) -> JSONResponse:
        evaluations = [evaluation_out(e) for e in getattr(exc, "evaluations", [])]
        return JSONResponse({"detail": str(exc), "evaluations": evaluations}, status_code=409)

    def limited(_: Request, exc: Exception) -> JSONResponse:
        retry_after = int(getattr(exc, "retry_after_seconds", 1))
        return JSONResponse({"detail": str(exc), "retry_after_seconds": retry_after},
                            status_code=429, headers={"Retry-After": str(retry_after)})

    app.add_exception_handler(RateLimited, limited)
    app.add_exception_handler(InvalidTransition, blocked)
    app.add_exception_handler(GuardBlocked, blocked)
