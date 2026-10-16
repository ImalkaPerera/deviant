from fastapi import APIRouter, Depends

from app.auth import get_current_user, get_db

router = APIRouter()


@router.get("/users")
def list_users(db=Depends(get_db)):
    return []


@router.post("/users", response_model=dict)
def create_user(db=Depends(get_db), user=Depends(get_current_user)):
    return {}


@router.delete("/users/{user_id}")
def delete_user(user_id: int):
    return {}
