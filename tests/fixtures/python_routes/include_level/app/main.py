from fastapi import Depends, FastAPI

from app.auth import get_current_user
from app.routes import reports

app = FastAPI()
app.include_router(reports.router, dependencies=[Depends(get_current_user)])
