# skins/report_skin.py
from django.http import JsonResponse
from django.views.decorators.http import require_POST
from django.shortcuts import get_object_or_404
from .models import Skin, SkinReport


@require_POST
def report_skin(request, skin_id: int):
    skin   = get_object_or_404(Skin, id=skin_id)
    reason  = request.POST.get('reason', '').strip()
    details = request.POST.get('details', '').strip()

    valid_reasons = {r[0] for r in SkinReport.REASON_CHOICES}
    if reason not in valid_reasons:
        return JsonResponse({'ok': False, 'error': 'invalid_reason'}, status=400)

    reporter = request.user if request.user.is_authenticated else None

    # Prevent duplicate reports from the same authenticated user
    if reporter:
        if SkinReport.objects.filter(skin=skin, reporter=reporter).exists():
            return JsonResponse({'ok': False, 'error': 'already_reported'}, status=409)

    SkinReport.objects.create(
        skin=skin,
        reporter=reporter,
        reason=reason,
        details=details[:1000],  # cap to avoid abuse
    )

    return JsonResponse({'ok': True})