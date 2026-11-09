"""The <username:…> path converter for profile URLs.

bonk.io allows usernames like "." and "..". In a path those are dot segments:
browsers (and requests) resolve /player/../ to /, so the profile can't be
reached, and percent-encoding doesn't help because "%2E%2E" counts as ".."
too. Such names get a "~" in front in the URL: "." → "~.", ".." → "~..".
So that a real name like "~.." still has its own URL, a name that is only
tildes followed by one or two dots gets one more "~" ("~.." → "~~.."). Every
other name is in the path as-is.
"""


def _is_dot_name(value):
    """Only tildes, then "." or ".." ("~*\\.{1,2}"), checked without a
    regex so a long run of "~" from a URL costs one linear scan."""
    return value.lstrip("~") in (".", "..")


def to_url(username):
    username = str(username)
    return "~" + username if _is_dot_name(username) else username


def from_url(value):
    if _is_dot_name(value) and value.startswith("~"):
        return value[1:]
    return value


class UsernameConverter:
    regex = "[^/]+"

    def to_python(self, value):
        return from_url(value)

    def to_url(self, value):
        return to_url(value)
