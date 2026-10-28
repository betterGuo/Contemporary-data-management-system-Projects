from typing import Any

from fastapi import APIRouter, Depends, Request
from pydantic import Field

from app.api.dependencies import db, now, require_write_user
from app.schemas.requests import StrictRequest, Revision
from app.services import question_reference_service as bindings
from app.web_utils import json_value, survey_dto
from app.services.storage_adapters import MAX_BSON_INT64

router = APIRouter(tags=["问卷题目复用"])


class SelectVersion(Revision):
    versionId: str
    requestKey: str = Field(min_length=1, max_length=128)


class UpgradeVersion(SelectVersion):
    instanceId: str


class SaveInstance(Revision):
    instanceId: str
    requestKey: str = Field(min_length=1, max_length=128)


class SnapshotSource(StrictRequest):
    surveyId: str
    definitionVersion: int = Field(ge=1, le=MAX_BSON_INT64)
    instanceId: str


class DeriveBatch(StrictRequest):
    instances: list[SnapshotSource] = Field(min_length=1, max_length=5)
    requestKey: str = Field(min_length=1, max_length=128)


@router.post("/api/library-questions/derive-batch", status_code=201)
def batch(payload: DeriveBatch, request: Request, user=Depends(require_write_user)):
    return json_value(bindings.derive_batch(db(request), user, payload.model_dump(), now(request)))


@router.post("/api/surveys/{survey_id}/library-instances", status_code=201)
def select(survey_id: str, payload: SelectVersion, request: Request, user=Depends(require_write_user)):
    return {"survey": survey_dto(bindings.select(db(request), user, survey_id, payload.model_dump(), now(request)), now(request))}


@router.post("/api/surveys/{survey_id}/library-instances/save")
def save(survey_id: str, payload: SaveInstance, request: Request, user=Depends(require_write_user)):
    return {"survey": survey_dto(bindings.save_instance(db(request), user, survey_id, payload.model_dump(), now(request)), now(request))}


@router.post("/api/surveys/{survey_id}/library-instances/upgrade")
def upgrade(survey_id: str, payload: UpgradeVersion, request: Request, user=Depends(require_write_user)):
    return {"survey": survey_dto(bindings.upgrade(db(request), user, survey_id, payload.model_dump(), now(request)), now(request))}
