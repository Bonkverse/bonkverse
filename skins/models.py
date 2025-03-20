from django.db import models

# Create your models here.

class Skin(models.Model):
    name = models.CharField(max_length=1000)
    link = models.URLField(unique=True)
    creator = models.CharField(max_length=1000, blank=True, null=True)
    image_url = models.URLField(blank=True, null=True)  # Store the extracted image URL

    def __str__(self):
        return f"{self.name} ({self.link})"
