from fastapi import Depends, FastAPI

from app.auth import require_login
from app.routes import reports

app = FastAPI(dependencies=[Depends(require_login)])
app.include_router(reports.router)
