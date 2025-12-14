import time
from celery import shared_task
from django.utils import timezone
from skins.models import DiscordServer, DiscordServerSnapshot
from skins.discord_invite import fetch_invite, parse_invite_payload

@shared_task(bind=True, autoretry_for=(Exception,), retry_backoff=30, retry_kwargs={"max_retries": 3})
def refresh_discord_servers(self):
    servers = DiscordServer.objects.filter(status=DiscordServer.Status.ACTIVE)

    REQUESTS_PER_SECOND = 40  # stay under 50 safely
    DELAY = 1 / REQUESTS_PER_SECOND

    for server in servers:
        try:
            payload = fetch_invite(server.invite_code)
            data = parse_invite_payload(payload)

            server.member_count = data["member_count"]
            server.online_count = data["online_count"]
            server.last_fetched_at = timezone.now()
            server.save(update_fields=["member_count", "online_count", "last_fetched_at"])

            DiscordServerSnapshot.objects.create(
                server=server,
                member_count=server.member_count,
                online_count=server.online_count,
            )

            time.sleep(DELAY)

        except Exception as e:
            # log + continue (never kill the batch)
            print(f"[Discord refresh failed] {server.name}: {e}")
