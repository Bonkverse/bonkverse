"""What a skin's owner can change about it: its name and its tags.

Owns: the rules for an owner's edit (name length, how many tags and how
long), and how one flat list of tags maps onto the skin's labels. Does not
own: who owns a skin (Skin.is_owned_by), the description (no longer shown or
edited; it stays as search data), or the image and code (skin_media.py).

Tags are what search's "Tags" mode and the categories read: the `themes`,
`objects` and `references` lists in `Skin.labels`. The owner sees them as one
list. Removing a tag takes it out of whichever list held it; a new tag goes
into `themes`. `style` and `colors` are left alone.
"""

from __future__ import annotations

from dataclasses import dataclass

from django.db import transaction

from .models import Skin

TAG_FIELDS = ("themes", "objects", "references")
NEW_TAGS_GO_TO = "themes"
MAX_NAME_LENGTH = 100
MAX_TAGS = 30
MAX_TAG_LENGTH = 40


class EditError(ValueError):
    """An edit that can't be saved; the message says why, for the owner."""


@dataclass(frozen=True)
class Edited:
    name: str
    tags: list[str]


def _as_list(value) -> list[str]:
    return [str(v) for v in value] if isinstance(value, list) else []


def tags_of(skin: Skin) -> list[str]:
    """The skin's tags as one list, in label order, each once (ignoring case)."""
    labels = skin.labels or {}
    seen, tags = set(), []
    for field in TAG_FIELDS:
        for tag in _as_list(labels.get(field)):
            if tag.lower() not in seen:
                seen.add(tag.lower())
                tags.append(tag)
    return tags


def clean_tags(raw) -> list[str]:
    """Tags as the owner typed them: trimmed, empty ones dropped, each once."""
    if not isinstance(raw, list):
        raise EditError("Tags must be a list.")
    seen, tags = set(), []
    for item in raw:
        tag = " ".join(str(item).split())
        if not tag or tag.lower() in seen:
            continue
        if len(tag) > MAX_TAG_LENGTH:
            raise EditError(f"Tags can be up to {MAX_TAG_LENGTH} characters.")
        seen.add(tag.lower())
        tags.append(tag)
    if len(tags) > MAX_TAGS:
        raise EditError(f"A skin can have up to {MAX_TAGS} tags.")
    return tags


def clean_name(raw) -> str:
    name = " ".join(str(raw or "").split())
    if not name:
        raise EditError("Give the skin a name.")
    if len(name) > MAX_NAME_LENGTH:
        raise EditError(f"Names can be up to {MAX_NAME_LENGTH} characters.")
    return name


def edit(skin_id: int, *, name, tags) -> Edited:
    """Rename the skin and set its tags. Raises EditError (nothing saved) for
    a bad name or tags, Skin.DoesNotExist if it's gone. Ownership is the
    caller's check."""
    name, tags = clean_name(name), clean_tags(tags)
    with transaction.atomic():
        skin = Skin.objects.select_for_update().get(id=skin_id)
        labels = dict(skin.labels or {})
        wanted = {t.lower() for t in tags}
        kept = set()
        for field in TAG_FIELDS:
            labels[field] = [t for t in _as_list(labels.get(field)) if t.lower() in wanted]
            kept.update(t.lower() for t in labels[field])
        labels[NEW_TAGS_GO_TO] += [t for t in tags if t.lower() not in kept]
        skin.name, skin.labels = name, labels
        skin.save(update_fields=["name", "labels"])
    return Edited(name=name, tags=tags_of(skin))
