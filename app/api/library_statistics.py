from fastapi import APIRouter, Depends, Query, Request

from app.api.dependencies import db, require_user
from app.services.cross_survey_statistics import cross_statistics
from app.services.storage_adapters import MAX_PAGE

router = APIRouter(prefix="/api/library-questions", tags=["跨问卷统计"])


@router.get("/{question_id}/statistics")
def cross_question_statistics(question_id: str, request: Request, versionId: str,
                              page: int = Query(1, ge=1, le=MAX_PAGE), pageSize: int = Query(20, ge=1, le=100),
                              user=Depends(require_user)):
    return {"statistics": cross_statistics(db(request), user, question_id, versionId, page, pageSize)}
