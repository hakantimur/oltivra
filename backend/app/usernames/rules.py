"""Username rules (spec §2.3): 3–16 chars, ASCII letters/digits/underscore, case-insensitive uniqueness,
reserved product/company/system/moderation/staff/impersonation names, profanity and slurs rejected."""

from __future__ import annotations

import re
from enum import StrEnum

USERNAME_RE = re.compile(r"^[A-Za-z0-9_]{3,16}$")

# Exact reserved names (normalized).
RESERVED_EXACT = {
    "admin", "administrator", "root", "system", "sys", "support", "help", "helpdesk", "moderator", "mod", "mods",
    "staff", "team", "official", "oltivra", "synova", "anthropic", "claude", "google", "apple", "firebase",
    "security", "safety", "trust", "billing", "payments", "store", "shop", "null", "undefined", "none", "nobody",
    "anonymous", "deleted", "deleteduser", "bot", "cpu", "ai", "server", "api", "dev", "developer", "owner",
    "gamemaster", "gm", "referee", "judge", "host", "everyone", "here", "you", "me", "player", "guest",
}

# Substrings that make a name reserved (impersonation of product/company/staff/moderation roles).
RESERVED_FRAGMENTS = (
    "oltivra", "synova", "admin", "moderat", "official", "staff", "support", "anthropic", "system",
)

# Profanity / slur fragments after leetspeak normalisation. Kept deliberately compact; admins extend it via
# the ``username_blocklist`` server document.
PROFANITY_FRAGMENTS = (
    "fuck", "fuk", "shit", "bitch", "cunt", "dick", "cock", "pussy", "whore", "slut", "bastard", "asshole",
    "nigg", "nigga", "fag", "retard", "rape", "nazi", "hitler", "kike", "chink", "spic", "tranny", "porn", "sex",
    "penis", "vagina", "orospu", "siktir", "amina", "yarrak", "pezevenk", "gavat", "kahpe", "ibne", "piç",
)

SCUNTHORPE_ALLOW = ("grape", "drape", "scrape", "peacock", "cockpit", "hancock", "dickens", "essex", "sussex",
                    "sextant", "sextet", "therapist", "shitake", "cocktail", "raccoon")

_LEET = str.maketrans({"0": "o", "1": "i", "3": "e", "4": "a", "5": "s", "7": "t", "8": "b", "9": "g", "@": "a",
                       "$": "s", "_": ""})


class UsernameProblem(StrEnum):
    FORMAT = "FORMAT"
    RESERVED = "RESERVED"
    PROFANITY = "PROFANITY"


def normalize(username: str) -> str:
    return username.lower()


def _deleet(value: str) -> str:
    collapsed = value.lower().translate(_LEET)
    return re.sub(r"(.)\1+", r"\1", collapsed)


def check_username(username: str, extra_blocklist: tuple[str, ...] = ()) -> UsernameProblem | None:
    if not USERNAME_RE.match(username or ""):
        return UsernameProblem.FORMAT
    norm = normalize(username)
    plain = norm.replace("_", "")
    if norm in RESERVED_EXACT or plain in RESERVED_EXACT:
        return UsernameProblem.RESERVED
    if any(fragment in plain for fragment in RESERVED_FRAGMENTS):
        return UsernameProblem.RESERVED
    squashed = _deleet(norm)
    raw = norm.replace("_", "")
    for word in SCUNTHORPE_ALLOW:  # innocent words that contain a blocked fragment
        squashed = squashed.replace(word, "")
        raw = raw.replace(word, "")
    for fragment in (*PROFANITY_FRAGMENTS, *extra_blocklist):
        if fragment in squashed or fragment in raw:
            return UsernameProblem.PROFANITY
    return None
