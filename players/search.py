"""Advanced player search for the Players page: a rule builder.

People look for accounts by the shape of the name (starts with "_" AND ends
with "_", exactly 3 characters, only digits, a name of spaces) and by the
account (joined in 2014, 100+ friends, a low ID). Each rule is one line of
the builder: [AND / OR] [field] [condition] [value]. AND binds before OR,
like in a search engine: a AND b OR c is (a AND b) OR c.

Rules travel in the address as numbered parameters (c0 f0 o0 v0 w0 k0,
c1 f1 …): connector, field, condition, value, second value (for "between")
and match case. Every field says which lists it works on (bonk.io accounts,
Flash friends) and which conditions and value it takes; the page builds the
form from FIELDS, so a new field is one entry here.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date

from django.db.models import Q
from django.db.models.functions import Length, Lower

from core.bonk import dbid

MAX_RULES = 12
MAX_TEXT = 100
MAX_WILDCARDS = 10
FIRST_YEAR = 2014  # bonk.io's release

# Character kinds: (key, label, one-character POSIX class). Symbols are
# anything that isn't a letter, digit, underscore or space.
KINDS = [
    ("letters", "letters", "[A-Za-z]"),
    ("digits", "digits", "[0-9]"),
    ("underscore", "underscores", "_"),
    ("spaces", "spaces", " "),
    ("symbols", "symbols", "[^A-Za-z0-9_ ]"),
]
SPACE_SPOTS = [
    ("lead", "a space at the start"),
    ("trail", "a space at the end"),
    ("double", "two spaces in a row"),
]

NUMBER_OPS = [
    ("eq", "is"),
    ("ne", "is not"),
    ("gte", "is at least"),
    ("lte", "is at most"),
    ("between", "is between"),
]

# field key -> definition. "value": text | number | year | choice | none.
# "lists": which directory views it works on ("all" = bonk.io accounts).
FIELDS = {
    "name": {
        "label": "Name",
        "value": "text",
        "lists": ["all", "flash"],
        "ops": [
            ("contains", "contains"),
            ("not_contains", "doesn't contain"),
            ("starts", "starts with"),
            ("not_starts", "doesn't start with"),
            ("ends", "ends with"),
            ("not_ends", "doesn't end with"),
            ("is", "is exactly"),
            ("is_not", "is not"),
            ("pattern", "matches pattern"),
        ],
    },
    "length": {
        "label": "Length",
        "value": "number",
        "unit": "characters",
        "min": 1,
        "max": MAX_TEXT,
        "lists": ["all", "flash"],
        "ops": NUMBER_OPS,
    },
    "chars": {
        "label": "Characters",
        "value": "choice",
        "choices": [(k, label) for k, label, _ in KINDS],
        "lists": ["all", "flash"],
        "ops": [("has", "has"), ("none", "has no"), ("only", "has only")],
    },
    "spaces": {
        "label": "Spaces",
        "value": "choice",
        "choices": SPACE_SPOTS,
        "lists": ["all", "flash"],
        "ops": [("has", "has"), ("none", "doesn't have")],
    },
    "joined": {
        "label": "Joined",
        "value": "year",
        "lists": ["all"],
        "ops": [
            ("in", "in"),
            ("before", "before"),
            ("after", "after"),
            ("between", "between"),
        ],
    },
    "friends": {
        "label": "Friends",
        "value": "number",
        "unit": "friends",
        "min": 0,
        "max": 100_000,
        "lists": ["all"],
        "ops": NUMBER_OPS,
    },
    "bonk_id": {
        "label": "Account ID",
        "value": "number",
        "min": 1,
        "max": 10**12,
        "lists": ["all"],
        "ops": NUMBER_OPS + [("lt", "is below"), ("gt", "is above")],
    },
    "member": {
        "label": "Bonkverse member",
        "value": "none",
        "lists": ["all"],
        "ops": [("yes", "yes"), ("no", "no")],
    },
    "listed": {
        "label": "Listed by",
        "value": "number",
        "unit": "members",
        "min": 0,
        "max": 100_000,
        "lists": ["flash"],
        "ops": NUMBER_OPS,
    },
}

SORTS = [
    ("", "Best match", ["all", "flash"]),
    ("az", "A–Z", ["all", "flash"]),
    ("za", "Z–A", ["all", "flash"]),
    ("short", "Shortest first", ["all", "flash"]),
    ("long", "Longest first", ["all", "flash"]),
    ("friends", "Most friends", ["all"]),
    ("old", "Oldest account", ["all"]),
    ("new", "Newest account", ["all"]),
]

# One-click starting points under the builder: (label, rules).
EXAMPLES = [
    ("Starts and ends with _", [("and", "name", "starts", "_"), ("and", "name", "ends", "_")]),
    ("Only digits", [("and", "chars", "only", "digits")]),
    ("3 characters", [("and", "length", "eq", "3")]),
    ("Made of spaces", [("and", "chars", "only", "spaces")]),
    ("Joined in 2014", [("and", "joined", "in", "2014")]),
    ("Has symbols", [("and", "chars", "has", "symbols")]),
]


@dataclass
class Rule:
    conn: str  # "and" / "or" (ignored on the first rule)
    field: str
    op: str
    value: str = ""
    value2: str = ""
    case: bool = False

    @property
    def spec(self):
        return FIELDS[self.field]

    def params(self, i):
        p = {f"f{i}": self.field, f"o{i}": self.op}
        if i:
            p[f"c{i}"] = self.conn
        if self.value:
            p[f"v{i}"] = self.value
        if self.value2:
            p[f"w{i}"] = self.value2
        if self.case:
            p[f"k{i}"] = "1"
        return p

    def describe(self):
        spec = self.spec
        op = dict(spec["ops"])[self.op]
        kind = spec["value"]
        if kind == "none":
            return f"{spec['label']}: {op}"
        if kind == "choice":
            return f"{spec['label']} {op} {dict(spec['choices'])[self.value]}"
        if kind == "text":
            shown = self.value.replace(" ", "␣")
            return f"{spec['label']} {op} “{shown}”" + (" (Aa)" if self.case else "")
        unit = f" {spec['unit']}" if spec.get("unit") else ""
        if self.op == "between":
            return f"{spec['label']} {op} {self.value} and {self.value2}{unit}"
        return f"{spec['label']} {op} {self.value}{unit}"


@dataclass
class Query:
    text: str = ""  # the plain search box (trimmed), ANDed with the rules
    rules: list = field(default_factory=list)
    sort: str = ""

    @property
    def active(self):
        return bool(self.rules or self.sort)

    def params(self):
        p = {}
        for i, rule in enumerate(self.rules):
            p.update(rule.params(i))
        if self.sort:
            p["sort"] = self.sort
        return p

    def chips(self):
        """[(connector or "", description)] for the summary under the form."""
        return [("" if i == 0 else r.conn.upper(), r.describe()) for i, r in enumerate(self.rules)]


# ── Parsing ──────────────────────────────────────────────────────


def _int(raw, lo, hi):
    try:
        value = int(str(raw).strip())
    except (TypeError, ValueError):
        return None
    return value if lo <= value <= hi else None


def _clean_rule(get, i, view, today):
    """Rule number `i` from the GET parameters, or None if it isn't usable."""
    key = get.get(f"f{i}")
    spec = FIELDS.get(key)
    if not spec or view not in spec["lists"]:
        return None
    op = get.get(f"o{i}")
    if op not in dict(spec["ops"]):
        return None
    conn = "or" if get.get(f"c{i}") == "or" else "and"
    raw, raw2 = get.get(f"v{i}", ""), get.get(f"w{i}", "")
    kind = spec["value"]
    rule = Rule(conn, key, op)

    if kind == "text":
        rule.value = raw[:MAX_TEXT]  # not trimmed: spaces are part of names
        rule.case = get.get(f"k{i}") == "1"
        return rule if rule.value else None
    if kind == "choice":
        rule.value = raw if raw in dict(spec["choices"]) else ""
        return rule if rule.value else None
    if kind == "none":
        return rule
    lo, hi = (FIRST_YEAR, today.year) if kind == "year" else (spec["min"], spec["max"])
    a, b = _int(raw, lo, hi), _int(raw2, lo, hi)
    if a is None:
        return None
    if op == "between":
        if b is None:
            return None
        a, b = min(a, b), max(a, b)
        rule.value2 = str(b)
    rule.value = str(a)
    return rule


def parse(get, view="all", *, today=None):
    """The query from request.GET for directory view `view`; unusable rules
    (blank values, fields that don't apply to the view) are dropped."""
    today = today or date.today()
    rules = []
    for i in range(MAX_RULES):
        rule = _clean_rule(get, i, view, today)
        if rule:
            rules.append(rule)
    sort = get.get("sort", "")
    if sort not in {k for k, _, lists in SORTS if view in lists}:
        sort = ""
    return Query(text=(get.get("q") or "").strip()[:MAX_TEXT], rules=rules, sort=sort)


# ── Building the query ───────────────────────────────────────────


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


_TEXT = {
    "contains": ("contains", False),
    "not_contains": ("contains", True),
    "starts": ("startswith", False),
    "not_starts": ("startswith", True),
    "ends": ("endswith", False),
    "not_ends": ("endswith", True),
    "is": ("exact", False),
    "is_not": ("exact", True),
    "pattern": ("regex", False),
}
_NUMBER = {"eq": "exact", "gte": "gte", "lte": "lte", "lt": "lt", "gt": "gt"}
_SPOT = {"lead": ("startswith", " "), "trail": ("endswith", " "), "double": ("contains", "  ")}


def _number_q(column, rule):
    a = int(rule.value)
    if rule.op == "between":
        return Q(**{f"{column}__gte": a, f"{column}__lte": int(rule.value2)})
    if rule.op == "ne":
        return ~Q(**{column: a})
    return Q(**{f"{column}__{_NUMBER[rule.op]}": a})


def rule_q(rule, name_field):
    """One rule as a Q object on a queryset of names in `name_field`."""
    nf = name_field
    if rule.field == "name":
        lookup, negate = _TEXT[rule.op]
        value = pattern_regex(rule.value) if rule.op == "pattern" else rule.value
        q = Q(**{f"{nf}__{'' if rule.case else 'i'}{lookup}": value})
        return ~q if negate else q
    if rule.field == "length":
        return _number_q("name_len", rule)
    if rule.field == "chars":
        cls = {k: c for k, _, c in KINDS}[rule.value]
        if rule.op == "only":
            return Q(**{f"{nf}__regex": f"^{cls}+$"})
        q = Q(**{f"{nf}__regex": cls})
        return q if rule.op == "has" else ~q
    if rule.field == "spaces":
        lookup, value = _SPOT[rule.value]
        q = Q(**{f"{nf}__{lookup}": value})
        return q if rule.op == "has" else ~q
    if rule.field == "joined":
        start = dbid.id_for_day(date(int(rule.value), 1, 1))
        end_year = int(rule.value2) if rule.op == "between" else int(rule.value)
        end = dbid.id_for_day(date(end_year + 1, 1, 1))
        if rule.op == "before":
            return Q(bonk_id__lt=start)
        if rule.op == "after":
            return Q(bonk_id__gte=end)
        return Q(bonk_id__gte=start, bonk_id__lt=end)
    if rule.field == "friends":
        return _number_q("last_friend_count", rule)
    if rule.field == "bonk_id":
        return _number_q("bonk_id", rule)
    if rule.field == "member":
        return Q(linked=rule.op == "yes")
    if rule.field == "listed":
        return _number_q("listed_by", rule)
    raise ValueError(rule.field)


def combined_q(rules, name_field):
    """The rules joined: AND before OR, so a AND b OR c is (a AND b) OR c."""
    groups, current = [], None
    for i, rule in enumerate(rules):
        q = rule_q(rule, name_field)
        if i == 0 or rule.conn == "or":
            if current is not None:
                groups.append(current)
            current = q
        else:
            current &= q
    if current is not None:
        groups.append(current)
    out = Q()
    for g in groups:
        out = g if not out else out | g
    return out


def apply(qs, query, name_field, *, players=True):
    """`qs` narrowed by `query`'s plain text and rules, then sorted."""
    if query.text:
        cond = Q(**{f"{name_field}__icontains": query.text})
        if players and query.text.isdigit():
            cond |= Q(bonk_id=int(query.text))  # the box also finds a bonk.io ID
        qs = qs.filter(cond)
    needs_len = any(r.field == "length" for r in query.rules) or query.sort in ("short", "long")
    if needs_len:
        qs = qs.annotate(name_len=Length(name_field))
    if query.rules:
        qs = qs.filter(combined_q(query.rules, name_field))
    return _order(qs, query.sort, name_field)


def _order(qs, sort, name_field):
    by_name = (Lower(name_field), name_field, "pk")
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
    return qs  # best match: the queryset's own order


# ── The form ─────────────────────────────────────────────────────


def schema(view, today=None):
    """Fields, conditions and values for the builder script, for one view."""
    today = today or date.today()
    years = list(range(today.year, FIRST_YEAR - 1, -1))
    out = []
    for key, spec in FIELDS.items():
        if view not in spec["lists"]:
            continue
        item = {
            "key": key,
            "label": spec["label"],
            "value": spec["value"],
            "ops": [{"key": k, "label": label} for k, label in spec["ops"]],
        }
        if spec["value"] == "choice":
            item["choices"] = [{"key": k, "label": label} for k, label in spec["choices"]]
        if spec["value"] == "year":
            item["choices"] = [{"key": str(y), "label": str(y)} for y in years]
        if spec["value"] == "number":
            item.update(min=spec["min"], max=spec["max"], unit=spec.get("unit", ""))
        out.append(item)
    return out


def example_links(view):
    """[(label, query string)] for the example chips that fit `view`."""
    out = []
    for label, rules in EXAMPLES:
        if not all(view in FIELDS[f]["lists"] for _, f, _, _ in rules):
            continue
        query = Query(rules=[Rule(c, f, o, v) for c, f, o, v in rules])
        out.append((label, query.params()))
    return out
