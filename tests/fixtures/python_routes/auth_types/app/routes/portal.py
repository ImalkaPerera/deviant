from fastapi import APIRouter

from app import auth

router = APIRouter()


@router.post("/me/payment")
def add_payment(subject: auth.PortalWrite):
    return {}


@router.post("/public/hook")
def hook(payload: dict):
    return {}
