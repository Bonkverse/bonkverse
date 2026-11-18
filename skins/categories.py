# Skin categories: what each one matches, and the skins a browse page lists.
# The pages themselves are skins/views/browse.py.
#
# The taxonomy below was derived from the actual label distribution
# (see analyze_labels). Each category is a set of KEYWORDS matched
# case-insensitively as substrings across style / themes / objects /
# references. Substring matching is deliberate: it collapses the
# labeler's synonym + compound noise automatically —
#   "minimal"  -> minimalist, minimalistic, minimalism, "modern, minimalist"
#   "cartoon"  -> cartoon, cartoonish
#   "flag"     -> flag, national flag, flag design
# colors is intentionally NOT searched (it's a filter axis, not a category,
# and matching it would make "dark" hit "dark blue", etc).


from django.core.cache import cache
from django.db.models import Q

from skins.models import CategoryCover, Skin

# slug -> display metadata + keyword set
CATEGORIES = {
    "minimalist": {
        "label": "Minimalist",
        "blurb": "Clean lines and lots of negative space.",
        "keywords": ["minimal", "flat design", "flat", "simplicity"],
    },
    "cartoon": {
        "label": "Cartoon",
        "blurb": "Cartoonish and comic-style art.",
        "keywords": ["cartoon", "comic"],
    },
    "faces": {
        "label": "Faces & Characters",
        "blurb": "Faces, expressions, and characters.",
        "keywords": ["face", "character", "smiley", "smile", "eyes"],
    },
    "nature": {
        "label": "Nature",
        "blurb": "Plants, water, sky, and the outdoors.",
        "keywords": [
            "nature",
            "natural",
            "tree",
            "plant",
            "flower",
            "leaf",
            "ocean",
            "wave",
            "landscape",
            "mountain",
        ],
    },
    "flags": {
        "label": "Flags & Countries",
        "blurb": "National flags and country pride.",
        "keywords": ["flag", "national identity", "national pride", "patriot", "country"],
    },
    "space": {
        "label": "Space & Cosmic",
        "blurb": "Stars, planets, and the cosmos.",
        "keywords": [
            "space",
            "cosmic",
            "galaxy",
            "planet",
            "moon",
            "star",
            "astronom",
            "celestial",
        ],
    },
    "sports": {
        "label": "Sports",
        "blurb": "Jerseys, teams, and athletics.",
        "keywords": ["sport", "soccer", "football", "jersey", "nike", "adidas", "basketball"],
    },
    "logos": {
        "label": "Logos & Text",
        "blurb": "Logos, emblems, letters, and numbers.",
        "keywords": ["logo", "emblem", "letter", "typography", "text", "number", "symbol"],
    },
    "fire": {
        "label": "Fire & Energy",
        "blurb": "Flames, sparks, and raw energy.",
        "keywords": ["fire", "flame", "energy", "lava", "spark"],
    },
    "gaming": {
        "label": "Gaming",
        "blurb": "Video games and gaming culture.",
        "keywords": ["gaming", "video game", "among us", "minecraft", "undertale", "kirby"],
    },
    "anime": {
        "label": "Anime & Manga",
        "blurb": "Anime, manga, and related references.",
        "keywords": ["anime", "manga", "naruto", "pokémon", "pokemon", "ninja"],
    },
    "spooky": {
        "label": "Spooky & Dark",
        "blurb": "Skulls, horror, and shadowy themes.",
        "keywords": ["horror", "skull", "spooky", "creepy", "stealth", "death", "mystery"],
    },
    "geometric": {
        "label": "Geometric",
        "blurb": "Shapes, symmetry, and structure.",
        "keywords": ["geometric", "geometry"],
    },
    "memes": {
        "label": "Memes & Internet",
        "blurb": "Memes, emoji, and internet culture.",
        "keywords": ["meme", "internet culture", "discord", "emoji"],
    },
    "cute": {
        "label": "Cute",
        "blurb": "Adorable, soft, and whimsical.",
        "keywords": ["cute", "kawaii", "adorable", "whimsy", "whimsical"],
    },
    "animals": {
        "label": "Animals",
        "blurb": "Creatures big and small.",
        "keywords": ["animal", "cat", "dog", "bird", "fish", "wolf", "fox"],
    },
    "food": {
        "label": "Food",
        "blurb": "Snacks, fruit, and meals.",
        "keywords": ["food", "fruit", "pizza", "burger", "candy"],
    },
    "silhouette": {
        "label": "Silhouette",
        "blurb": "Bold shapes against a backdrop.",
        "keywords": ["silhouette"],
    },
    "pixel": {
        "label": "Pixel Art",
        "blurb": "Retro pixel and 8-bit style.",
        "keywords": ["pixel", "8-bit", "8 bit"],
    },
}

# Fields we treat as category sources (NOT colors).
_CATEGORY_FIELDS = ["style", "themes", "objects", "references"]


def keyword_q(keywords, include_description=False):
    """OR a list of keywords across the label fields (substring, case-insensitive)."""
    q = Q()
    for kw in keywords:
        for field in _CATEGORY_FIELDS:
            q |= Q(**{f"labels__{field}__icontains": kw})
        if include_description:
            q |= Q(description__icontains=kw)
    return q


# Hide flagged content from browse surfaces by default.
NSFW_Q = keyword_q(["nsfw", "explicit", "nude"], include_description=True)


# Hide flagged content in a NULL-safe way: positively match nsfw skins,
# then exclude those ids. Writing .exclude(NSFW_Q) directly would also drop
# skins whose labels/description are NULL (NOT NULL = NULL in SQL) — i.e.
# every brand-new, not-yet-labeled upload. We also no longer require labels
# at all here, so New Releases shows fresh uploads immediately.
def browsable_skins():
    nsfw_ids = Skin.objects.filter(NSFW_Q).values("id")
    return Skin.objects.exclude(id__in=nsfw_ids)


def sorted_skins(qs, sort):
    if sort == "newest":
        return qs.order_by("-created_at"), "newest"
    if sort == "upvotes":
        return qs.with_score().order_by("-score", "-created_at"), "upvotes"
    return qs.with_favorite_count().order_by("-fav_count", "-upvotes"), "favorites"


def category_covers() -> dict[str, str]:
    """{category slug: cover image URL} for the hand-picked covers (CategoryCover)
    whose skin has no open report. One query, not cached, so a new pick or a
    report shows at once."""
    picks = CategoryCover.objects.filter(skin__in=Skin.objects.without_open_reports()).values_list(
        "category", "skin__image_url"
    )
    return {slug: image for slug, image in picks if image}


def category_tiles() -> list[dict]:
    """A tile per category (hand-picked cover and count), biggest first.

    The counts are cached an hour; covers are looked up on every request.
    A category without a cover gets an empty tile: covers are never picked
    automatically (the most upvoted match can be anything).
    """
    counts = cache.get("category_counts_v2")
    if counts is None:
        counts = {
            slug: browsable_skins().filter(keyword_q(meta["keywords"])).count()
            for slug, meta in CATEGORIES.items()
        }
        cache.set("category_counts_v2", counts, 60 * 60)  # 1 hour
    covers = category_covers()
    items = [
        {
            "slug": slug,
            "label": meta["label"],
            "blurb": meta["blurb"],
            "count": counts.get(slug, 0),
            "cover": covers.get(slug),
        }
        for slug, meta in CATEGORIES.items()
    ]
    items.sort(key=lambda x: -x["count"])
    return items
