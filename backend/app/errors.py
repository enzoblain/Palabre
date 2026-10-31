"""Stable error codes shared by the domain layers and the REST API."""

from enum import StrEnum


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
    INVALID_TEAM_PERMISSIONS = "invalid_team_permissions"
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
    INVALID_PERSONALITY = "invalid_personality"
    UNKNOWN_PERSONALITY = "unknown_personality"
    INVALID_BRANCH_NAME = "invalid_branch_name"
    BRANCH_ALREADY_USED = "branch_already_used"
    NO_NAME_LEFT = "no_name_left"
    TASK_WRONG_STATUS = "task_wrong_status"
    TASK_NOT_YOURS = "task_not_yours"
    TASK_WAITING_FOR_DEPENDENCIES = "task_waiting_for_dependencies"
    TASK_NO_BRANCH = "task_no_branch"
    TASK_NO_PULL_REQUEST = "task_no_pull_request"
    INVALID_PR_TITLE = "invalid_pr_title"
    CANNOT_REVIEW_OWN_TASK = "cannot_review_own_task"
    MERGE_BLOCKED = "merge_blocked"
    NO_COMMITS = "no_commits"
    GITHUB_NOT_CONFIGURED = "github_not_configured"
    INVALID_GITHUB_URL = "invalid_github_url"
    GITHUB_BRANCH_MISSING = "github_branch_missing"
    PRODUCTION_BRANCH_BOSS_ONLY = "production_branch_boss_only"


class WorkflowError(Exception):
    """A rule of the company was not respected; the message is shown to the agent.
    `code` names it for the API (falls back to the generic `workflow_error`)."""

    def __init__(self, *args: object, code: ErrorCode | None = None):
        super().__init__(*args)
        self.code = code or ErrorCode.WORKFLOW_ERROR


class NothingToRelease(WorkflowError):
    """No commit since the last tag deserves a version."""
