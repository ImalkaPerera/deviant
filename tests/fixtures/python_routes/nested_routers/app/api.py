from fastapi import APIRouter

from app.routes import admin

api_router = APIRouter()
api_router.include_router(admin.router)
