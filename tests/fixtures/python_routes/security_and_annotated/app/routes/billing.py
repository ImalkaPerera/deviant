from typing import Annotated

from fastapi import APIRouter, Depends, Security

from app.auth import get_current_user, verify_scope

router = APIRouter()


@router.post("/invoices")
def create_invoice(user: Annotated[dict, Depends(get_current_user)]):
    return {}


@router.patch("/invoices/{invoice_id}")
def patch_invoice(invoice_id: int, scope=Security(verify_scope)):
    return {}
