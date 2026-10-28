from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app import workflow
from app.api.deps import SessionDep, get_or_404
from app.api.schemas import MergeIn, ReviewOut, TaskDetail, TaskIn, TaskOut, TaskPatch
from app.models import Conversation, Project, Review, Room, Task, TaskStatus

router = APIRouter(tags=["tasks"])


async def load_task(s, task_id: int) -> Task:
    task = await s.scalar(select(Task).where(Task.id == task_id).options(selectinload(Task.assignee)))
    if task is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Task {task_id} not found")
    return task


async def task_detail(s, task: Task) -> TaskDetail:
    reviews = await s.scalars(
        select(Review).where(Review.task_id == task.id).options(selectinload(Review.reviewer)).order_by(Review.id)
    )
    return TaskDetail.model_validate(
        {
            **TaskOut.model_validate(task).model_dump(),
            "description": task.description,
            "acceptance_criteria": task.acceptance_criteria,
            "depends_on": task.depends_on,
            "branch": task.branch,
            "reviews": [ReviewOut.model_validate(r) for r in reviews],
        }
    )


@router.get("/projects/{project_id}/tasks", response_model=list[TaskOut])
async def list_tasks(project_id: int, s: SessionDep, status: TaskStatus | None = None, room_id: int | None = None):
    await get_or_404(s, Project, project_id)
    q = select(Task).where(Task.project_id == project_id).options(selectinload(Task.assignee))
    if status is not None:
        q = q.where(Task.status == status)
    if room_id is not None:
        q = q.where(Task.room_id == room_id)
    return list(await s.scalars(q.order_by(Task.id)))


@router.post("/rooms/{room_id}/tasks", response_model=TaskDetail, status_code=status.HTTP_201_CREATED)
async def create_task(room_id: int, body: TaskIn, s: SessionDep):
    """Create a task as the boss; the assignee (first name) is woken up."""
    room = await get_or_404(s, Room, room_id)
    conversation_id = body.conversation_id or await s.scalar(
        select(Conversation.id).where(Conversation.room_id == room_id).order_by(Conversation.id.desc()).limit(1)
    )
    conversation = await s.get(Conversation, conversation_id) if conversation_id else None
    if conversation is None or conversation.room_id != room_id:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "The room has no such conversation")
    task = await workflow.create_task(
        s,
        project_id=room.project_id,
        room_id=room_id,
        conversation_id=conversation.id,
        author=None,
        title=body.title,
        description=body.description,
        acceptance_criteria=body.acceptance_criteria,
        assignee=body.assignee,
        depends_on=body.depends_on,
    )
    return await task_detail(s, task)


@router.post("/tasks/cleanup")
async def clean_up_finished_tasks(s: SessionDep) -> dict:
    """Close the open PRs and delete the branches of every done or cancelled task. Idempotent."""
    return {"tasks_visited": await workflow.clean_up_finished_tasks(s)}


@router.get("/tasks/{task_id}", response_model=TaskDetail)
async def get_task(task_id: int, s: SessionDep):
    return await task_detail(s, await load_task(s, task_id))


@router.patch("/tasks/{task_id}", response_model=TaskDetail)
async def update_task(task_id: int, body: TaskPatch, s: SessionDep):
    task = await load_task(s, task_id)
    fields = body.model_dump(exclude_unset=True)
    assignee = fields.pop("assignee", None)
    if fields:
        await workflow.update_task(
            s,
            task.project_id,
            task.id,
            **{k: fields.get(k) for k in ("title", "description", "acceptance_criteria", "depends_on", "status")},
        )
    if assignee:
        await workflow.assign_task(s, task.project_id, task.id, assignee)
    s.expire_all()
    return await task_detail(s, await load_task(s, task_id))


@router.get("/tasks/{task_id}/merge-blockers")
async def merge_blockers(task_id: int, s: SessionDep) -> dict:
    """What still prevents merging, under the company's mode."""
    task = await load_task(s, task_id)
    if task.status != TaskStatus.review:
        return {"task_id": task.id, "status": task.status.value, "blockers": [f"task is {task.status.value}"]}
    project = await get_or_404(s, Project, task.project_id)
    return {"task_id": task.id, "status": task.status.value, "blockers": await workflow.merge_blockers(s, project, task)}


@router.post("/tasks/{task_id}/merge", response_model=TaskDetail)
async def merge(task_id: int, body: MergeIn, s: SessionDep):
    """Merge as the boss; `force` skips the mode's merge rules."""
    task = await load_task(s, task_id)
    await workflow.merge_task(s, task.project_id, task.id, None, force=body.force)
    s.expire_all()
    return await task_detail(s, await load_task(s, task_id))
