from fastapi import Depends, FastAPI

from app.api import api_router
from app.auth import verify_token


def create_app():
    application = FastAPI()
    application.include_router(api_router, dependencies=[Depends(verify_token)])
    return application
