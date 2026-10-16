from fastapi import APIRouter, Depends

from app.auth import verify_token

router = APIRouter(dependencies=[Depends(verify_token)])


@router.post("/items")
def create_item():
    return {}


@router.get("/items")
def list_items():
    return []
