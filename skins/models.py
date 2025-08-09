from django.db import models
from django.contrib.auth.models import AbstractBaseUser, BaseUserManager

# Create your models here.

class Skin(models.Model):
    name = models.CharField(max_length=1000, default="UnnamedSkin")
    link = models.URLField(unique=True)
    creator = models.CharField(max_length=1000, blank=True, null=True, default="UnknownSkinCreator")
    image_url = models.URLField(max_length=4000, blank=True, null=True, default="https://bonkleagues.io/api/avatar.svg?skinCode=CgcDYQACCQkBCgcFYWwAAQBNPlt5PUI19d8%2FGMUDPsJvGgAAAAAAAAoFAAEATT5beT1CNfXfvvn8kL80i70BAAAAAAAKBQABAEs%2BgkonQjVq%2FL2vivk9L4r5AAAAzxsPCgUAAQANP1yl2D9VbKUAAAAAAAAAAAAAAM8bDwAAAAA%3D")  # Store the extracted image URL
    created_at = models.DateTimeField(auto_now_add=True)
    description = models.TextField(blank=True, null=True)
    labels = models.JSONField(blank=True, null=True)  # Django 3.1+ uses this instead of `from contrib.postgres`
    labeled_at = models.DateTimeField(blank=True, null=True)
    upvotes = models.PositiveIntegerField(default=0)
    downvotes = models.PositiveIntegerField(default=0)
    favorited_by = models.ManyToManyField("BonkUser", related_name="favorite_skins", blank=True)


    def __str__(self):
        return f"{self.name} ({self.link})"

class BonkUserManager(BaseUserManager):
    def create_user(self, username):
        if not username:
            raise ValueError("Bonk.io username is required")
        user = self.model(username=username)
        user.set_unusable_password()  # don't store Bonk.io passwords
        user.save(using=self._db)
        return user

class BonkUser(AbstractBaseUser):
    username = models.CharField(max_length=100, unique=True)
    date_joined = models.DateTimeField(auto_now_add=True)

    objects = BonkUserManager()

    USERNAME_FIELD = 'username'

    def __str__(self):
        return self.username

class SkinVote(models.Model):
    VOTE_CHOICES = [
        ('up', 'Upvote'),
        ('down', 'Downvote'),
    ]
    user = models.ForeignKey("BonkUser", on_delete=models.CASCADE)
    skin = models.ForeignKey(Skin, on_delete=models.CASCADE)
    vote = models.CharField(max_length=4, choices=VOTE_CHOICES)

    class Meta:
        unique_together = ('user', 'skin')

    def __str__(self):
        return f"{self.user.username} voted {self.vote} on {self.skin.name}"
