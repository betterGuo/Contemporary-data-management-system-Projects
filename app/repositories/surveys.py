from pymongo import ReturnDocument

from app.services.storage_adapters import from_storage_survey


def by_owner(db, survey_id, user_id):
    record = db.surveys.find_one({"_id": survey_id, "ownerId": user_id})
    return from_storage_survey(record) if record is not None else None


def update_draft(db, survey_id, user_id, revision, changes):
    return db.surveys.find_one_and_update(
        {"_id": survey_id, "ownerId": user_id, "status": "draft", "revision": revision},
        {"$set": changes, "$inc": {"revision": 1}},
        return_document=ReturnDocument.AFTER,
    )
