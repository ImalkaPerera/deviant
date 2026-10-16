from fastapi import APIRouter

router = APIRouter()


@router.put("/reports/{report_id}")
def update_report(report_id: int):
    return {}


@router.get("/reports")
def list_reports():
    return []
