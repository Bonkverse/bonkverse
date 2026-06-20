# skins/categories.py
#
# Browse-by-category + New Releases views.
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

from datetime import timedelta

from django.core.cache import cache
from django.core.paginator import Paginator
from django.db.models import Q, Count, F
from django.http import Http404
from django.shortcuts import render
from django.utils import timezone
from django_ratelimit.decorators import ratelimit

from skins.models import Skin

# slug -> display metadata + keyword set
CATEGORIES = {
    "minimalist":   {"label": "Minimalist",          "blurb": "Clean lines and lots of negative space.",
                     "keywords": ["minimal", "flat design", "flat", "simplicity"]},
    "cartoon":      {"label": "Cartoon",             "blurb": "Cartoonish and comic-style art.",
                     "keywords": ["cartoon", "comic"]},
    "faces":        {"label": "Faces & Characters",  "blurb": "Faces, expressions, and characters.",
                     "keywords": ["face", "character", "smiley", "smile", "eyes"]},
    "nature":       {"label": "Nature",              "blurb": "Plants, water, sky, and the outdoors.",
                     "keywords": ["nature", "natural", "tree", "plant", "flower", "leaf",
                                  "ocean", "wave", "landscape", "mountain"]},
    "flags":        {"label": "Flags & Countries",   "blurb": "National flags and country pride.",
                     "keywords": ["flag", "national identity", "national pride", "patriot", "country"]},
    "space":        {"label": "Space & Cosmic",      "blurb": "Stars, planets, and the cosmos.",
                     "keywords": ["space", "cosmic", "galaxy", "planet", "moon", "star", "astronom", "celestial"]},
    "sports":       {"label": "Sports",              "blurb": "Jerseys, teams, and athletics.",
                     "keywords": ["sport", "soccer", "football", "jersey", "nike", "adidas", "basketball"]},
    "logos":        {"label": "Logos & Text",        "blurb": "Logos, emblems, letters, and numbers.",
                     "keywords": ["logo", "emblem", "letter", "typography", "text", "number", "symbol"]},
    "fire":         {"label": "Fire & Energy",       "blurb": "Flames, sparks, and raw energy.",
                     "keywords": ["fire", "flame", "energy", "lava", "spark"]},
    "gaming":       {"label": "Gaming",              "blurb": "Video games and gaming culture.",
                     "keywords": ["gaming", "video game", "among us", "minecraft", "undertale", "kirby"]},
    "anime":        {"label": "Anime & Manga",       "blurb": "Anime, manga, and related references.",
                     "keywords": ["anime", "manga", "naruto", "pokémon", "pokemon", "ninja"]},
    "spooky":       {"label": "Spooky & Dark",       "blurb": "Skulls, horror, and shadowy themes.",
                     "keywords": ["horror", "skull", "spooky", "creepy", "stealth", "death", "mystery"]},
    "geometric":    {"label": "Geometric",           "blurb": "Shapes, symmetry, and structure.",
                     "keywords": ["geometric", "geometry"]},
    "memes":        {"label": "Memes & Internet",    "blurb": "Memes, emoji, and internet culture.",
                     "keywords": ["meme", "internet culture", "discord", "emoji"]},
    "cute":         {"label": "Cute",                "blurb": "Adorable, soft, and whimsical.",
                     "keywords": ["cute", "kawaii", "adorable", "whimsy", "whimsical"]},
    "animals":      {"label": "Animals",             "blurb": "Creatures big and small.",
                     "keywords": ["animal", "cat", "dog", "bird", "fish", "wolf", "fox"]},
    "food":         {"label": "Food",                "blurb": "Snacks, fruit, and meals.",
                     "keywords": ["food", "fruit", "pizza", "burger", "candy"]},
    "silhouette":   {"label": "Silhouette",          "blurb": "Bold shapes against a backdrop.",
                     "keywords": ["silhouette"]},
    "pixel":        {"label": "Pixel Art",           "blurb": "Retro pixel and 8-bit style.",
                     "keywords": ["pixel", "8-bit", "8 bit"]},
    # "abstract" is the labeler's fallback bucket (huge + low signal).
    # Uncomment if you want it browsable.
    # "abstract":   {"label": "Abstract / Other",    "blurb": "Non-representational designs.",
    #                "keywords": ["abstract"]},
}

# Fields we treat as category sources (NOT colors).
_CATEGORY_FIELDS = ["style", "themes", "objects", "references"]


def _kw_q(keywords, include_description=False):
    """OR a list of keywords across the label fields (substring, case-insensitive)."""
    q = Q()
    for kw in keywords:
        for field in _CATEGORY_FIELDS:
            q |= Q(**{f"labels__{field}__icontains": kw})
        if include_description:
            q |= Q(description__icontains=kw)
    return q


# Hide flagged content from browse surfaces by default.
NSFW_Q = _kw_q(["nsfw", "explicit", "nude"], include_description=True)

# Hide flagged content in a NULL-safe way: positively match nsfw skins,
# then exclude those ids. Writing .exclude(NSFW_Q) directly would also drop
# skins whose labels/description are NULL (NOT NULL = NULL in SQL) — i.e.
# every brand-new, not-yet-labeled upload. We also no longer require labels
# at all here, so New Releases shows fresh uploads immediately.
def _base_queryset():
    nsfw_ids = Skin.objects.filter(NSFW_Q).values("id")
    return Skin.objects.exclude(id__in=nsfw_ids)


def _apply_sort(qs, sort):
    if sort == "newest":
        return qs.order_by("-created_at"), "newest"
    if sort == "upvotes":
        return qs.annotate(score=F("upvotes") - F("downvotes")).order_by("-score", "-created_at"), "upvotes"
    return qs.annotate(fav_count=Count("favorited_by")).order_by("-fav_count", "-upvotes"), "favorites"


@ratelimit(key="ip", rate="30/m", block=True)
def category_index(request):
    """Tiles for every category, with a cover image and count. Cached in Redis."""
    items = cache.get("category_index_v1")
    if items is None:
        items = []
        for slug, meta in CATEGORIES.items():
            qs = _base_queryset().filter(_kw_q(meta["keywords"]))
            cover = qs.order_by("-upvotes").values_list("image_url", flat=True).first()
            items.append({
                "slug":  slug,
                "label": meta["label"],
                "blurb": meta["blurb"],
                "count": qs.count(),
                "cover": cover,
            })
        items.sort(key=lambda x: -x["count"])
        cache.set("category_index_v1", items, 60 * 60)  # 1 hour
    return render(request, "skins/category_index.html", {"categories": items})


@ratelimit(key="ip", rate="30/m", block=True)
def category_detail(request, slug):
    meta = CATEGORIES.get(slug)
    if not meta:
        raise Http404("Unknown category")

    qs = _base_queryset().filter(_kw_q(meta["keywords"]))
    qs, sort = _apply_sort(qs, request.GET.get("sort", "favorites"))

    page_obj = Paginator(qs, 60).get_page(request.GET.get("page", 1))
    return render(request, "skins/skin_browse.html", {
        "page_obj": page_obj,
        "heading":  meta["label"],
        "blurb":    meta["blurb"],
        "sort":     sort,
        "slug":     slug,
    })


@ratelimit(key="ip", rate="30/m", block=True)
def new_releases(request):
    period = request.GET.get("period", "all")
    qs = _base_queryset().order_by("-created_at")

    now = timezone.now()
    if period == "today":
        qs = qs.filter(created_at__gte=now - timedelta(days=1))
    elif period == "week":
        qs = qs.filter(created_at__gte=now - timedelta(days=7))
    else:
        period = "all"

    page_obj = Paginator(qs, 60).get_page(request.GET.get("page", 1))
    return render(request, "skins/skin_browse.html", {
        "page_obj": page_obj,
        "heading":  "New Releases",
        "blurb":    "Fresh uploads, newest first.",
        "period":   period,
    })