"""Advanced player search for the Players page (players/directory.html).

People look for accounts by the shape of the name: starting or ending with a
character, a length, only digits, symbols, leading or double spaces. These
filters read the GET parameters, describe themselves as chips, and narrow a
queryset of BonkPlayer (`username`) or FlashFriend (`name`) rows in Postgres.

Spaces in the name box count here (a name can be six spaces); the plain
search box trims them, because phone keyboards add a space after a word.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date

from django.db.models import Q
from django.db.models.functions import Length, Lower

from core.bonk import dbid

MATCHES = [
    ("contains", "Contains"),
    ("starts", "Starts with"),
    ("ends", "Ends with"),
    ("exact", "Is exactly"),
    ("pattern", "Pattern"),
]
_MATCH_LOOKUP = {
    "contains": "contains",
    "starts": "startswith",
    "ends": "endswith",
    "exact": "exact",
    "pattern": "regex",
}

# (key, label, POSIX class). Symbols are anything else.
KINDS = [
    ("letters", "Letters", "[A-Za-z]"),
    ("digits", "Digits", "[0-9]"),
    ("underscore", "Underscores", "_"),
    ("spaces", "Spaces", " "),
    ("symbols", "Symbols", "[^A-Za-z0-9_ ]"),
]
KIND_STATES = [("", "Any"), ("yes", "Has"), ("no", "None")]

SPACES = [
    ("lead_space", "Starts with a space"),
    ("trail_space", "Ends with a space"),
    ("double_space", "Two spaces in a row"),
]

SORTS = [
    ("", "Best match"),
    ("az", "A–Z"),
    ("za", "Z–A"),
    ("short", "Shortest first"),
    ("long", "Longest first"),
    ("friends", "Most friends"),
    ("old", "Oldest account"),
    ("new", "Newest account"),
]
# Sorts that need BonkPlayer columns; Flash friends fall back to best match.
PLAYER_ONLY_SORTS = {"friends", "old", "new"}

MAX_NAME = 100
MAX_WILDCARDS = 10
FIRST_YEAR = 2014  # bonk.io's release


@dataclass
class Filters:
    text: str = ""
    match: str = "contains"
    case: bool = False
    len_min: int | None = None
    len_max: int | None = None
    kinds: dict = field(default_factory=dict)  # key -> "yes" / "no"
    spaces: set = field(default_factory=set)
    joined_from: int | None = None
    joined_to: int | None = None
    min_friends: int | None = None
    members: bool = False
    sort: str = ""

    @property
    def active(self):
        """Any filter beyond the plain "contains" search box."""
        return bool(
            self.match != "contains"
            or self.case
            or self.len_min
            or self.len_max
            or self.kinds
            or self.spaces
            or self.joined_from
            or self.joined_to
            or self.min_friends
            or self.members
            or self.sort
        )

    def params(self):
        """The filters as GET parameters (no blanks), for links and paging."""
        p = {}
        if self.match != "contains":
            p["match"] = self.match
        if self.case:
            p["case"] = "1"
        for key in ("len_min", "len_max", "joined_from", "joined_to", "min_friends"):
            if getattr(self, key):
                p[key] = str(getattr(self, key))
        for key, state in self.kinds.items():
            p[key] = state
        for key in sorted(self.spaces):
            p[key] = "1"
        if self.members:
            p["members"] = "1"
        if self.sort:
            p["sort"] = self.sort
        return p

    def chips(self, *, players=True):
        """Short descriptions of the active filters, in form order."""
        out = []
        label = dict(MATCHES)[self.match]
        if self.text and self.match != "contains":
            out.append(f"{label} “{self.text}”")
        if self.case:
            out.append("Match case")
        if self.len_min and self.len_max:
            out.append(
                f"{self.len_min} characters"
                if self.len_min == self.len_max
                else f"{self.len_min}–{self.len_max} characters"
            )
        elif self.len_min:
            out.append(f"{self.len_min}+ characters")
        elif self.len_max:
            out.append(f"Up to {self.len_max} characters")
        for key, kind_label, _ in KINDS:
            state = self.kinds.get(key)
            if state == "yes":
                out.append(f"Has {kind_label.lower()}")
            elif state == "no":
                out.append(f"No {kind_label.lower()}")
        out.extend(text for key, text in SPACES if key in self.spaces)
        if players:
            if self.joined_from or self.joined_to:
                out.append(f"Joined {self.joined_from or FIRST_YEAR}–{self.joined_to or 'now'}")
            if self.min_friends:
                out.append(f"{self.min_friends}+ friends")
            if self.members:
                out.append("Bonkverse members")
        if self.sort and (players or self.sort not in PLAYER_ONLY_SORTS):
            out.append(f"Sort: {dict(SORTS)[self.sort]}")
        return out


def _int(raw, lo, hi):
    try:
        value = int(str(raw).strip())
    except (TypeError, ValueError):
        return None
    return value if lo <= value <= hi else None


def parse(get, *, today=None):
    """Filters from request.GET (anything invalid is ignored)."""
    today = today or date.today()
    match = get.get("match", "contains")
    f = Filters(
        match=match if match in _MATCH_LOOKUP else "contains",
        case=get.get("case") == "1",
        len_min=_int(get.get("len_min"), 1, MAX_NAME),
        len_max=_int(get.get("len_max"), 1, MAX_NAME),
        kinds={k: get.get(k) for k, _, _ in KINDS if get.get(k) in ("yes", "no")},
        spaces={k for k, _ in SPACES if get.get(k) == "1"},
        joined_from=_int(get.get("joined_from"), FIRST_YEAR, today.year),
        joined_to=_int(get.get("joined_to"), FIRST_YEAR, today.year),
        min_friends=_int(get.get("min_friends"), 1, 100_000),
        members=get.get("members") == "1",
        sort=get.get("sort") if get.get("sort") in dict(SORTS) else "",
    )
    if f.len_min and f.len_max and f.len_min > f.len_max:
        f.len_min, f.len_max = f.len_max, f.len_min
    if f.joined_from and f.joined_to and f.joined_from > f.joined_to:
        f.joined_from, f.joined_to = f.joined_to, f.joined_from
    raw = (get.get("q") or "")[:MAX_NAME]
    # Spaces count in advanced search; the plain box trims them.
    f.text = raw if f.active else raw.strip()
    return f


def pattern_regex(text):
    """A name pattern as an anchored regex: * is any run of characters, ? is
    one character, everything else is literal."""
    out, wild = [], 0
    for ch in text:
        if ch in "*?" and wild < MAX_WILDCARDS:
            wild += 1
            out.append(".*" if ch == "*" else ".")
        else:
            out.append(re.escape(ch))
    return "^" + "".join(out) + "$"


def apply(qs, f, name_field, *, players=True):
    """`qs` narrowed by `f` on `name_field`; BonkPlayer-only filters apply
    when `players` is true. Returns the queryset, ordered."""
    if f.text:
        lookup = _MATCH_LOOKUP[f.match]
        value = pattern_regex(f.text) if f.match == "pattern" else f.text
        if not f.case:
            lookup = "i" + lookup
        cond = Q(**{f"{name_field}__{lookup}": value})
        if players and f.match == "contains" and f.text.isdigit():
            cond |= Q(bonk_id=int(f.text))  # the plain box also finds a bonk.io ID
        qs = qs.filter(cond)

    if f.len_min or f.len_max or f.sort in ("short", "long"):
        qs = qs.annotate(name_len=Length(name_field))
        if f.len_min:
            qs = qs.filter(name_len__gte=f.len_min)
        if f.len_max:
            qs = qs.filter(name_len__lte=f.len_max)

    classes = {k: cls for k, _, cls in KINDS}
    for key, state in f.kinds.items():
        cond = Q(**{f"{name_field}__regex": classes[key]})
        qs = qs.filter(cond) if state == "yes" else qs.exclude(cond)

    if "lead_space" in f.spaces:
        qs = qs.filter(**{f"{name_field}__startswith": " "})
    if "trail_space" in f.spaces:
        qs = qs.filter(**{f"{name_field}__endswith": " "})
    if "double_space" in f.spaces:
        qs = qs.filter(**{f"{name_field}__contains": "  "})

    if players:
        if f.joined_from:
            qs = qs.filter(bonk_id__gte=dbid.id_for_day(date(f.joined_from, 1, 1)))
        if f.joined_to:
            qs = qs.filter(bonk_id__lt=dbid.id_for_day(date(f.joined_to + 1, 1, 1)))
        if f.min_friends:
            qs = qs.filter(last_friend_count__gte=f.min_friends)
        if f.members:
            qs = qs.filter(linked=True)

    return _order(qs, f, name_field, players=players)


def _order(qs, f, name_field, *, players):
    by_name = (Lower(name_field), name_field, "pk")
    sort = f.sort if (players or f.sort not in PLAYER_ONLY_SORTS) else ""
    if sort == "az":
        return qs.order_by(*by_name)
    if sort == "za":
        return qs.order_by(Lower(name_field).desc(), f"-{name_field}", "-pk")
    if sort == "short":
        return qs.order_by("name_len", *by_name)
    if sort == "long":
        return qs.order_by("-name_len", *by_name)
    if sort == "friends":
        return qs.order_by("-last_friend_count", *by_name)
    if sort == "old":
        return qs.order_by("bonk_id")
    if sort == "new":
        return qs.order_by("-bonk_id")
    # Best match: the existing default order of the queryset.
    return qs
