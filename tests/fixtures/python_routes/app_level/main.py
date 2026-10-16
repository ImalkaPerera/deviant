from fastapi import Depends, FastAPI

from app.auth import require_login

app = FastAPI(dependencies=[Depends(require_login)])


@app.post("/orders")
def create_order():
    return {}
