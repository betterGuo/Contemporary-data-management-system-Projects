from fastapi import APIRouter, Depends, Query, Request

from app.api.dependencies import db, now, require_user, require_write_user
from app.schemas.requests import Revision
from app.schemas.library_requests import (LibraryCreate, WorkingContent, VersionCreate, RestoreVersion, DeriveQuestion, GrantQuestion, VersionAvailability, BookmarkQuestion, RenameTag)
from app.services import library_service as service
from app.services.storage_adapters import MAX_PAGE


router = APIRouter(tags=["题目库与版本"])


@router.get("/api/library-questions")
def listing(request: Request, scope: str = "mine", q: str = Query("", max_length=100), tag: str | None = Query(None, max_length=50), page: int = Query(1, ge=1, le=MAX_PAGE), pageSize: int = Query(20, ge=1, le=100), user=Depends(require_user)):
    return service.listing(db(request), user, scope, q, tag, page, pageSize)


@router.post("/api/library-questions", status_code=201)
def create(payload: LibraryCreate, request: Request, user=Depends(require_write_user)):
    return {"question": service.create(db(request), user, payload.model_dump(), now(request))}


@router.get("/api/library-questions/{question_id}")
def detail(question_id: str, request: Request, user=Depends(require_user)):
    question = service.require_question(db(request), user, question_id)
    return {"question": service.question_dto(db(request), user, question)}


@router.post("/api/library-questions/{question_id}/working-content")
def save_working(question_id: str, payload: WorkingContent, request: Request, user=Depends(require_write_user)):
    return {"question": service.save_working(db(request), user, question_id, payload.model_dump(), now(request))}


@router.get("/api/library-questions/{question_id}/versions")
def versions(question_id: str, request: Request, user=Depends(require_user)):
    return {"versions": service.versions(db(request), user, question_id)}


@router.post("/api/library-questions/{question_id}/versions", status_code=201)
def save_version(question_id: str, payload: VersionCreate, request: Request, user=Depends(require_write_user)):
    return service.save_version(db(request), user, question_id, payload.model_dump(), now(request))


@router.get("/api/library-questions/{question_id}/versions/{version_id}")
def version_detail(question_id: str, version_id: str, request: Request, user=Depends(require_user)):
    question = service.require_question(db(request), user, question_id)
    version = db(request).question_versions.find_one({"_id": service.oid(version_id), "questionId": question["_id"]})
    if not version:
        from app.services.storage_adapters import DomainError
        raise DomainError("NOT_FOUND", "版本不存在。", status_code=404)
    dto = service.version_dto(db(request), version)
    if not dto["selectable"] and not service.manageable(db(request), user, question):
        from app.services.storage_adapters import DomainError
        raise DomainError("NOT_FOUND", "版本已停止提供新增选用，请查看本人问卷中的既有快照。", status_code=404)
    return {"version": dto}


@router.post("/api/library-questions/{question_id}/restore", status_code=201)
def restore(question_id: str, payload: RestoreVersion, request: Request, user=Depends(require_write_user)):
    return service.restore(db(request), user, question_id, payload.model_dump(), now(request))


@router.post("/api/library-questions/{question_id}/derive", status_code=201)
def derive(question_id: str, payload: DeriveQuestion, request: Request, user=Depends(require_write_user)):
    return {"question": service.derive(db(request), user, question_id, payload.model_dump(), now(request))}


@router.post("/api/library-questions/{question_id}/archive")
def archive(question_id: str, payload: Revision, request: Request, user=Depends(require_write_user)):
    return {"question": service.archive(db(request), user, question_id, payload.revision, now(request))}


@router.post("/api/library-questions/{question_id}/versions/{version_id}/availability")
def availability(question_id: str, version_id: str, payload: VersionAvailability, request: Request, user=Depends(require_write_user)):
    return {"version": service.availability(db(request), user, question_id, version_id, payload.model_dump(), now(request))}


@router.get("/api/library-questions/{question_id}/grants")
def grants(question_id: str, request: Request, user=Depends(require_user)):
    return {"grants": service.grants(db(request), user, question_id)}


@router.post("/api/library-questions/{question_id}/grants")
def grant(question_id: str, payload: GrantQuestion, request: Request, user=Depends(require_write_user)):
    return service.grant(db(request), user, question_id, payload.model_dump(), now(request))


@router.delete("/api/library-questions/{question_id}/grants/{grant_id}")
def revoke(question_id: str, grant_id: str, payload: Revision, request: Request, user=Depends(require_write_user)):
    return service.revoke(db(request), user, question_id, grant_id, payload.revision, now(request))


@router.get("/api/library-questions/{question_id}/usage")
def usage(question_id: str, request: Request, versionId: str | None = None, scope: str | None = None, user=Depends(require_user)):
    return {"usage": service.usage(db(request), user, question_id, versionId, scope)}


@router.get("/api/question-bookmarks")
def bookmarks(request: Request, q: str = Query("", max_length=100), tag: str | None = None, page: int = Query(1, ge=1, le=MAX_PAGE), pageSize: int = Query(20, ge=1, le=100), user=Depends(require_user)):
    result = service.listing(db(request), user, "bookmarks", q, tag, page, pageSize)
    result["tags"] = sorted(db(request).question_bookmarks.distinct("tags", {"userId": user["_id"]}))
    return result


@router.post("/api/question-bookmarks")
def bookmark(payload: BookmarkQuestion, request: Request, user=Depends(require_write_user)):
    return {"question": service.bookmark(db(request), user, payload.model_dump(), now(request))}


@router.delete("/api/question-bookmarks/{question_id}")
def remove_bookmark(question_id: str, request: Request, user=Depends(require_write_user)):
    service.remove_bookmark(db(request), user, question_id)
    return {"removed": True}


@router.post("/api/question-tags")
def rename_tag(payload: RenameTag, request: Request, user=Depends(require_write_user)):
    return service.rename_tag(db(request), user, payload.oldTag, payload.newTag)
