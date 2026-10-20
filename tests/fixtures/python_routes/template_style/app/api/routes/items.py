from fastapi import APIRouter, Depends

from app.api import deps
from app.api.deps import CurrentUser, SessionDep, get_current_active_superuser

router: APIRouter = APIRouter(prefix="/items")


@router.post("/")
def create_item(session: SessionDep, current_user: CurrentUser):
    return {}


@router.delete("/{item_id}", dependencies=[Depends(get_current_active_superuser)])
def delete_item(session: SessionDep, item_id: int):
    return {}


@router.put("/{item_id}")
def update_item(session: SessionDep, current_user: deps.CurrentUser, item_id: int):
    return {}


@router.post("/notes")
def note_item(session: SessionDep):
    return {}
