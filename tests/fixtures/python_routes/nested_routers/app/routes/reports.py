from fastapi import APIRouter

router = APIRouter()


@router.post("/reports")
def create_report():
    return {}
