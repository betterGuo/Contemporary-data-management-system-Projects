"""Grant or revoke library-admin privileges for an explicitly named account."""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.config import Settings
from app.database import connect, utcnow


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--username", required=True)
    parser.add_argument("--revoke", action="store_true")
    args = parser.parse_args()
    settings = Settings()
    with connect(settings.mongodb_uri) as client:
        db = client[settings.mongodb_db]
        user = db.users.find_one({"username": args.username})
        if user is None:
            raise ValueError("指定账号不存在，请先通过注册建立该账号。")
        role = "user" if args.revoke else "admin"
        db.users.update_one({"_id": user["_id"]}, {"$set": {"role": role}})
        db.admin_audit.insert_one({"actor": "local-admin-command", "targetUserId": user["_id"], "role": role, "createdAt": utcnow()})
        print(json.dumps({"username": args.username, "role": role, "status": "updated"}, ensure_ascii=False))


if __name__ == "__main__":
    main()
