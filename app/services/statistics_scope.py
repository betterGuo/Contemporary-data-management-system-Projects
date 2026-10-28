"""The single authorization boundary for cross-questionnaire answer statistics."""


def resolve_statistics_scope(db, user):
    """Return a server-owned survey filter; source sharing never expands it."""
    return {"ownerId": user["_id"]}
