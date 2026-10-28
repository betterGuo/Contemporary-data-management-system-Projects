from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.services.storage_adapters import MAX_BSON_INT64


class StrictRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    @model_validator(mode="before")
    @classmethod
    def require_valid_unicode(cls, value):
        # JSON can represent lone surrogate escapes, but UTF-8/BSON cannot.
        # Validate even generic nested question/answer fields before errors or
        # database commands can accidentally echo/encode those characters.
        def check(item):
            if isinstance(item, str):
                try:
                    item.encode("utf-8")
                except UnicodeError as error:
                    raise ValueError("输入包含无法保存的Unicode字符。") from error
            elif isinstance(item, dict):
                for key, child in item.items():
                    check(key)
                    check(child)
            elif isinstance(item, list):
                for child in item:
                    check(child)
        check(value)
        return value


class Credentials(StrictRequest):
    username: str
    password: str


class SurveyCreate(StrictRequest):
    title: str
    description: str = ""
    allowAnonymous: bool = False
    allowMultipleSubmissions: bool = False
    closesAt: str | None = None


class SurveyPatch(StrictRequest):
    revision: int = Field(ge=1, le=MAX_BSON_INT64)
    title: str | None = None
    description: str | None = None
    allowAnonymous: bool | None = None
    allowMultipleSubmissions: bool | None = None
    closesAt: str | None = None
    questions: list[dict[str, Any]] | None = None


class Revision(StrictRequest):
    revision: int = Field(ge=1, le=MAX_BSON_INT64)


class QuestionWrite(Revision):
    question: dict[str, Any]


class QuestionOrder(Revision):
    questionIds: list[str]


class Answer(StrictRequest):
    questionId: str
    value: Any


class Submission(StrictRequest):
    definitionVersion: int = Field(ge=1, le=MAX_BSON_INT64)
    submissionKey: str = Field(min_length=1, max_length=128)
    isAnonymous: bool = False
    answers: list[Answer]
