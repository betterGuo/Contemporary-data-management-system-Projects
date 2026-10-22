from datetime import datetime

from bson import ObjectId
from bson.decimal128 import Decimal128

from app.services.survey_service import effective_status
from app.services.storage_adapters import from_storage_survey


def json_value(value):
    if isinstance(value, ObjectId):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, Decimal128):
        return str(value.to_decimal())
    if isinstance(value, dict):
        return {k: json_value(v) for k, v in value.items()}
    if isinstance(value, list):
        return [json_value(v) for v in value]
    return value


def survey_dto(survey, now, participant=False):
    survey = from_storage_survey(survey)
    fields = ["publicId", "title", "description", "allowAnonymous", "allowMultipleSubmissions", "status", "closesAt", "revision", "definitionVersion", "questions", "createdAt", "updatedAt", "publishedAt", "closedAt"]
    result = {k: json_value(survey.get(k)) for k in fields}
    result["id"] = str(survey["_id"])
    result["effectiveStatus"] = effective_status(survey, now)
    if participant:
        for field in ["revision", "createdAt", "updatedAt", "closedAt"]:
            result.pop(field, None)
    return result
