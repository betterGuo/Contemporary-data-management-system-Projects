from app.services.storage_adapters import DomainError, from_storage_survey


def load_definition(db, survey_id, definition_version):
    """Single version today; immutable historical versions can be added without changing callers."""
    survey = db.surveys.find_one({"_id": survey_id})
    if survey and survey.get("definitionVersion", 1) == definition_version:
        return from_storage_survey(survey)
    historical = db.survey_versions.find_one({"surveyId": survey_id, "definitionVersion": definition_version})
    if historical:
        return from_storage_survey(historical)
    raise DomainError("DEFINITION_VERSION_UNAVAILABLE", "该问卷版本不存在，请重新打开问卷。", [], status_code=409)
