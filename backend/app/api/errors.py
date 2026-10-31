"""Stable error codes of the REST API: every error carries a `code` next to the English `detail`."""

from enum import StrEnum

from fastapi import HTTPException, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse


class ErrorCode(StrEnum):
    """Values are part of the API contract (the frontend translates them): never rename one."""

    AUTH_INVALID_TOKEN = "auth_invalid_token"
    AUTH_LOCKED = "auth_locked"
    VALIDATION_ERROR = "validation_error"
    WORKFLOW_ERROR = "workflow_error"
    GITHUB_ERROR = "github_error"
    GITHUB_MERGE_REFUSED = "github_merge_refused"
    PROJECT_NOT_FOUND = "project_not_found"
    ROOM_NOT_FOUND = "room_not_found"
    TASK_NOT_FOUND = "task_not_found"
    CONVERSATION_NOT_FOUND = "conversation_not_found"
    DECISION_NOT_FOUND = "decision_not_found"
    EMPLOYEE_NOT_FOUND = "employee_not_found"
    MESSAGE_NOT_FOUND = "message_not_found"
    QUESTION_NOT_FOUND = "question_not_found"
    MODE_NOT_FOUND = "mode_not_found"
    UNKNOWN_MODE = "unknown_mode"
    RESEARCH_TOPIC_REQUIRED = "research_topic_required"
    INVALID_REPOSITORY = "invalid_repository"
    DUPLICATE_EMPLOYEE_NAME = "duplicate_employee_name"
    UNKNOWN_ROLES = "unknown_roles"
    LEAD_REQUIRED = "lead_required"
    INVALID_ACCOUNT = "invalid_account"
    RESEARCH_HAS_NO_REPOSITORY = "research_has_no_repository"
    DIRECTION_ROOM_IMMUTABLE = "direction_room_immutable"
    DM_IMMUTABLE = "dm_immutable"
    BOSS_DIRECTION_ONLY = "boss_direction_only"
    BOSS_READ_ONLY_ROOM = "boss_read_only_room"
    MEMBERS_NOT_IN_PROJECT = "members_not_in_project"
    EMPLOYEE_OTHER_PROJECT = "employee_other_project"
    DIRECTION_ROOM_RESERVED = "direction_room_reserved"
    CONVERSATION_NOT_IN_ROOM = "conversation_not_in_room"
    INVALID_LANGUAGE = "invalid_language"
    NOT_FOUND = "not_found"


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
