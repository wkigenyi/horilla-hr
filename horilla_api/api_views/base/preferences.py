"""
System Preferences and color themes over JWT.

The web page at ``/settings/system-preferences-view/`` reads and writes a
handful of per-company rows. Token requests have no session company, so the
scope is the one ``TenantScopedJWTAuthentication`` already established: the
employee's own company, or every company when the caller is a superuser
(the web page's "All companies").
"""

from django.apps import apps
from django.conf import settings
from django.utils.translation import gettext_lazy as _
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from accessibility.accessibility import ACCESSBILITY_FEATURE
from accessibility.models import DefaultAccessibility
from base.models import (
    AnnouncementExpire,
    Company,
    CompanyLanguageSetting,
    DefaultExportPermission,
    DynamicPagination,
)
from employee.models import EmployeeGeneralSetting, ProfileEditFeature
from horilla.__version__ import __version__
from horilla_api.authentication import resolve_company_id
from horilla_audit.forms import HistoryTrackingFieldsForm
from horilla_audit.models import AccountBlockUnblock, HistoryTrackingFields

DATE_FORMAT_DEFAULT = "MMM. D, YYYY"
TIME_FORMAT_DEFAULT = "hh:mm A"


def bind_request_user(request):
    """Model saves read the Django request on the thread, which middleware
    authenticated before the JWT existed. Point that request at the caller."""
    django_request = request._request
    if not getattr(django_request, "user", None) or not django_request.user.is_authenticated:
        django_request.user = request.user
    return django_request


def preference_company(user):
    """Company these settings belong to, or None for all companies."""
    company_id = resolve_company_id(user)
    if company_id is None:
        return None
    return Company.objects.filter(pk=company_id).first()


def _allowed(user, perm):
    return user.has_perm(perm)


def _first(model, **lookup):
    return model.objects.filter(**lookup).first()


def _get_or_create(model, lookup, defaults=None):
    instance = model.objects.filter(**lookup).first()
    if instance is not None:
        return instance
    payload = dict(lookup)
    payload.update(defaults or {})
    return model.objects.create(**payload)


def _integer(value, minimum):
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, str):
        text = value.strip()
        if not text or not text.lstrip("-").isdigit():
            return None
        value = int(text)
    if isinstance(value, int) and value >= minimum:
        return value
    return None


def _flag(value):
    if isinstance(value, bool):
        return value
    return None


def tracking_field_choices():
    form = HistoryTrackingFieldsForm()
    return [
        {"name": name, "label": str(label)}
        for name, label in form.fields["tracking_fields"].choices
    ]


def _date_choices():
    return list(settings.HORILLA_DATE_FORMATS.keys())


def _time_choices():
    return list(settings.HORILLA_TIME_FORMATS.keys())


def _language_choices():
    return [{"code": code, "label": str(label)} for code, label in settings.LANGUAGES]


def _display_company(company):
    """The company whose date and time format the page shows.

    With all companies selected the web page shows the first company and,
    on save, writes the choice onto every company.
    """
    if company is not None:
        return company
    return Company.objects.order_by("id").first()


def build_preferences(user):
    company = preference_company(user)
    payload = {
        "company_id": company.id if company else None,
        "company_is_all": company is None,
        "version": __version__,
    }

    general = {}
    if _allowed(user, "base.change_announcementexpire"):
        expire = _first(AnnouncementExpire, company_id=company)
        general["expire_days"] = {
            "value": expire.days if expire and expire.days is not None else 30,
            "writable": True,
        }
    if _allowed(user, "base.view_dynamicpagination"):
        paging = _first(DynamicPagination, user_id=user, company_id=company)
        general["records_per_page"] = {
            "value": paging.pagination if paging else 50,
            "writable": True,
        }
    if general:
        payload["general"] = general

    formatting = {}
    if _allowed(user, "employee.change_employeegeneralsetting"):
        prefix = _first(EmployeeGeneralSetting, company_id=company)
        formatting["badge_prefix"] = {
            "value": prefix.badge_id_prefix if prefix else "PEP",
            "writable": _allowed(user, "employee.add_employeegeneralsetting")
            or _allowed(user, "employee.change_employeegeneralsetting"),
        }
    if apps.is_installed("payroll") and _allowed(user, "payroll.view_payrollsettings"):
        from payroll.models.tax_models import PayrollSettings

        payroll = _first(PayrollSettings, company_id=company)
        formatting["currency"] = {
            "symbol": (payroll.currency_symbol if payroll else None) or "$",
            "position": (payroll.position if payroll else None) or "postfix",
            "positions": ["prefix", "postfix"],
            "writable": _allowed(user, "payroll.change_payrollsettings"),
        }
    if _allowed(user, "base.view_company"):
        shown = _display_company(company)
        formatting["date_format"] = {
            "value": (shown.date_format if shown and shown.date_format else None)
            or DATE_FORMAT_DEFAULT,
            "choices": _date_choices(),
            "writable": _allowed(user, "base.change_company"),
        }
        formatting["time_format"] = {
            "value": (shown.time_format if shown and shown.time_format else None)
            or TIME_FORMAT_DEFAULT,
            "choices": _time_choices(),
            "writable": _allowed(user, "base.change_company"),
        }
    if formatting:
        payload["formatting"] = formatting

    access = {}
    if _allowed(user, "horilla_audit.view_accountblockunblock"):
        blocked = _first(AccountBlockUnblock)
        access["restrict_login"] = {
            "value": bool(blocked and blocked.is_enabled),
            "writable": _allowed(user, "horilla_audit.change_accountblockunblock"),
        }
        profile = _first(ProfileEditFeature)
        access["restrict_profile_edit"] = {
            "value": bool(profile and profile.is_enabled),
            "writable": _allowed(user, "employee.change_employee"),
        }
    if _allowed(user, "horilla_audit.view_historytrackingfields"):
        tracking = HistoryTrackingFields.for_settings_ui(company)
        access["work_info_tracking"] = {
            "enabled": bool(tracking.work_info_track),
            "fields": tracking.tracked_field_names(),
            "choices": tracking_field_choices(),
            "writable": _allowed(user, "horilla_audit.change_historytrackingfields"),
        }
    if _allowed(user, "base.view_defaultexportpermission"):
        export = _first(DefaultExportPermission, company_id=company)
        access["export_access"] = {
            "value": export is None or bool(export.is_enabled),
            "writable": _allowed(user, "base.change_defaultexportpermission"),
        }
    if access:
        payload["access"] = access

    if _allowed(user, "base.view_companylanguagesetting"):
        language = _first(CompanyLanguageSetting, company_id=company)
        enabled = list(language.enabled_languages or []) if language else ["en"]
        payload["languages"] = {
            "enabled": enabled,
            "choices": _language_choices(),
            "writable": _allowed(user, "base.change_companylanguagesetting"),
        }
    return payload


def _reject(errors):
    return errors or None


def apply_preferences(user, data):
    """Apply a partial update. Returns a field-error dict, or None."""
    if not isinstance(data, dict):
        return {"error": [_("Send a JSON object.")]}
    company = preference_company(user)
    errors = {}

    general = data.get("general") or {}
    formatting = data.get("formatting") or {}
    access = data.get("access") or {}
    if not isinstance(general, dict) or not isinstance(formatting, dict) or not isinstance(access, dict):
        return {"error": [_("Each section must be an object.")]}

    if "expire_days" in general:
        if not _allowed(user, "base.change_announcementexpire"):
            errors["expire_days"] = [_("You cannot change announcement expiry.")]
        else:
            days = _integer(general.get("expire_days"), 0)
            if days is None:
                errors["expire_days"] = [_("Enter a whole number of days.")]
            else:
                row = _get_or_create(AnnouncementExpire, {"company_id": company})
                row.days = days
                row.save()

    if "records_per_page" in general:
        if not _allowed(user, "base.view_dynamicpagination"):
            errors["records_per_page"] = [_("You cannot change records per page.")]
        else:
            size = _integer(general.get("records_per_page"), 1)
            if size is None:
                errors["records_per_page"] = [_("Enter a whole number of records.")]
            else:
                row = _get_or_create(
                    DynamicPagination,
                    {"user_id": user, "company_id": company},
                    {"pagination": size},
                )
                # DynamicPagination.save() overwrites the user from the thread
                # request. The row is already owned by this caller.
                DynamicPagination.objects.filter(pk=row.pk).update(pagination=size)

    if "badge_prefix" in formatting:
        if not (
            _allowed(user, "employee.add_employeegeneralsetting")
            or _allowed(user, "employee.change_employeegeneralsetting")
        ):
            errors["badge_prefix"] = [_("You cannot change the badge prefix.")]
        else:
            prefix = formatting.get("badge_prefix")
            prefix = prefix.strip() if isinstance(prefix, str) else ""
            if not prefix or len(prefix) > 5:
                errors["badge_prefix"] = [_("Enter a prefix of 1 to 5 characters.")]
            else:
                row = _get_or_create(
                    EmployeeGeneralSetting,
                    {"company_id": company},
                    {"badge_id_prefix": prefix},
                )
                row.badge_id_prefix = prefix
                row.save()

    if "currency" in formatting:
        currency = formatting.get("currency")
        if not apps.is_installed("payroll") or not _allowed(user, "payroll.change_payrollsettings"):
            errors["currency"] = [_("You cannot change the currency.")]
        elif not isinstance(currency, dict):
            errors["currency"] = [_("Send a symbol and a position.")]
        else:
            symbol = currency.get("symbol")
            symbol = symbol.strip() if isinstance(symbol, str) else ""
            position = currency.get("position")
            if len(symbol) > 5:
                errors["currency"] = [_("The symbol can be at most 5 characters.")]
            elif position not in ("prefix", "postfix"):
                errors["currency"] = [_("Choose prefix or suffix.")]
            else:
                from payroll.models.tax_models import PayrollSettings

                row = _get_or_create(
                    PayrollSettings,
                    {"company_id": company},
                    {"currency_symbol": symbol or "$", "position": position},
                )
                row.currency_symbol = symbol or "$"
                row.position = position
                row.save()

    if "date_format" in formatting or "time_format" in formatting:
        if not _allowed(user, "base.change_company"):
            if "date_format" in formatting:
                errors["date_format"] = [_("You cannot change the date format.")]
            if "time_format" in formatting:
                errors["time_format"] = [_("You cannot change the time format.")]
        else:
            date_format = formatting.get("date_format", None)
            time_format = formatting.get("time_format", None)
            if "date_format" in formatting and date_format not in settings.HORILLA_DATE_FORMATS:
                errors["date_format"] = [_("Choose a date format from the list.")]
            if "time_format" in formatting and time_format not in settings.HORILLA_TIME_FORMATS:
                errors["time_format"] = [_("Choose a time format from the list.")]
            if "date_format" not in errors and "time_format" not in errors:
                targets = Company.objects.all() if company is None else Company.objects.filter(pk=company.pk)
                updates = {}
                if "date_format" in formatting:
                    updates["date_format"] = date_format
                if "time_format" in formatting:
                    updates["time_format"] = time_format
                targets.update(**updates)

    if "restrict_login" in access:
        enabled = _flag(access.get("restrict_login"))
        if not _allowed(user, "horilla_audit.change_accountblockunblock"):
            errors["restrict_login"] = [_("You cannot change login restriction.")]
        elif enabled is None:
            errors["restrict_login"] = [_("Choose on or off.")]
        else:
            row = _first(AccountBlockUnblock)
            if row is None:
                AccountBlockUnblock.objects.create(is_enabled=enabled)
            else:
                row.is_enabled = enabled
                row.save()

    if "restrict_profile_edit" in access:
        enabled = _flag(access.get("restrict_profile_edit"))
        if not _allowed(user, "employee.change_employee"):
            errors["restrict_profile_edit"] = [_("You cannot change profile editing.")]
        elif enabled is None:
            errors["restrict_profile_edit"] = [_("Choose on or off.")]
        else:
            _set_profile_edit(enabled)

    if "work_info_tracking" in access:
        tracking = access.get("work_info_tracking")
        if not _allowed(user, "horilla_audit.change_historytrackingfields"):
            errors["work_info_tracking"] = [_("You cannot change work information tracking.")]
        elif not isinstance(tracking, dict):
            errors["work_info_tracking"] = [_("Send the tracking switch and the field list.")]
        else:
            enabled = _flag(tracking.get("enabled"))
            names = tracking.get("fields")
            allowed_names = {choice["name"] for choice in tracking_field_choices()}
            if enabled is None:
                errors["work_info_tracking"] = [_("Choose on or off.")]
            elif not isinstance(names, list) or any(name not in allowed_names for name in names):
                errors["work_info_tracking"] = [_("Choose tracking fields from the list.")]
            else:
                HistoryTrackingFields.apply_settings(
                    work_info_track=enabled,
                    field_names=names,
                    company=company,
                    assign_company_ids=HistoryTrackingFields.assigned_company_ids()
                    if company is None
                    else None,
                    update_fields=True,
                )

    if "export_access" in access:
        enabled = _flag(access.get("export_access"))
        if not _allowed(user, "base.change_defaultexportpermission"):
            errors["export_access"] = [_("You cannot change export access.")]
        elif enabled is None:
            errors["export_access"] = [_("Choose on or off.")]
        else:
            row = _get_or_create(
                DefaultExportPermission, {"company_id": company}, {"is_enabled": enabled}
            )
            row.is_enabled = enabled
            row.save()

    if "languages" in data:
        if not _allowed(user, "base.change_companylanguagesetting"):
            errors["languages"] = [_("You cannot change languages.")]
        else:
            incoming = data.get("languages")
            codes = incoming.get("enabled") if isinstance(incoming, dict) else incoming
            known = {code for code, _label in settings.LANGUAGES}
            if not isinstance(codes, list) or any(code not in known for code in codes):
                errors["languages"] = [_("Choose languages from the list.")]
            else:
                row = _get_or_create(
                    CompanyLanguageSetting,
                    {"company_id": company},
                    {"enabled_languages": codes},
                )
                row.enabled_languages = codes
                row.save()

    return _reject(errors)


def _set_profile_edit(enabled):
    row = _first(ProfileEditFeature)
    if row is None:
        ProfileEditFeature.objects.create(is_enabled=enabled)
    else:
        row.is_enabled = enabled
        row.save()
    feature = DefaultAccessibility.objects.filter(feature="profile_edit").first()
    if enabled and feature is None:
        DefaultAccessibility.objects.create(
            feature="profile_edit", filter={"feature": ["profile_edit"]}
        )
    elif not enabled and feature is not None:
        feature.delete()
    if enabled:
        if not any(item[0] == "profile_edit" for item in ACCESSBILITY_FEATURE):
            ACCESSBILITY_FEATURE.append(("profile_edit", _("Profile Edit Access")))
    elif ACCESSBILITY_FEATURE and ACCESSBILITY_FEATURE[-1][0] == "profile_edit":
        ACCESSBILITY_FEATURE.pop()


def _lighten(hex_color, amount=0.28):
    text = hex_color.lstrip("#")
    channels = [int(text[index : index + 2], 16) for index in (0, 2, 4)]
    mixed = [round(channel + (255 - channel) * amount) for channel in channels]
    return "#{:02x}{:02x}{:02x}".format(*mixed)


def _darken(hex_color, amount=0.82):
    text = hex_color.lstrip("#")
    channels = [int(text[index : index + 2], 16) for index in (0, 2, 4)]
    mixed = [round(channel * (1 - amount)) for channel in channels]
    return "#{:02x}{:02x}{:02x}".format(*mixed)


def theme_payload(theme, active_id, default_id):
    accent = theme.primary_600
    return {
        "id": theme.id,
        "name": theme.name,
        "description": theme.description,
        "is_default": theme.id == default_id,
        "is_active": theme.id == active_id,
        "preview": [
            theme.primary_100,
            theme.primary_300,
            theme.primary_500,
            theme.primary_600,
            theme.primary_800,
        ],
        "accent": accent,
        "accent_dark": _lighten(accent),
        "accent_foreground": "#ffffff",
        "accent_dark_foreground": _darken(accent),
    }


def active_theme_for(company):
    from horilla_theme.models import CompanyTheme, HorillaColorTheme

    if company is None:
        return HorillaColorTheme.get_default_theme()
    return CompanyTheme.get_theme_for_company(company)


class SystemPreferencesAPIView(APIView):
    """Read and update the System Preferences page for the caller's company."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        bind_request_user(request)
        return Response(build_preferences(request.user))

    def patch(self, request):
        bind_request_user(request)
        errors = apply_preferences(request.user, request.data)
        if errors:
            return Response(errors, status=400)
        return Response(build_preferences(request.user))


class ColorThemeListAPIView(APIView):
    """Preset color themes, and which one this company is using."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        if not apps.is_installed("horilla_theme"):
            return Response(status=404)
        if not _allowed(request.user, "horilla_theme.view_horillacolortheme"):
            return Response({"error": _("You cannot view color themes.")}, status=403)
        from horilla_theme.models import HorillaColorTheme

        company = preference_company(request.user)
        active = active_theme_for(company)
        default = HorillaColorTheme.get_default_theme()
        active_id = active.id if active else None
        default_id = default.id if default else None
        return Response(
            {
                "company_is_all": company is None,
                "themes": [
                    theme_payload(theme, active_id, default_id)
                    for theme in HorillaColorTheme.objects.all()
                ],
            }
        )


class ColorThemeActivateAPIView(APIView):
    """Apply a preset to the caller's company."""

    permission_classes = [IsAuthenticated]

    def post(self, request):
        if not apps.is_installed("horilla_theme"):
            return Response(status=404)
        if not _allowed(request.user, "horilla_theme.change_horillacolortheme"):
            return Response({"error": _("You cannot change the color theme.")}, status=403)
        company = preference_company(request.user)
        if company is None:
            return Response({"error": _("No active company found")}, status=400)
        theme_id = request.data.get("theme_id") if isinstance(request.data, dict) else None
        from horilla_theme.models import CompanyTheme, HorillaColorTheme

        theme = HorillaColorTheme.objects.filter(pk=theme_id).first()
        if theme is None:
            return Response({"error": _("Theme not found")}, status=404)
        CompanyTheme.objects.update_or_create(company=company, defaults={"theme": theme})
        return Response(theme_payload(theme, theme.id, _default_id()))


class ColorThemeDefaultAPIView(APIView):
    """Toggle the login-page default. Only the all-companies scope may do this."""

    permission_classes = [IsAuthenticated]

    def post(self, request):
        if not apps.is_installed("horilla_theme"):
            return Response(status=404)
        if not _allowed(request.user, "horilla_theme.add_horillacolortheme"):
            return Response({"error": _("You cannot change the login theme.")}, status=403)
        if preference_company(request.user) is not None:
            return Response(
                {"error": _("Select all companies to change the login default.")},
                status=400,
            )
        theme_id = request.data.get("theme_id") if isinstance(request.data, dict) else None
        from horilla_theme.models import HorillaColorTheme

        theme = HorillaColorTheme.objects.filter(pk=theme_id).first()
        if theme is None:
            return Response({"error": _("Theme not found")}, status=404)
        theme.is_default = not theme.is_default
        theme.save()
        default = HorillaColorTheme.get_default_theme()
        return Response(theme_payload(theme, None, default.id if default else None))


def _default_id():
    from horilla_theme.models import HorillaColorTheme

    default = HorillaColorTheme.get_default_theme()
    return default.id if default else None
