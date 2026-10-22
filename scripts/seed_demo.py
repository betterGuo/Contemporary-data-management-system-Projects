"""Idempotent fictional demo data, through the same application services."""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.config import Settings
from app.database import connect, initialize_database, utcnow
from app.services import auth_service, response_service, survey_service

DEMO_PASSWORD = "Survey2026!"


def choice(qid, title, labels, *, multiple=False, required=True, validation=None, rules=None):
    return {"id": qid, "type": "multiple" if multiple else "single", "title": title, "required": required, "options": [{"id": key, "label": text} for key, text in labels], "validation": validation or {}, "jumpRules": rules or []}


def statistics_questions():
    return [
        choice("stage", "你的学习阶段", [("A", "本科生"), ("B", "研究生")]),
        choice("places", "你常用的学习场所", [("X", "图书馆"), ("Y", "自习室"), ("Z", "宿舍")], multiple=True, validation={"minSelections": 1, "maxSelections": 3}),
        {"id": "age", "type": "number", "title": "年龄", "required": True, "validation": {"minValue": "0", "maxValue": "120", "integerOnly": True}},
        {"id": "comment", "type": "text", "title": "一句学习建议", "required": True, "validation": {"minLength": 1, "maxLength": 10}},
    ]


def branching_questions():
    return [
        choice("q1", "是否继续参与", [("yes", "是"), ("no", "否")], rules=[{"id": "stop", "operator": "eq", "value": "no", "targetQuestionId": "q6"}]),
        choice("q2", "你感兴趣的领域", [("tech", "技术"), ("art", "艺术"), ("sport", "运动")], multiple=True, validation={"minSelections": 1}, rules=[{"id": "technical", "operator": "containsAny", "value": ["tech"], "targetQuestionId": "q4"}]),
        {"id": "q3", "type": "text", "title": "补充说明", "required": True, "validation": {"minLength": 1}},
        {"id": "q4", "type": "number", "title": "你的年龄", "required": True, "validation": {"minValue": "0", "maxValue": "120", "integerOnly": True}, "jumpRules": [{"id": "minor", "operator": "lt", "value": "18", "targetQuestionId": "q6"}]},
        {"id": "q5", "type": "text", "title": "成年用户的学习建议", "required": True, "validation": {"minLength": 1}},
        choice("q6", "是否确认完成", [("ok", "确认")]),
    ]


def seed(db, settings):
    initialize_database(db)
    users = {}
    for name in ["demo_owner", "demo_student", "student_01", "student_02", "student_03", "student_04"]:
        users[name] = db.users.find_one({"usernameNormalized": name}) or auth_service.register(db, name, DEMO_PASSWORD, utcnow())
    owner = users["demo_owner"]

    def ensure_survey(key, title, questions, **options):
        existing = db.surveys.find_one({"demoKey": key, "ownerId": owner["_id"]})
        if existing:
            return existing
        record = survey_service.create(db, owner["_id"], {"title": title, "description": "课程实验的虚构演示数据，可直接查看并测试。", "allowAnonymous": options.get("anonymous", True), "allowMultipleSubmissions": options.get("multiple", False), "closesAt": None}, utcnow())
        record = survey_service.patch(db, owner["_id"], str(record["_id"]), {"revision": record["revision"], "questions": questions}, utcnow())
        record = survey_service.publish(db, owner["_id"], str(record["_id"]), record["revision"], utcnow())
        db.surveys.update_one({"_id": record["_id"]}, {"$set": {"demoKey": key}})
        return record

    stats = ensure_survey("stats", "学习体验 · 统计验收基准", statistics_questions(), multiple=True)
    rows = [("A", ["X", "Y"], "0", "甲"), ("B", ["Y", "Z"], "40", "乙"), ("A", ["X", "Y", "Z"], "80", "丙"), ("A", ["Y"], "120", "丁")]
    for index, values in enumerate(rows, 1):
        payload = {"definitionVersion": 1, "submissionKey": f"seed-statistics-{index}", "isAnonymous": True, "answers": [{"questionId": qid, "value": value} for qid, value in zip(["stage", "places", "age", "comment"], values)]}
        response_service.submit(db, settings, users[f"student_{index:02d}"], stats["publicId"], payload, utcnow)
    branching = ensure_survey("branching", "校园学习调查 · 条件跳转", branching_questions())
    single = ensure_survey("anonymous-single", "匿名填写与防重复演示", [choice("answer", "你更喜欢哪种学习方式", [("A", "独立学习"), ("B", "小组讨论")])])
    multiple = ensure_survey("multiple", "同人多次填写与人数统计", [choice("answer", "今天选择的学习方式", [("A", "独立学习"), ("B", "小组讨论")])], multiple=True)
    for index, option in enumerate(["A", "B"], 1):
        response_service.submit(db, settings, users["demo_student"], multiple["publicId"], {"definitionVersion": 1, "submissionKey": f"seed-repeat-{index}", "isAnonymous": True, "answers": [{"questionId": "answer", "value": option}]}, utcnow)
    return {"statistics": stats, "branching": branching, "anonymousSingle": single, "multiple": multiple}


if __name__ == "__main__":
    settings = Settings()
    with connect(settings.mongodb_uri) as client:
        surveys = seed(client[settings.mongodb_db], settings)
        for label, survey in surveys.items():
            print(f"{label}: /survey/{survey['publicId']} | manage /surveys/{survey['_id']}/edit")
    print(f"Fictional demo logins: demo_owner / demo_student; password: {DEMO_PASSWORD}")
