"""Create the local secret once; never replace an existing environment."""
from pathlib import Path
import secrets

root = Path(__file__).resolve().parents[1]
target = root / ".env"
if target.exists():
    print(".env already exists; preserved.")
else:
    target.write_text((root / ".env.example").read_text().replace("replace-with-a-persistent-random-secret-at-least-32-characters", secrets.token_hex(32)))
    target.chmod(0o600)
    print("Created .env with a persistent random secret.")
