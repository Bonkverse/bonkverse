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
    InviteError.INVALID_CODE: "❌ Invalid Discord invite format.",
    InviteError.NOT_FOUND: "❌ Invalid or inaccessible Discord invite.",
    InviteError.RATE_LIMITED: "❌ Couldn't reach Discord right now. Try again in a minute.",
    InviteError.UNAVAILABLE: "❌ Couldn't reach Discord right now. Try again in a minute.",
}

# What people see when the server can't be added, by outcome.
REFUSAL_MESSAGES = {
    SubmitOutcome.MISSING_INVITE: "❌ Discord invite link is required.",
    SubmitOutcome.INVALID_FORMAT: "❌ Invalid Discord invite format.",
    SubmitOutcome.NO_SERVER: "❌ Could not determine Discord server from invite.",
    SubmitOutcome.NOT_PERMANENT: "❌ Invite must be permanent (non-expiring).",
}


@require_POST
@limit("submit")
def submit_server(request):
    result = submit(request.POST.get("invite", ""), request.POST.getlist("tags"))

    if result.outcome == SubmitOutcome.LOOKUP_FAILED:
        messages.error(request, LOOKUP_FAILURE_MESSAGES[result.lookup_error])
        return redirect("submit_server")
    if result.outcome in REFUSAL_MESSAGES:
        messages.error(request, REFUSAL_MESSAGES[result.outcome])
        return redirect("submit_server")

    if result.outcome == SubmitOutcome.ALREADY_LISTED:
        messages.warning(request, "⚠️ This Discord server has already been submitted.")
    else:
        messages.success(request, "✅ Discord server submitted successfully!")
    return redirect(reverse("detail", kwargs={"server_id": result.server.id}))
