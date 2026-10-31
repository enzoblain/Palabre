"""Stable error codes of the REST API: every error carries a `code` next to the English `detail`."""

from fastapi import HTTPException, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.errors import ErrorCode


class ApiError(HTTPException):
    """An HTTPException that also names its error with a stable code."""

    def __init__(self, status_code: int, code: ErrorCode, detail: str, headers: dict[str, str] | None = None):
        super().__init__(status_code, detail, headers=headers)
        self.code = code


async def api_error(_: Request, exc: ApiError) -> JSONResponse:
    body = {"detail": exc.detail, "code": exc.code.value}
    return JSONResponse(body, status_code=exc.status_code, headers=exc.headers)


async def validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
    body = {"detail": jsonable_encoder(exc.errors()), "code": ErrorCode.VALIDATION_ERROR.value}
    return JSONResponse(body, status_code=422)


# Code of the "<Model> <id> not found" lookups, by model name
NOT_FOUND = {
    "Project": ErrorCode.PROJECT_NOT_FOUND,
    "Room": ErrorCode.ROOM_NOT_FOUND,
    "Task": ErrorCode.TASK_NOT_FOUND,
    "Conversation": ErrorCode.CONVERSATION_NOT_FOUND,
    "Decision": ErrorCode.DECISION_NOT_FOUND,
    "Employee": ErrorCode.EMPLOYEE_NOT_FOUND,
    "Message": ErrorCode.MESSAGE_NOT_FOUND,
    "OpenQuestion": ErrorCode.QUESTION_NOT_FOUND,
}
