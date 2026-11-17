"""Minimal HTMX shell for OHS — React consumes horilla_api."""

from django.contrib.auth.decorators import login_required
from django.shortcuts import render
from django.utils.translation import gettext_lazy as _

from horilla.decorators import hx_request_required, permission_required


@login_required
@permission_required("ohs.view_oshevent")
def ohs_index(request):
    """Classic-UI landing; Imara UI uses /api/v1/ohs/."""
    return render(
        request,
        "ohs/index.html",
        {"title": _("Occupational Health and Safety")},
    )


@login_required
@hx_request_required
@permission_required("ohs.view_oshevent")
def ohs_index_hx(request):
    return render(
        request,
        "ohs/index.html",
        {"title": _("Occupational Health and Safety")},
    )
