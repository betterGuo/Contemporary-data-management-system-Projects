"""The initial migration uses the same idempotent initializer as application startup."""
from app.database import initialize_database


def apply(db):
    initialize_database(db)
