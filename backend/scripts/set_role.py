r"""Give an existing account a role from the server's command line (needed once, to make the first owner on an installation that already
had users before roles existed). New installations need nothing: the very first account that signs up becomes the owner.

    cd backend
    .venv\Scripts\python scripts\set_role.py list
    .venv\Scripts\python scripts\set_role.py you@example.com developer --owner
    .venv\Scripts\python scripts\set_role.py someone@example.com admin
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import select  # noqa: E402

from app.admin import audit  # noqa: E402
from app.database.session import SessionLocal, ensure_columns  # noqa: E402
from app.models import User  # noqa: E402


def main(argv: list[str]) -> int:
    ensure_columns()
    with SessionLocal() as db:
        if not argv or argv[0] == "list":
            for u in db.scalars(select(User).order_by(User.id)):
                print(f"{u.id:>4}  {u.email:<40} {u.role:<10} {'owner' if u.is_owner else ''} {'' if u.is_active else 'DISABLED'}")
            return 0
        if len(argv) < 2 or argv[1] not in ("user", "admin", "developer"):
            print(__doc__)
            return 2
        u = db.scalar(select(User).where(User.email == argv[0].lower()))
        if not u:
            print(f"no account with email {argv[0]}")
            return 1
        before = u.role
        u.role, u.is_active = argv[1], True
        if "--owner" in argv:
            if argv[1] != "developer":
                print("--owner needs the developer role")
                return 2
            for other in db.scalars(select(User).where(User.is_owner.is_(True), User.id != u.id)):
                other.is_owner = False
            u.is_owner = True
        db.commit()
        audit.record("user.role_cli", None, f"user:{u.id}", {"role": [before, u.role], "owner": u.is_owner, "via": "set_role.py"})
        print(f"{u.email}: {before} -> {u.role}{' (owner)' if u.is_owner else ''}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
