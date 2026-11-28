"""Roles are cumulative: developer > admin > user. Who may act on whom:
  * admins create users; developers create admins; only the owner (the first developer) creates developers;
  * you act only on people ranked below you (the owner also on other developers);
  * nobody disables, removes, demotes or signs out themselves, and the last developer cannot be removed or demoted;
  * "view as" is read-only and secrets (passwords, keys) are never shown."""
from __future__ import annotations

from fastapi import Depends, HTTPException

from app.api.deps import current_user
from app.models import User

RANK = {"user": 0, "admin": 1, "developer": 2}
PERMISSIONS = [
    ("session.self", "user"), ("users.read", "admin"), ("users.create", "admin"), ("users.manage", "admin"), ("users.view_as", "admin"),
    ("audit.read", "admin"), ("announcements.manage", "admin"), ("calendar.manage", "admin"),
    ("system.read", "developer"), ("system.manage", "developer"),
]


def rank(user: User) -> int:
    return RANK.get(user.role or "user", 0)


def require(role: str):
    def dep(user: User = Depends(current_user)) -> User:
        if rank(user) < RANK[role]:
            raise HTTPException(403, f"{role.capitalize()} access required")
        if getattr(user, "_read_only", False):
            raise HTTPException(403, "Not available while viewing as another user")
        return user
    return dep


def can_assign(actor: User, role: str) -> bool:
    if role == "developer":
        return bool(actor.is_owner)
    return rank(actor) > RANK[role]


def can_manage(actor: User, target: User) -> bool:
    if actor.id == target.id:
        return False
    return rank(actor) > rank(target) or (bool(actor.is_owner) and not target.is_owner)


def matrix() -> list[dict]:
    return [{"permission": p, **{r: RANK[r] >= RANK[need] for r in RANK}} for p, need in PERMISSIONS]


RULES = [
    "Roles are cumulative: developer includes admin, admin includes user.",
    "Admins create users; developers create admins; only the owner (the first developer) creates developers.",
    "Nobody can disable, remove, demote or sign out themselves, and the last developer cannot be removed or demoted.",
    "'View as' is read-only and sees only people ranked below the viewer; passwords and keys are never shown.",
]
