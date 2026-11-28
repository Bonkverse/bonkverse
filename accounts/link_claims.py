"""What every sign-in claim shares (the LinkClaim table): the claim length,
the per-name limit, how names are checked, and the error a claim raises.

Room codes (room_claims.py, ADR 0026) are the only claims made now.
Friend-request claims (ADR 0024) were removed on 2026-11-27: a friend
request can't show who started the claim it proves, and room codes do the
same job without that weakness. Old rows stay in the table as history.
"""

from __future__ import annotations

CLAIM_MINUTES = 10
NAME_MAX_LENGTH = 64
# Claims for one name per hour, so nobody can keep a name busy.
CLAIMS_PER_NAME_PER_HOUR = 4

# Shown when an old friend-request link or waiting page is opened.
FRIEND_REQUESTS_GONE = (
    "Signing in with a friend request has been replaced by room codes, which are safer. "
    "Sign in with a room code or your bonk.io password."
)


class ClaimProblem(Exception):
    """The claim can't be started or finished; `message` says why."""

    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


def name_problem(name: str) -> str | None:
    """Why `name` can't be a bonk.io username, in words for the person."""
    if not name or not name.strip():
        return "Type your bonk.io username."
    if len(name) > NAME_MAX_LENGTH:
        return f"bonk.io usernames are at most {NAME_MAX_LENGTH} characters."
    if any(not ch.isprintable() for ch in name):
        return "That username has characters bonk.io doesn't allow."
    return None
