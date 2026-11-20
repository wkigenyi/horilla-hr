"""
Tenant-scoped JWT authentication for the API.

Why this exists
---------------
Tenant scoping in this project rests on a ContextVar: ``CompanyMiddleware``
resolves the caller's company and calls ``set_selected_company()``, and
``HorillaCompanyManager.get_queryset()`` reads it on every query.

That works for session-authenticated web requests. It does not apply on the
API path, because of ordering:

    MIDDLEWARE          -> CompanyMiddleware runs here, sees AnonymousUser
    view dispatch       -> DRF resolves the JWT here, user becomes known

``CompanyMiddleware._handle()`` returns early for unauthenticated requests, so
a token-authenticated request reaches the view with the ContextVar unset, and
``HorillaCompanyManager`` applies no company predicate when it is unset::

    if not filter_path or not company:
        return qs          # no company context -> no predicate added

This class sets the ContextVar at the moment the user is resolved, which is
the earliest point the company is knowable on a tokened request, so the API
path gets the same manager-level scoping the web path already has.

Superuser company switch
------------------------
Classic web uses ``request.session["selected_company"]``. JWT has no session
equivalent; superusers may send ``X-Horilla-Company: <id|all>`` on each
authenticated call instead. Non-superusers' headers are ignored.

Scope
-----
This establishes the *manager-level* default scoping only. Per-viewset
``get_queryset`` filtering is still worth adding, because a manager default
can be bypassed by ``_base_manager``, ``entire()`` or raw SQL.
"""

from __future__ import annotations

import logging

from django.utils.translation import gettext_lazy as _
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework_simplejwt.authentication import JWTAuthentication

from horilla.horilla_middlewares import set_selected_company

logger = logging.getLogger(__name__)

COMPANY_HEADER = "X-Horilla-Company"


def resolve_company_id(user):
    """The company a tokened request should be scoped to, or None.

    Mirrors ``CompanyMiddleware._get_user_default_company``: the employee's
    work-information company. Superusers are left unscoped by default
    (tenant-wide / "all"), matching the web path; they may narrow via
    ``X-Horilla-Company`` (see ``apply_company_header``).
    """
    if user is None or not user.is_authenticated:
        return None
    if user.is_superuser:
        return None
    # Query the work-info row rather than traversing user.employee_get:
    # the reverse OneToOne is cached on the user instance, so a user object
    # loaded before its work info was written keeps returning a stale (or
    # null) company. A direct query cannot go stale, and it is one indexed
    # lookup either way.
    try:
        from employee.models import EmployeeWorkInformation

        return (
            EmployeeWorkInformation.objects.filter(
                employee_id__employee_user_id=user.pk
            )
            .values_list("company_id", flat=True)
            .first()
        )
    except Exception:
        # No employee record, no work info, or the app is unavailable.
        # Callers must read None as "cannot place this user", never as
        # "no restriction needed".
        logger.exception("Could not resolve company for user_id=%s", user.pk)
        return None


def _header_value(request):
    """Read ``X-Horilla-Company`` from a Django or DRF request."""
    headers = getattr(request, "headers", None)
    if headers is not None:
        raw = headers.get(COMPANY_HEADER)
        if raw is not None:
            return raw.strip()
    meta = getattr(request, "META", None) or {}
    return (meta.get("HTTP_X_HORILLA_COMPANY") or "").strip()


def apply_company_header(user, request):
    """Apply ``X-Horilla-Company`` for superusers; ignore for everyone else.

    Values:
      - omitted / empty: leave ContextVar as already set (unscoped for
        superusers; work-info company for others)
      - ``all``: leave unset / treat as all companies (superuser only)
      - decimal company id: ``set_selected_company(<id>)`` when the row exists

    Unknown or non-decimal values raise ``ValidationError`` (HTTP 400).
    Non-superusers sending the header are ignored so older clients do not
    break.
    """
    raw = _header_value(request)
    if not raw or not getattr(user, "is_superuser", False):
        return

    if raw == "all":
        # Explicit all: ensure managers stay unscoped even if something set
        # a company earlier on this request.
        set_selected_company(None)
        return

    if not raw.isdigit():
        raise ValidationError({"detail": _("Invalid company.")})

    from base.models import Company

    company_id = int(raw)
    if not Company.objects.filter(pk=company_id).exists():
        raise ValidationError({"detail": _("Unknown company.")})
    set_selected_company(company_id)


def attach_audit_actor(user):
    """Name ``user`` as the actor on audit log entries for this request.

    ``AuditlogMiddleware`` reads ``request.user`` once, while the middleware
    runs, and a tokened request is still anonymous at that point. Without this
    every change made through the API was logged with no actor, so the audit
    trail could say a wage changed but not who changed it. The middleware's
    context is a plain dict held for the whole request, so filling in the
    actor here reaches every entry the view writes.
    """
    try:
        from auditlog.context import auditlog_value

        context = auditlog_value.get()
    except (ImportError, LookupError):
        # Outside the middleware (management commands, tests calling the
        # view directly): nothing to attach to.
        return
    if isinstance(context, dict) and context.get("actor") is None:
        context["actor"] = user


class TenantScopedJWTAuthentication(JWTAuthentication):
    """JWTAuthentication that also establishes tenant scope.

    DRF calls ``authenticate()`` during view dispatch, after all middleware.
    Setting the ContextVar here means every queryset built by the view -- and
    by anything it calls -- is company-filtered, without each of the 333
    endpoints having to remember.

    ``CompanyMiddleware.__call__`` resets the ContextVar in a ``finally``, so
    the value set here does not outlive the request even though it is set
    later in the cycle.
    """

    def authenticate(self, request):
        result = super().authenticate(request)
        if result is None:
            # No credentials offered; leave scope unset. DRF's IsAuthenticated
            # rejects the request before any queryset is built.
            return None

        user, validated_token = result
        attach_audit_actor(user)
        company_id = resolve_company_id(user)
        if company_id is not None:
            set_selected_company(company_id)
        elif not user.is_superuser:
            # None means "cannot place this user", never "no restriction".
            # Proceeding would run HorillaCompanyManager with no predicate.
            logger.warning(
                "API request from user_id=%s has no resolvable company; refusing",
                getattr(user, "pk", None),
            )
            raise PermissionDenied(_("This account is not assigned to a company."))

        # Superuser may narrow (or reaffirm all) via the request header.
        # Non-superuser headers are ignored inside apply_company_header.
        apply_company_header(user, request)
        return user, validated_token
