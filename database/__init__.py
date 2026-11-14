# Central database exports.
# Allows both "from database import db" and the existing
# "from database.users_chats_db import db" imports.
from .users_chats_db import db, db2

__all__ = ["db", "db2"]
