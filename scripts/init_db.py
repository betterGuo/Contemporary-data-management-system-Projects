from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.config import Settings
from app.database import connect, initialize_database

if __name__ == "__main__":
    settings = Settings()
    with connect(settings.mongodb_uri) as client:
        initialize_database(client[settings.mongodb_db])
        print(f"Initialized {settings.mongodb_db}; existing records preserved.")
