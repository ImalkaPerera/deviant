from typing import Annotated

from fastapi import Depends
from fastapi.security import OAuth2PasswordBearer

reusable_oauth2 = OAuth2PasswordBearer(tokenUrl="/login")
TokenDep = Annotated[str, Depends(reusable_oauth2)]


def get_db():
    yield None


SessionDep = Annotated[object, Depends(get_db)]


def get_current_user(token: TokenDep):
    return token


CurrentUser = Annotated[dict, Depends(get_current_user)]


def get_current_active_superuser(current_user: CurrentUser):
    return current_user
