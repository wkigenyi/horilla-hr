from django.urls import reverse
from django.utils.translation import gettext_lazy as _

MENU = _("OHS")
IMG_SRC = "images/ui/headset-solid.svg"

SUBMENUS = [
    {
        "menu": _("Overview"),
        "redirect": reverse("ohs-index"),
        "accessibility": "ohs.sidebar.ohs_accessibility",
    },
]


def ohs_accessibility(request, submenu, user_perms, *args, **kwargs):
    return request.user.has_perm("ohs.view_oshevent") or request.user.has_perm(
        "ohs.view_oshworkplace"
    )
