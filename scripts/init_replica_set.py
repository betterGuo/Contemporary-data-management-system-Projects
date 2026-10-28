"""Initialize or verify the project-only local replica set, without dropping data."""
from time import monotonic, sleep
from pymongo import MongoClient
from pymongo.errors import OperationFailure, PyMongoError


def main():
    client = MongoClient("mongodb://localhost:27018/?directConnection=true", serverSelectionTimeoutMS=3000)
    try:
        status = client.admin.command("replSetGetStatus")
        if status.get("set") != "survey-rs":
            raise RuntimeError("27018已属于其他副本集，拒绝更改。")
    except OperationFailure as error:
        if error.code != 94:
            raise
        client.admin.command({"replSetInitiate": {"_id": "survey-rs", "members": [{"_id": 0, "host": "localhost:27018"}]}})
    deadline = monotonic()+30
    while monotonic() < deadline:
        if client.admin.command("hello").get("isWritablePrimary"):
            print("survey-rs ready at mongodb://localhost:27018/?replicaSet=survey-rs")
            client.close()
            return
        sleep(0.25)
    raise RuntimeError("副本集尚未选出主节点，请检查容器日志后重试。")


if __name__ == "__main__":
    main()
