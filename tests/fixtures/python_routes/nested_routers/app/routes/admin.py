from fastapi import APIRouter

router = APIRouter()


@router.put("/settings")
def update_settings():
    return {}
