from fastapi import APIRouter, Depends, Query, Request
from pymongo import ReturnDocument

from app.api.dependencies import db, now, require_user, require_write_user
from app.schemas.requests import QuestionOrder, QuestionWrite, Revision, SurveyCreate, SurveyPatch
from app.services import survey_service
from app.services.storage_adapters import DomainError, MAX_PAGE
from app.web_utils import survey_dto

router = APIRouter(prefix="/api/surveys", tags=["问卷管理"])


def output(request, record):
    return {"survey": survey_dto(record, now(request))}


@router.post("", status_code=201)
def create(payload: SurveyCreate, request: Request, user=Depends(require_write_user)):
    return output(request, survey_service.create(db(request), user["_id"], payload.model_dump(), now(request)))


@router.get("")
def listing(request: Request, page: int = Query(1, ge=1, le=MAX_PAGE), pageSize: int = Query(20, ge=1, le=100), user=Depends(require_user)):
    collection = db(request).surveys
    query = {"ownerId": user["_id"]}
    rows = collection.find(query).sort([("createdAt", -1), ("_id", -1)]).skip((page-1)*pageSize).limit(pageSize)
    return {"surveys": [survey_dto(row, now(request)) for row in rows], "total": collection.count_documents(query), "page": page, "pageSize": pageSize}


@router.get("/{survey_id}")
def get(survey_id: str, request: Request, user=Depends(require_user)):
    return output(request, survey_service.owned(db(request), survey_id, user["_id"]))


@router.patch("/{survey_id}")
def update(survey_id: str, payload: SurveyPatch, request: Request, user=Depends(require_write_user)):
    return output(request, survey_service.patch(db(request), user["_id"], survey_id, payload.model_dump(exclude_unset=True), now(request), request.app.state.settings.max_definition_bytes))


@router.post("/{survey_id}/questions", status_code=201)
def add_question(survey_id: str, payload: QuestionWrite, request: Request, user=Depends(require_write_user)):
    survey = survey_service.owned(db(request), survey_id, user["_id"])
    return output(request, survey_service.patch(db(request), user["_id"], survey_id, {"revision": payload.revision, "questions": survey["questions"]+[payload.question]}, now(request)))


@router.patch("/{survey_id}/questions/{question_id:path}")
def edit_question(survey_id: str, question_id: str, payload: QuestionWrite, request: Request, user=Depends(require_write_user)):
    survey = survey_service.owned(db(request), survey_id, user["_id"])
    if not any(q["id"] == question_id for q in survey["questions"]):
        raise DomainError("NOT_FOUND", "题目不存在。", [], status_code=404)
    if payload.question.get("id", question_id) != question_id:
        raise DomainError("STABLE_ID_REQUIRED", "题目 ID 不能修改。", [])
    question = {**payload.question, "id": question_id}
    questions = [question if q["id"] == question_id else q for q in survey["questions"]]
    return output(request, survey_service.patch(db(request), user["_id"], survey_id, {"revision": payload.revision, "questions": questions}, now(request)))


@router.delete("/{survey_id}/questions/{question_id:path}")
def delete_question(survey_id: str, question_id: str, payload: Revision, request: Request, user=Depends(require_write_user)):
    survey = survey_service.owned(db(request), survey_id, user["_id"])
    questions = [q for q in survey["questions"] if q["id"] != question_id]
    if len(questions) == len(survey["questions"]):
        raise DomainError("NOT_FOUND", "题目不存在。", [], status_code=404)
    return output(request, survey_service.patch(db(request), user["_id"], survey_id, {"revision": payload.revision, "questions": questions}, now(request)))


@router.put("/{survey_id}/question-order")
def reorder(survey_id: str, payload: QuestionOrder, request: Request, user=Depends(require_write_user)):
    survey = survey_service.owned(db(request), survey_id, user["_id"])
    existing = {q["id"]: q for q in survey["questions"]}
    if len(payload.questionIds) != len(existing) or set(payload.questionIds) != set(existing):
        raise DomainError("INVALID_ORDER", "顺序必须完整且不重复地包含全部题目 ID。", [])
    return output(request, survey_service.patch(db(request), user["_id"], survey_id, {"revision": payload.revision, "questions": [existing[qid] for qid in payload.questionIds]}, now(request)))


@router.post("/{survey_id}/publish")
def publish(survey_id: str, payload: Revision, request: Request, user=Depends(require_write_user)):
    return output(request, survey_service.publish(db(request), user["_id"], survey_id, payload.revision, now(request)))


@router.post("/{survey_id}/close")
def close(survey_id: str, request: Request, user=Depends(require_write_user)):
    survey = survey_service.owned(db(request), survey_id, user["_id"])
    if survey["status"] == "closed":
        return output(request, survey)
    if survey["status"] != "published":
        raise DomainError("INVALID_STATE", "只有已发布问卷可以关闭。", [], status_code=409)
    result = db(request).surveys.find_one_and_update({"_id": survey["_id"], "ownerId": user["_id"], "status": "published"}, {"$set": {"status": "closed", "closedAt": now(request), "updatedAt": now(request)}}, return_document=ReturnDocument.AFTER)
    return output(request, result or survey_service.owned(db(request), survey_id, user["_id"]))


@router.get("/{survey_id}/preview")
def preview(survey_id: str, request: Request, user=Depends(require_user)):
    survey = survey_service.owned(db(request), survey_id, user["_id"])
    return {**output(request, survey), "isPreview": True}
