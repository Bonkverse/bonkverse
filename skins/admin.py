from django.contrib import admin
from .models import Skin
from django import forms
from django.shortcuts import render
# Register your models here.


@admin.action(description="Update creator to specified name")
def bulk_update_creator(modeladmin, request, queryset):
    if 'apply' in request.POST:
        form = BulkUpdateCreatorForm(request.POST)
        if form.is_valid():
            new_creator = form.cleaned_data["new_creator"]
            count = queryset.update(creator=new_creator)
            modeladmin.message_user(request, f"Updated {count} skins.")
            return None
    else:
        form = BulkUpdateCreatorForm(initial={'_selected_action': request.POST.getlist(admin.ACTION_CHECKBOX_NAME)})

    return render(request, 'admin/bulk_update_creator.html', {
        'skins': queryset,
        'form': form,
        'title': 'Update Creator Name',
        'action': 'bulk_update_creator'
    })

class SkinAdmin(admin.ModelAdmin):
    actions = [bulk_update_creator]


class BulkUpdateCreatorForm(forms.Form):
    _selected_action = forms.CharField(widget=forms.MultipleHiddenInput)
    new_creator = forms.CharField(label="New Creator Name", max_length=255)


admin.site.register(Skin, SkinAdmin)