from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse

from app.api.dependencies import db, now, require_user, require_write_user
from app.schemas.requests import Submission
from app.services.response_service import assert_admissible, submit
from app.services.storage_adapters import DomainError
from app.web_utils import survey_dto

router = APIRouter(prefix="/api/participation", tags=["填写问卷"])


@router.get("/{public_id}")
def definition(public_id: str, request: Request, user=Depends(require_user)):
    survey = db(request).surveys.find_one({"publicId": public_id})
    if not survey:
        raise DomainError("NOT_FOUND", "问卷不存在。", [], status_code=404)
    assert_admissible(survey, survey["definitionVersion"], False, now(request))
    return {"survey": survey_dto(survey, now(request), participant=True)}


@router.post("/{public_id}/responses")
def response(public_id: str, payload: Submission, request: Request, user=Depends(require_write_user)):
    result, status = submit(db(request), request.app.state.settings, user, public_id, payload.model_dump(), request.app.state.clock)
    return JSONResponse(result, status_code=status)
