from django.contrib.auth.decorators import login_required
from django.shortcuts import render, get_object_or_404, redirect
from django.shortcuts import render
from django.http import HttpResponseRedirect
from django.urls import reverse
from .models import Skin
from django.core.paginator import Paginator

@login_required
def my_profile(request):
    user = request.user
    user_skins = Skin.objects.filter(creator__iexact=user.username)
    paginator = Paginator(user_skins, 20)
    page_number = request.GET.get("page", 1)
    page_obj = paginator.get_page(page_number)

    return render(request, 'skins/my_profile.html', {
        'skins': page_obj,
        'user': user
    })


@login_required
def edit_skin(request, skin_id):
    skin = get_object_or_404(Skin, id=skin_id)
    
    if skin.creator != request.user.username:
        return redirect('my_profile')

    if request.method == 'POST':
        new_name = request.POST.get('name', '').strip()
        if new_name:
            skin.name = new_name
            skin.save()

        # Make sure referer is a valid fallback
        referer = request.POST.get('referer') or request.META.get('HTTP_REFERER') or reverse('my_profile')
        return redirect(referer)

    # For GET request, pass referer into context
    referer = request.META.get('HTTP_REFERER', reverse('my_profile'))
    return render(request, 'skins/edit_skin.html', {
        'skin': skin,
        'referer': referer
    })


@login_required
def delete_skin(request, skin_id):
    skin = get_object_or_404(Skin, id=skin_id)
    if skin.creator == request.user.username:
        skin.delete()
    return redirect('my_profile')
