from fastapi import APIRouter, Depends

from app.db import get_db
from app.limits import rate_limiter

router = APIRouter()


@router.post("/feedback", dependencies=[Depends(rate_limiter)])
def send_feedback(db=Depends(get_db)):
    return {}


@router.get("/stats")
def health():
    return {"ok": True}
