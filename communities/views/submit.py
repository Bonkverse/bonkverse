"""The submit form's POST: hands the invite to the service and tells the
person what happened (a message, then the server's page or back to the form).
"""

from django.contrib import messages
from django.shortcuts import redirect
from django.urls import reverse
from django.views.decorators.http import require_POST

from core.ratelimits import limit
from integrations.discord_api import InviteError

from ..services import SubmitOutcome, submit_server as submit

# What people see when the invite lookup fails, by InviteError code.
LOOKUP_FAILURE_MESSAGES = {
    InviteError.INVALID_CODE: "That isn't a Discord invite link. It looks like https://discord.gg/abc123.",
    InviteError.NOT_FOUND: "Discord doesn't know that invite. Check the link, or make a new one.",
    InviteError.RATE_LIMITED: "Discord didn't answer. Try again in a minute.",
    InviteError.UNAVAILABLE: "Discord didn't answer. Try again in a minute.",
}

# What people see when the server can't be added, by outcome.
REFUSAL_MESSAGES = {
    SubmitOutcome.MISSING_INVITE: "Paste an invite link to submit a server.",
    SubmitOutcome.INVALID_FORMAT: "That isn't a Discord invite link. It looks like https://discord.gg/abc123.",
    SubmitOutcome.NO_SERVER: "That invite doesn't lead to a server.",
    SubmitOutcome.NOT_PERMANENT: "That invite expires. In Discord, make one set to never expire.",
}


@require_POST
@limit("submit")
def submit_server(request):
    result = submit(request.POST.get("invite", ""), request.POST.getlist("tags"))

    if result.outcome == SubmitOutcome.LOOKUP_FAILED:
        messages.error(request, LOOKUP_FAILURE_MESSAGES[result.lookup_error])
        return redirect("communities:submit_server")
    if result.outcome in REFUSAL_MESSAGES:
        messages.error(request, REFUSAL_MESSAGES[result.outcome])
        return redirect("communities:submit_server")

    if result.outcome == SubmitOutcome.ALREADY_LISTED:
        messages.warning(request, "That server is already in the directory.")
    else:
        messages.success(request, "Server added to the directory.")
    return redirect(reverse("communities:detail", kwargs={"server_id": result.server.id}))
