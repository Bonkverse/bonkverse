from django.conf import settings
from django.db import models
from django.contrib.postgres.indexes import GinIndex
from django.contrib.postgres.search import SearchVector, SearchVectorField
import uuid
from django.urls import reverse

from core.validators import validate_bonk_username


# SKIN_SEARCH_CONFIG: the text-search language Skin.search_vector is built
# with; every SearchQuery against it must use the same one.
from .querysets import SKIN_SEARCH_CONFIG, SkinQuerySet


class Skin(models.Model):
    name = models.CharField(max_length=1000, default="UnnamedSkin")
    link = models.URLField(
        blank=True,
        null=True,
        help_text="Legacy external source (e.g. Bonkleagues import)",
    )
    creator = models.CharField(max_length=1000, blank=True, null=True, default="UnknownSkinCreator")
    image_url = models.URLField(
        max_length=4000,
        blank=True,
        null=True,
        default="https://bonkleagues.io/api/avatar.svg?skinCode=CgcDYQACCQkBCgcFYWwAAQBNPlt5PUI19d8%2FGMUDPsJvGgAAAAAAAAoFAAEATT5beT1CNfXfvvn8kL80i70BAAAAAAAKBQABAEs%2BgkonQjVq%2FL2vivk9L4r5AAAAzxsPCgUAAQANP1yl2D9VbKUAAAAAAAAAAAAAAM8bDwAAAAA%3D",
    )  # Store the extracted image URL
    skin_code = models.TextField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    description = models.TextField(blank=True, null=True)
    labels = models.JSONField(
        blank=True, null=True
    )  # Django 3.1+ uses this instead of `from contrib.postgres`
    labeled_at = models.DateTimeField(blank=True, null=True)
    upvotes = models.PositiveIntegerField(default=0)
    downvotes = models.PositiveIntegerField(default=0)
    favorited_by = models.ManyToManyField(
        settings.AUTH_USER_MODEL, related_name="favorite_skins", blank=True
    )
    uuid = models.UUIDField(default=uuid.uuid4, editable=False, unique=True)

    # Full-text search data, kept up to date by Postgres on every insert/update.
    # Same fields and weights the search page always used; storing it lets a GIN
    # index find matches instead of rebuilding this for every row on every search.
    search_vector = models.GeneratedField(
        expression=(
            SearchVector("labels", weight="A", config=SKIN_SEARCH_CONFIG)
            + SearchVector("description", weight="A", config=SKIN_SEARCH_CONFIG)
            + SearchVector("name", weight="B", config=SKIN_SEARCH_CONFIG)
            + SearchVector("creator", weight="C", config=SKIN_SEARCH_CONFIG)
        ),
        output_field=SearchVectorField(),
        db_persist=True,
    )

    objects = SkinQuerySet.as_manager()

    class Meta:
        indexes = [
            # Relevance search: full-text match.
            GinIndex(fields=["search_vector"], name="skin_search_vector_gin"),
            # Fuzzy name match (pg_trgm `%`) and name mode (`ilike_contains`).
            GinIndex(fields=["name"], opclasses=["gin_trgm_ops"], name="skin_name_trgm"),
            # name / creator / description modes (`ilike_contains`, core/lookups.py).
            GinIndex(fields=["creator"], opclasses=["gin_trgm_ops"], name="skin_creator_trgm"),
            GinIndex(
                fields=["description"], opclasses=["gin_trgm_ops"], name="skin_description_trgm"
            ),
            # Newest sort, New Releases, and the "added today" header count.
            models.Index(fields=["-created_at"], name="skin_created_at_desc"),
        ]

    def __str__(self):
        return f"{self.name} ({self.link})"

    def get_absolute_url(self):
        return reverse("skin_detail", kwargs={"skin_id": self.id})


class SkinVote(models.Model):
    VOTE_CHOICES = [
        ("up", "Upvote"),
        ("down", "Downvote"),
    ]
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    skin = models.ForeignKey(Skin, on_delete=models.CASCADE)
    vote = models.CharField(max_length=4, choices=VOTE_CHOICES)

    class Meta:
        unique_together = ("user", "skin")

    def __str__(self):
        return f"{self.user.username} voted {self.vote} on {self.skin.name}"


class SkinImage(models.Model):
    skin = models.ForeignKey("skins.Skin", on_delete=models.CASCADE, related_name="images")
    kind = models.CharField(max_length=50, default="original")
    path = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.kind} image for {self.skin.name}"


# Old migrations (0016) import the validator by this path; keep it.
validate_username = validate_bonk_username


class SkinReport(models.Model):
    REASON_CHOICES = [
        ("inappropriate", "Inappropriate content"),
        ("stolen", "Stolen / reposted without credit"),
        ("spam", "Spam or low-effort"),
        ("broken", "Broken / not loading"),
        ("other", "Other"),
    ]

    skin = models.ForeignKey(Skin, on_delete=models.CASCADE, related_name="reports")
    reporter = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="skin_reports",
    )  # null = anonymous report
    reason = models.CharField(max_length=32, choices=REASON_CHOICES)
    details = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    resolved = models.BooleanField(default=False)

    class Meta:
        # One report per user per skin (authenticated users only)
        constraints = [
            models.UniqueConstraint(
                fields=["skin", "reporter"],
                condition=models.Q(reporter__isnull=False),
                name="one_report_per_user_per_skin",
            )
        ]

    def __str__(self):
        return f"Report on {self.skin.name} ({self.reason})"
