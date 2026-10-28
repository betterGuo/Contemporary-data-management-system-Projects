from fastapi import APIRouter, Depends, Query, Request

from app.api.dependencies import db, require_user
from app.services.statistics_service import statistics
from app.services.survey_service import owned
from app.services.storage_adapters import MAX_PAGE

router = APIRouter(prefix="/api/surveys", tags=["问卷统计"])


@router.get("/{survey_id}/statistics")
def overview(survey_id: str, request: Request, page: int = Query(1, ge=1, le=MAX_PAGE), pageSize: int = Query(20, ge=1, le=100), user=Depends(require_user)):
    survey = owned(db(request), survey_id, user["_id"])
    return {"statistics": statistics(db(request), survey, page=page, page_size=pageSize)}


@router.get("/{survey_id}/questions/{question_id:path}/statistics")
def question(survey_id: str, question_id: str, request: Request, page: int = Query(1, ge=1, le=MAX_PAGE), pageSize: int = Query(20, ge=1, le=100), user=Depends(require_user)):
    survey = owned(db(request), survey_id, user["_id"])
    return {"statistics": statistics(db(request), survey, question_id, page, pageSize)}
