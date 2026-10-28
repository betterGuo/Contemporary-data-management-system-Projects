"""Optional fictional stage-two examples. Never replaces existing users or data."""
import argparse
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.config import Settings
from app.database import connect, initialize_database, utcnow
from app.services import auth_service, library_service as library, question_reference_service as bindings, survey_service, response_service

PASSWORD = "Survey2026!"


def seed(db, settings, *, include_admin_demo=False):
    if not include_admin_demo:
        raise ValueError("公共演示需要明确指定 --include-admin-demo，仅对新建的专用虚构账号授予管理权。")
    initialize_database(db)
    users = {}
    for name in ("stage2_owner", "stage2_peer", "stage2_admin"):
        existing = db.users.find_one({"usernameNormalized": name})
        if existing and not existing.get("stage2DemoAccount"):
            raise ValueError("演示用户名已被真实用户使用，拒绝覆盖或提权。")
        if existing is None:
            existing = auth_service.register(db, name, PASSWORD, utcnow())
            db.users.update_one({"_id": existing["_id"]}, {"$set": {"stage2DemoAccount": True}})
        users[name] = existing
    admin = users["stage2_admin"]
    if admin.get("role") != "admin":
        db.users.update_one({"_id": admin["_id"], "stage2DemoAccount": True}, {"$set": {"role": "admin"}})
        db.admin_audit.insert_one({"actor": "explicit-stage2-demo-command", "targetUserId": admin["_id"], "role": "admin", "createdAt": utcnow()})
    admin = db.users.find_one({"_id": admin["_id"]})
    owner, peer = users["stage2_owner"], users["stage2_peer"]

    def ensure_question(key, actor, value, visibility):
        existing = db.questions.find_one({"stage2DemoKey": key})
        if existing:
            return existing
        def work(session):
            q = library.new_question(db, actor, value, utcnow(), session, visibility=visibility, formal=True)
            db.questions.update_one({"_id": q["_id"]}, {"$set": {"stage2DemoKey": key}}, session=session)
            return q
        return library.transaction(db, work)

    age = ensure_question("public-age", admin, {"type": "number", "title": "公共示例：你的年龄（周岁）", "required": True,
        "validation": {"integerOnly": True, "minValue": "0", "maxValue": "120"}}, "public")
    intent = ensure_question("shared-intent", owner, {"type": "single", "title": "共享示例：你是否愿意参加课程讨论", "required": True,
        "options": [{"id": "yes", "label": "愿意"}, {"id": "no", "label": "暂不参加"}]}, "private")
    if not db.question_grants.find_one({"questionId": intent["_id"], "granteeId": peer["_id"], "active": True}):
        current = db.questions.find_one({"_id": intent["_id"]})
        library.grant(db, owner, intent["_id"], {"revision": current["revision"], "username": peer["username"]}, utcnow())
    surveys = []
    for key, title in (("example-a", "第二阶段示例 · 问卷甲"), ("example-b", "第二阶段示例 · 问卷乙")):
        survey = db.surveys.find_one({"stage2DemoKey": key, "ownerId": owner["_id"]})
        if survey is None:
            survey = survey_service.create(db, owner["_id"], {"title": title, "description": "虚构样例：两卷复用同一题目版本，年龄0/20/40，合并均值20。", "allowAnonymous": True, "allowMultipleSubmissions": True, "closesAt": None}, utcnow())
            for question in (age, intent):
                survey = bindings.select(db, owner, survey["_id"], {"revision": survey["revision"], "versionId": str(question["latestVersionId"]), "requestKey": "demo:"+key+":"+str(question["_id"])}, utcnow())
            survey = survey_service.publish(db, owner["_id"], str(survey["_id"]), survey["revision"], utcnow())
            db.surveys.update_one({"_id": survey["_id"]}, {"$set": {"stage2DemoKey": key}})
        surveys.append(survey)
    for index, (survey, actor, number, answer) in enumerate(((surveys[0], peer, "0", "yes"), (surveys[0], owner, "20", "no"), (surveys[1], peer, "40", "yes"))):
        response_service.submit(db, settings, actor, survey["publicId"], {"definitionVersion": survey["definitionVersion"], "submissionKey": f"stage2-demo-{index}", "isAnonymous": True,
            "answers": [{"questionId": survey["questions"][0]["id"], "value": number}, {"questionId": survey["questions"][1]["id"], "value": answer}]}, utcnow)
    return {"accounts": list(users), "surveys": [str(s["_id"]) for s in surveys], "publicAgeQuestion": str(age["_id"]), "publicAgeVersion": str(age["latestVersionId"])}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--include-admin-demo", action="store_true")
    args = parser.parse_args()
    settings = Settings()
    with connect(settings.mongodb_uri) as client:
        print(seed(client[settings.mongodb_db], settings, include_admin_demo=args.include_admin_demo))
    print("Fictional demonstration password: Survey2026!")
