"""Reusable Skin queries: Skin.objects.<method>() (RFC-0001: one home per filter).

Owns: the favorite-count and score annotations, period filters, and the
search modes (relevance, name, creator, tags, description) with their
relevance thresholds.
Does not own: sorting and paging a page's results (the views), the visitor's
own votes and favorites on cards (skins/selectors.py), or the search indexes
(Skin.Meta in skins/models.py).
"""

from django.contrib.postgres.search import SearchQuery, SearchRank, TrigramSimilarity
from django.db import models
from django.db.models import Count, F, Q

from core.periods import period_start

# Text-search language for skins: Skin.search_vector (skins/models.py) and
# every SearchQuery against it must use the same one, or searches miss.
SKIN_SEARCH_CONFIG = "english"

# Relevance thresholds. Unchanged from the original search; the index prefilter
# in relevant_to only skips rows that could never pass them.
MIN_RANK = 0.1
MIN_NAME_SIMILARITY = 0.2


class SkinQuerySet(models.QuerySet):
    def with_favorite_count(self):
        """Annotate `fav_count`: how many users favorited each skin."""
        return self.annotate(fav_count=Count("favorited_by"))

    def with_score(self):
        """Annotate `score`: upvotes minus downvotes."""
        return self.annotate(score=F("upvotes") - F("downvotes"))

    def created_in(self, period: str, now=None):
        """Skins created within a period from core.periods ("today", "week").

        A name that isn't a period (e.g. "all") leaves the queryset unfiltered.
        """
        start = period_start(period, now)
        if start is None:
            return self
        return self.filter(created_at__gte=start)

    def relevant_to(self, query: str):
        """Full-text + fuzzy-name matches, annotated with `rank` and `similarity`.

        Index-backed (search_vector GIN, name trigram GIN). Run it with
        pg_trgm.similarity_threshold = MIN_NAME_SIMILARITY (skins/search.py
        does), so the trigram prefilter keeps every row the rule accepts.
        """
        search_query = SearchQuery(query, config=SKIN_SEARCH_CONFIG)
        return (
            self.filter(Q(search_vector=search_query) | Q(name__trigram_similar=query))
            .annotate(
                rank=SearchRank(F("search_vector"), search_query),
                similarity=TrigramSimilarity("name", query),
            )
            .filter(Q(rank__gte=MIN_RANK) | Q(similarity__gt=MIN_NAME_SIMILARITY))
        )

    def search(self, query: str, mode: str):
        """Skins matching `query` in one search mode; unknown modes use relevance."""
        return SEARCH_MODES.get(mode, SEARCH_MODES["relevance"])(self, query)


# Search mode -> how it filters. Adding a mode is one line here (plus its
# option on the search page).
SEARCH_MODES = {
    "relevance": lambda skins, query: skins.relevant_to(query),
    "name": lambda skins, query: skins.filter(name__ilike_contains=query),
    "creator": lambda skins, query: skins.filter(creator__ilike_contains=query),
    "tags": lambda skins, query: skins.filter(labels__icontains=[query.lower()]),
    "description": lambda skins, query: skins.filter(description__ilike_contains=query),
}
