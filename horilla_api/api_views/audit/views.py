"""
Audit trail API: who changed what, and when.

Reads the django-auditlog ``LogEntry`` rows that ``horilla_audit.registry``
writes for tracked models (pay, people, leave, attendance and payroll runs)
and returns them with readable field names and values, so the React client
does not need to know model internals.

Two ways in:

* ``GET /audit/entries/`` -- the whole trail, filtered. Needs the
  "View audit trail" permission (``auditlog.view_logentry``); superusers have
  it implicitly.
* The same endpoint with ``model`` and ``object_id`` -- one record's history.
  Anyone who may view that kind of record (``<app>.view_<model>``) may read
  its history, so a payroll officer sees a run's approvals without being
  granted the whole trail.

Values are returned raw (ISO dates, plain numbers) with a ``kind`` so the
client formats dates in the company format and money with its currency
component.
"""

from datetime import datetime, time

from auditlog.models import LogEntry
from django.contrib.auth import get_user_model
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import FieldDoesNotExist
from django.db import models
from django.db.models import Q
from django.utils import timezone
from django.utils.dateparse import parse_date
from django.utils.translation import gettext_lazy as _
from rest_framework.pagination import PageNumberPagination
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

AUDIT_PERMISSION = "auditlog.view_logentry"

# Records whose screens are guarded by another model's permission. A payroll
# run is opened with "view payslip", so its history is too.
RECORD_VIEW_PERMISSIONS = {
    "payroll.payrollbatch": "payroll.view_payslip",
}

ACTIONS = {
    LogEntry.Action.CREATE: ("create", _("Created")),
    LogEntry.Action.UPDATE: ("update", _("Changed")),
    LogEntry.Action.DELETE: ("delete", _("Deleted")),
    LogEntry.Action.ACCESS: ("access", _("Viewed")),
}
ACTION_BY_KEY = {key: value for value, (key, _label) in ACTIONS.items()}

# Screen names for each area, in Imara's words rather than app labels.
AREA_LABELS = {
    "employee": _("People"),
    "payroll": _("Payroll"),
    "leave": _("Leave"),
    "attendance": _("Attendance"),
    "base": _("Organisation"),
    "recruitment": _("Recruitment"),
    "onboarding": _("Onboarding"),
    "offboarding": _("Offboarding"),
    "asset": _("Assets"),
    "helpdesk": _("Helpdesk"),
    "pms": _("Performance"),
    "project": _("Projects"),
    "ohs": _("Health and safety"),
}

# Bookkeeping columns every save rewrites. Showing them buries the change a
# person actually made.
HIDDEN_FIELDS = {
    "id",
    "created_at",
    "created_by",
    "modified_by",
    "modified_at",
    "updated_at",
    "history_set",
    "history",
}

# Number fields in payroll that are not money.
_NOT_MONEY_HINTS = (
    "rate",
    "percent",
    "count",
    "days",
    "hours",
    "divisor",
    "period",
    "sequence",
    "order",
    "year",
    "month",
)

# Fields a scheduled job recalculates on its own. A system update that changed
# only these says nothing an auditor asks about, and there are thousands of
# them: the experience job saves every work record every four hours. They are
# hidden with ``routine=hide``; an update by a person, or one that also changed
# a real field, always shows.
ROUTINE_FIELDS = {
    "employee.employeeworkinformation": {"experience"},
}

MAX_PAGE_SIZE = 100


class AuditPagination(PageNumberPagination):
    page_size = 25
    page_size_query_param = "page_size"
    max_page_size = MAX_PAGE_SIZE


def _model_key(content_type):
    return f"{content_type.app_label}.{content_type.model}"


def _model_label(content_type):
    model = content_type.model_class()
    if model is None:
        return content_type.model.replace("_", " ").capitalize()
    return str(model._meta.verbose_name).capitalize()


def _area(content_type):
    label = AREA_LABELS.get(content_type.app_label)
    if label is None:
        label = content_type.app_label.replace("_", " ").capitalize()
    return {"key": content_type.app_label, "label": str(label)}


def _content_type_from_key(raw):
    """``payroll.payrollbatch`` -> ContentType, or None."""
    if not raw or "." not in raw:
        return None
    app_label, model = raw.lower().split(".", 1)
    return ContentType.objects.filter(app_label=app_label, model=model).first()


def _person(user):
    """Display name for an actor: the employee's name, else the login."""
    if user is None:
        return None
    employee = getattr(user, "employee_get", None)
    name = None
    if employee is not None:
        name = " ".join(
            part
            for part in (employee.employee_first_name, employee.employee_last_name)
            if part
        ).strip()
    return {
        "id": user.pk,
        "name": name or user.get_full_name() or user.get_username(),
        "employee_id": getattr(employee, "pk", None),
    }


def _value_kind(field):
    if field is None:
        return "text"
    if isinstance(field, models.BooleanField):
        return "boolean"
    if isinstance(field, models.DateTimeField):
        return "datetime"
    if isinstance(field, models.DateField):
        return "date"
    if isinstance(field, (models.FloatField, models.DecimalField)):
        name = field.name.lower()
        if field.model._meta.app_label == "payroll" and not any(
            hint in name for hint in _NOT_MONEY_HINTS
        ):
            return "money"
        return "number"
    if isinstance(field, (models.IntegerField,)) and not field.is_relation:
        return "number"
    return "text"


def _clean(value):
    """auditlog stores the string "None" for an empty value."""
    if value is None or value == "None":
        return None
    return value


class _Resolver:
    """Turns stored raw values into what a person reads, per page of entries.

    Foreign keys are stored as primary keys; they are looked up once per
    model for the whole page rather than once per change.
    """

    def __init__(self, entries):
        self.wanted = {}
        self.names = {}
        for entry in entries:
            model = entry.content_type.model_class()
            if model is None:
                continue
            for field_name, change in self._changes(entry):
                field = self._field(model, field_name)
                if field is not None and field.many_to_one:
                    target = field.related_model
                    for value in change:
                        value = _clean(value)
                        if value is not None:
                            self.wanted.setdefault(target, set()).add(str(value))
        for target, keys in self.wanted.items():
            # _base_manager: a record can be renamed or moved company after
            # the change; the trail still names it.
            for obj in target._base_manager.filter(pk__in=list(keys)):
                self.names[(target, str(obj.pk))] = str(obj)

    @staticmethod
    def _changes(entry):
        changes = entry.changes if isinstance(entry.changes, dict) else {}
        for field_name, change in changes.items():
            if field_name in HIDDEN_FIELDS:
                continue
            if isinstance(change, (list, tuple)) and len(change) == 2:
                yield field_name, change

    @staticmethod
    def _field(model, field_name):
        try:
            return model._meta.get_field(field_name)
        except FieldDoesNotExist:
            return None

    def display(self, field, value):
        value = _clean(value)
        if value is None or field is None:
            return value
        if field.choices:
            for choice_value, choice_label in field.flatchoices:
                if str(choice_value) == str(value):
                    return str(choice_label)
            return value
        if field.many_to_one:
            return self.names.get((field.related_model, str(value)), value)
        if isinstance(field, models.BooleanField):
            return value in (True, "True", "true", "1")
        if isinstance(field, (models.FloatField, models.DecimalField)):
            try:
                return float(value)
            except (TypeError, ValueError):
                return value
        if isinstance(field, models.DateTimeField):
            return str(value).replace(" ", "T")
        if isinstance(field, models.DateField):
            return str(value)[:10]
        return value

    def changes(self, entry):
        model = entry.content_type.model_class()
        out = []
        raw_changes = entry.changes if isinstance(entry.changes, dict) else {}
        for field_name, change in raw_changes.items():
            if field_name in HIDDEN_FIELDS:
                continue
            field = self._field(model, field_name) if model else None
            if field is not None and field.auto_created and not field.concrete:
                # A reverse relation (another table pointing here), which
                # auditlog sometimes serialises as a placeholder string.
                continue
            label = (
                str(field.verbose_name).capitalize()
                if field is not None and hasattr(field, "verbose_name")
                else field_name.replace("_", " ").capitalize()
            )
            if isinstance(change, dict) and change.get("type") == "m2m":
                # Many-to-many: {"type": "m2m", "operation": "add", "objects": [...]}
                objects = [str(item) for item in change.get("objects") or []]
                adding = change.get("operation") == "add"
                out.append(
                    {
                        "field": field_name,
                        "label": label,
                        "kind": "list",
                        "old": None if adding else objects,
                        "new": objects if adding else None,
                        "operation": change.get("operation"),
                    }
                )
                continue
            if not (isinstance(change, (list, tuple)) and len(change) == 2):
                continue
            old, new = change
            # A create logs every field going from nothing to its first value;
            # empty ones say nothing.
            if (
                entry.action == LogEntry.Action.CREATE
                and _clean(old) is None
                and _clean(new) in (None, "")
            ):
                continue
            out.append(
                {
                    "field": field_name,
                    "label": label,
                    "kind": _value_kind(field),
                    "old": self.display(field, old),
                    "new": self.display(field, new),
                }
            )
        return out


def _entry_payload(entry, resolver):
    action_key, action_label = ACTIONS.get(entry.action, ("update", _("Changed")))
    content_type = entry.content_type
    return {
        "id": entry.pk,
        # Company time, as the rest of the API returns it.
        "timestamp": timezone.localtime(entry.timestamp).isoformat()
        if entry.timestamp
        else None,
        "action": action_key,
        "action_label": str(action_label),
        "area": _area(content_type),
        "model": _model_key(content_type),
        "model_label": _model_label(content_type),
        "object_id": entry.object_id
        if entry.object_id is not None
        else entry.object_pk,
        "object_repr": entry.object_repr,
        "actor": _person(entry.actor),
        # None when the change came from the system (a scheduled job, an
        # import) rather than a signed-in person.
        "actor_email": entry.actor_email or None,
        "remote_addr": entry.remote_addr,
        "changes": resolver.changes(entry),
    }


def _company_scope(user, queryset):
    """Entries a non-superuser may see under company scoping.

    LogEntry has no company. An entry is in scope when its record is still
    visible through the model's company-scoped manager, or when the person
    who made it belongs to the viewer's company (which keeps deletes, whose
    record is gone, in the trail).
    """
    if user.is_superuser:
        return queryset
    from horilla_api.authentication import resolve_company_id

    company_id = resolve_company_id(user)
    if company_id is None:
        return queryset.none()

    visible = Q(
        actor__employee_get__employee_work_info__company_id=company_id,
    )
    content_type_ids = queryset.values_list("content_type_id", flat=True).distinct()
    for content_type in ContentType.objects.filter(pk__in=list(content_type_ids)):
        model = content_type.model_class()
        if model is None:
            continue
        visible |= Q(
            content_type=content_type,
            object_id__in=model.objects.values("pk"),
        )
    return queryset.filter(visible)


def _routine_updates():
    """System updates whose only meaningful change is a ROUTINE_FIELDS field."""
    routine = Q(pk__in=[])
    for model_key, fields in ROUTINE_FIELDS.items():
        content_type = _content_type_from_key(model_key)
        model = content_type.model_class() if content_type else None
        if model is None:
            continue
        # Changes are keyed by field name; foreign keys may use the column name.
        other_fields = set()
        for field in model._meta.concrete_fields:
            other_fields.update({field.name, field.attname})
        other_fields -= fields | HIDDEN_FIELDS
        routine |= (
            Q(
                content_type=content_type,
                action=LogEntry.Action.UPDATE,
                actor__isnull=True,
                changes__has_any_keys=sorted(fields),
            )
            & ~Q(changes__has_any_keys=sorted(other_fields))
        )
    return routine


def _parse_day(raw, end=False):
    day = parse_date(raw) if raw else None
    if day is None:
        return None
    moment = datetime.combine(day, time.max if end else time.min)
    return timezone.make_aware(moment) if timezone.is_naive(moment) else moment


class AuditEntryListView(APIView):
    """
    GET /api/v1/audit/entries/

    Filters (all optional):
      area       app label, e.g. ``payroll``
      model      ``app_label.model``, e.g. ``payroll.payrollbatch``
      object_id  with ``model``: one record's history
      actor      user id
      action     create | update | delete
      field      only entries that changed this field, e.g. ``wage``
      routine    ``hide`` leaves out system recalculations (ROUTINE_FIELDS)
      date_from, date_to   YYYY-MM-DD, inclusive
      search     record name or the person's email
      page, page_size (max 100)
    """

    permission_classes = [IsAuthenticated]

    def get(self, request):
        params = request.query_params
        user = request.user
        queryset = LogEntry.objects.select_related(
            "content_type", "actor", "actor__employee_get"
        ).order_by("-timestamp", "-pk")

        content_type = None
        if params.get("model"):
            content_type = _content_type_from_key(params["model"])
            if content_type is None:
                return Response({"model": [_("Unknown record type.")]}, status=400)
            queryset = queryset.filter(content_type=content_type)

        object_id = (params.get("object_id") or "").strip()
        single_record = bool(content_type and object_id)

        if single_record:
            # One record's history: enough to be allowed to view that record.
            model = content_type.model_class()
            view_perm = RECORD_VIEW_PERMISSIONS.get(
                _model_key(content_type),
                f"{content_type.app_label}.view_{content_type.model}",
            )
            if not (user.has_perm(AUDIT_PERMISSION) or user.has_perm(view_perm)):
                return Response(
                    {"detail": _("You do not have permission to view this history.")},
                    status=403,
                )
            if (
                model is not None
                and not user.has_perm(AUDIT_PERMISSION)
                and object_id.isdigit()
                and not model.objects.filter(pk=int(object_id)).exists()
            ):
                # The record must be one the viewer can see (company scoping).
                return Response({"detail": _("Not found.")}, status=404)
            queryset = queryset.filter(object_pk=object_id)
        elif not user.has_perm(AUDIT_PERMISSION):
            return Response(
                {"detail": _("You do not have permission to view the audit trail.")},
                status=403,
            )

        if params.get("area"):
            queryset = queryset.filter(content_type__app_label=params["area"].lower())
        if params.get("actor"):
            if not params["actor"].isdigit():
                return Response({"actor": [_("Unknown person.")]}, status=400)
            queryset = queryset.filter(actor_id=int(params["actor"]))
        if params.get("action"):
            action = ACTION_BY_KEY.get(params["action"].lower())
            if action is None:
                return Response({"action": [_("Unknown action.")]}, status=400)
            queryset = queryset.filter(action=action)
        if params.get("field"):
            queryset = queryset.filter(changes__has_key=params["field"])
        if (params.get("routine") or "").lower() == "hide":
            queryset = queryset.exclude(_routine_updates())
        start = _parse_day(params.get("date_from"))
        if start:
            queryset = queryset.filter(timestamp__gte=start)
        end = _parse_day(params.get("date_to"), end=True)
        if end:
            queryset = queryset.filter(timestamp__lte=end)
        search = (params.get("search") or "").strip()
        if search:
            queryset = queryset.filter(
                Q(object_repr__icontains=search) | Q(actor_email__icontains=search)
            )

        if not single_record:
            queryset = _company_scope(user, queryset)

        paginator = AuditPagination()
        page = paginator.paginate_queryset(queryset, request, view=self)
        resolver = _Resolver(page)
        return paginator.get_paginated_response(
            [_entry_payload(entry, resolver) for entry in page]
        )


class AuditFiltersView(APIView):
    """
    GET /api/v1/audit/filters/

    The choices the audit trail screen offers: areas and record types that
    have entries, and the people who made changes.
    """

    permission_classes = [IsAuthenticated]

    def get(self, request):
        user = request.user
        if not user.has_perm(AUDIT_PERMISSION):
            return Response(
                {"detail": _("You do not have permission to view the audit trail.")},
                status=403,
            )
        queryset = _company_scope(user, LogEntry.objects.all())
        content_type_ids = set(
            queryset.values_list("content_type_id", flat=True).distinct()
        )
        record_types = []
        areas = {}
        for content_type in ContentType.objects.filter(pk__in=content_type_ids):
            area = _area(content_type)
            areas[area["key"]] = area
            record_types.append(
                {
                    "value": _model_key(content_type),
                    "label": _model_label(content_type),
                    "area": area["key"],
                }
            )
        actor_ids = set(
            queryset.exclude(actor__isnull=True)
            .values_list("actor_id", flat=True)
            .distinct()
        )
        people = [
            _person(actor)
            for actor in get_user_model()
            .objects.filter(pk__in=actor_ids)
            .select_related("employee_get")
        ]
        return Response(
            {
                "areas": sorted(areas.values(), key=lambda item: item["label"]),
                "record_types": sorted(record_types, key=lambda item: item["label"]),
                "people": sorted(people, key=lambda item: item["name"].lower()),
                "actions": [
                    {"value": key, "label": str(label)}
                    for key, label in (value for value in ACTIONS.values())
                    if key != "access"
                ],
            }
        )
