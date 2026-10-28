from typing import Any, Literal

from pydantic import Field

from app.schemas.requests import StrictRequest, Revision


class LibraryCreate(StrictRequest):
    content: dict[str, Any]
    visibility: Literal["private", "public"] = "private"
    requestKey: str = Field(min_length=1, max_length=128)


class WorkingContent(Revision):
    content: dict[str, Any]


class VersionCreate(WorkingContent):
    sourceVersionId: str | None = None
    requestKey: str = Field(min_length=1, max_length=128)
    reason: str = Field(default="", max_length=2000)


class RestoreVersion(Revision):
    versionId: str
    requestKey: str = Field(min_length=1, max_length=128)


class DeriveQuestion(StrictRequest):
    versionId: str
    content: dict[str, Any] | None = None
    requestKey: str = Field(min_length=1, max_length=128)


class GrantQuestion(Revision):
    username: str = Field(min_length=1, max_length=100)


class VersionAvailability(Revision):
    selectable: bool


class BookmarkQuestion(StrictRequest):
    questionId: str
    versionId: str | None = None
    tags: list[str] = Field(default_factory=list, max_length=20)


class RenameTag(StrictRequest):
    oldTag: str = Field(min_length=1, max_length=50)
    newTag: str | None = Field(default=None, max_length=50)
