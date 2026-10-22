from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class StrictRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


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
    revision: int = Field(ge=1)
    title: str | None = None
    description: str | None = None
    allowAnonymous: bool | None = None
    allowMultipleSubmissions: bool | None = None
    closesAt: str | None = None
    questions: list[dict[str, Any]] | None = None


class Revision(StrictRequest):
    revision: int = Field(ge=1)


class QuestionWrite(Revision):
    question: dict[str, Any]


class QuestionOrder(Revision):
    questionIds: list[str]


class Answer(StrictRequest):
    questionId: str
    value: Any


class Submission(StrictRequest):
    definitionVersion: int = Field(ge=1)
    submissionKey: str = Field(min_length=1, max_length=128)
    isAnonymous: bool = False
    answers: list[Answer]
