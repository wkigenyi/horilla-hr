"""
Read-only JSON for the employee-profile Note, Mail Log, History, and
Work Type & Shift tabs. Mirrors HTML tab visibility and list fields;
create/edit/delete stay on the HTMX UI.
"""

from datetime import date, datetime

from django.db.models import Q
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from base.models import (
    EmailLog,
    RotatingShiftAssign,
    RotatingWorkTypeAssign,
    ShiftRequest,
    WorkTypeRequest,
)
from employee.cbv.accessibility import (
    history_accessibility,
    mail_log_accessibility,
    note_accessibility,
    workshift_accessibility,
)
from employee.history import (
    get_employee_history_models,
    get_employee_history_search,
    get_employee_model_history,
)
from employee.models import Employee, EmployeeNote
from horilla_api.api_methods.base.pagination import HorillaPageNumberPagination


def _employee_or_404(employee_id):
    return (
        Employee.objects.select_related("employee_user_id", "employee_work_info")
        .filter(pk=employee_id)
        .first()
    )


def _forbidden():
    return Response(
        {"detail": "You do not have permission to perform this action."},
        status=403,
    )


def _not_found():
    return Response({"detail": "Employee not found."}, status=404)


def _iso(value):
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    return str(value)


def _label(obj):
    if obj is None:
        return None
    return str(obj)


def _paginate(request, items):
    paginator = HorillaPageNumberPagination()
    page = paginator.paginate_queryset(items, request)
    return paginator.get_paginated_response(page)


class EmployeeNotesAPIView(APIView):
    permission_classes = [IsAuthenticated]
    http_method_names = ["get", "head", "options"]

    def get(self, request, employee_id):
        employee = _employee_or_404(employee_id)
        if employee is None:
            return _not_found()
        if not note_accessibility(request, employee):
            return _forbidden()

        notes = (
            EmployeeNote.objects.filter(employee_id=employee)
            .select_related("updated_by")
            .prefetch_related("note_files")
            .order_by("-id")
        )
        rows = []
        for note in notes:
            files = []
            for attachment in note.note_files.all():
                url = None
                try:
                    url = attachment.files.url if attachment.files else None
                except ValueError:
                    url = None
                files.append(
                    {
                        "id": attachment.id,
                        "name": str(attachment),
                        "url": url,
                    }
                )
            updated_by = note.updated_by
            rows.append(
                {
                    "id": note.id,
                    "description": note.description,
                    "created_at": _iso(note.created_at),
                    "updated_by": (
                        {
                            "id": updated_by.id,
                            "name": updated_by.get_full_name(),
                        }
                        if updated_by
                        else None
                    ),
                    "note_files": files,
                }
            )
        return _paginate(request, rows)


class EmployeeMailLogAPIView(APIView):
    permission_classes = [IsAuthenticated]
    http_method_names = ["get", "head", "options"]

    def get(self, request, employee_id):
        employee = _employee_or_404(employee_id)
        if employee is None:
            return _not_found()
        if not mail_log_accessibility(request, employee):
            return _forbidden()

        parts = []
        if employee.email:
            parts.append(Q(to__icontains=employee.email))
        work_email = getattr(
            getattr(employee, "employee_work_info", None), "email", None
        )
        if work_email:
            parts.append(Q(to__icontains=work_email))
        if not parts:
            logs = EmailLog.objects.none()
        else:
            query = parts[0]
            for part in parts[1:]:
                query |= part
            logs = EmailLog.objects.filter(query).order_by("-created_at")
        rows = [
            {
                "id": log.id,
                "subject": log.subject,
                "status": log.status,
                "to": log.to,
                "from_email": log.from_email,
                "created_at": _iso(log.created_at),
            }
            for log in logs
        ]
        return _paginate(request, rows)


def _serialize_history_entry(entry):
    return {
        "entry_key": entry.get("entry_key"),
        "model_key": entry.get("model_key"),
        "model_label": (
            str(entry["model_label"]) if entry.get("model_label") is not None else None
        ),
        "record_repr": entry.get("record_repr"),
        "history_date": _iso(entry.get("history_date")),
        "action_phrase": (
            str(entry["action_phrase"])
            if entry.get("action_phrase") is not None
            else None
        ),
        "actor_name": entry.get("actor_name"),
        "reason": entry.get("reason"),
        "changes": [
            {
                "field": change.get("field") or change.get("field_name"),
                "field_label": change.get("field_label"),
                "old_value": change.get("old_value"),
                "new_value": change.get("new_value"),
            }
            for change in (entry.get("changes") or [])
        ],
    }


class EmployeeHistoryAPIView(APIView):
    permission_classes = [IsAuthenticated]
    http_method_names = ["get", "head", "options"]

    def get(self, request, employee_id):
        employee = _employee_or_404(employee_id)
        if employee is None:
            return _not_found()
        if not history_accessibility(request, employee):
            return _forbidden()

        model_options = get_employee_history_models()
        default_model = "employee.employeeworkinformation"
        selected_model = request.GET.get("model") or default_model
        if selected_model not in {m["key"] for m in model_options}:
            selected_model = default_model

        def parse_date(value):
            try:
                return date.fromisoformat(value) if value else None
            except ValueError:
                return None

        date_from = parse_date(request.GET.get("date_from"))
        date_to = parse_date(request.GET.get("date_to"))
        sort = request.GET.get("sort") or "-date"
        if sort not in {"date", "-date"}:
            sort = "-date"
        search = (request.GET.get("search") or "").strip()

        if search:
            entries = get_employee_history_search(
                employee,
                model_options,
                search,
                date_from=date_from,
                date_to=date_to,
                sort=sort,
            )
            tracking_status = "simple_history"
        else:
            entries, tracking_status = get_employee_model_history(
                employee,
                selected_model,
                date_from=date_from,
                date_to=date_to,
                sort=sort,
            )

        rows = [_serialize_history_entry(entry) for entry in entries]
        response = _paginate(request, rows)
        # Attach feed metadata without breaking {count, results}.
        if isinstance(response.data, dict):
            response.data["model"] = selected_model
            response.data["tracking_status"] = tracking_status
        return response


def _work_shift_rows(employee_id):
    rows = []
    for req in WorkTypeRequest.objects.filter(employee_id=employee_id).select_related(
        "work_type_id", "previous_work_type_id"
    ):
        rows.append(
            {
                "id": req.id,
                "kind": "work_type_request",
                "sort_date": req.requested_date,
                "work_type": _label(req.work_type_id),
                "previous_work_type": _label(req.previous_work_type_id),
                "requested_date": _iso(req.requested_date),
                "requested_till": _iso(req.requested_till),
                "status": str(req.request_status()),
                "description": req.description,
            }
        )
    for assign in RotatingWorkTypeAssign.objects.filter(
        employee_id=employee_id
    ).select_related(
        "rotating_work_type_id", "current_work_type", "next_work_type"
    ):
        rows.append(
            {
                "id": assign.id,
                "kind": "rotating_work_type",
                "sort_date": assign.start_date,
                "rotating_work_type": _label(assign.rotating_work_type_id),
                "based_on": assign.get_based_on_display(),
                "start_date": _iso(assign.start_date),
                "current_work_type": _label(assign.current_work_type),
                "next_change_date": _iso(assign.next_change_date),
                "next_work_type": _label(assign.next_work_type),
            }
        )
    for req in ShiftRequest.objects.filter(employee_id=employee_id).select_related(
        "shift_id", "previous_shift_id", "reallocate_to"
    ):
        kind = (
            "shift_allocation"
            if req.reallocate_to_id is not None
            else "shift_request"
        )
        rows.append(
            {
                "id": req.id,
                "kind": kind,
                "sort_date": req.requested_date,
                "shift": _label(req.shift_id),
                "previous_shift": _label(req.previous_shift_id),
                "requested_date": _iso(req.requested_date),
                "requested_till": _iso(req.requested_till),
                "status": str(req.request_status()),
                "description": req.description,
                "reallocate_to": (
                    req.reallocate_to.get_full_name() if req.reallocate_to_id else None
                ),
            }
        )
    # Allocations where this employee is the reallocate target but not requester.
    for req in (
        ShiftRequest.objects.filter(reallocate_to_id=employee_id)
        .exclude(employee_id=employee_id)
        .select_related("shift_id", "previous_shift_id", "reallocate_to", "employee_id")
    ):
        rows.append(
            {
                "id": req.id,
                "kind": "shift_allocation",
                "sort_date": req.requested_date,
                "shift": _label(req.shift_id),
                "previous_shift": _label(req.previous_shift_id),
                "requested_date": _iso(req.requested_date),
                "requested_till": _iso(req.requested_till),
                "status": str(req.request_status()),
                "description": req.description,
                "reallocate_to": (
                    req.reallocate_to.get_full_name() if req.reallocate_to_id else None
                ),
            }
        )
    for assign in RotatingShiftAssign.objects.filter(
        employee_id=employee_id
    ).select_related("rotating_shift_id", "current_shift", "next_shift"):
        rows.append(
            {
                "id": assign.id,
                "kind": "rotating_shift",
                "sort_date": assign.start_date,
                "rotating_shift": _label(assign.rotating_shift_id),
                "based_on": assign.get_based_on_display(),
                "start_date": _iso(assign.start_date),
                "current_shift": _label(assign.current_shift),
                "next_change_date": _iso(assign.next_change_date),
                "next_shift": _label(assign.next_shift),
            }
        )

    rows.sort(key=lambda row: row.get("sort_date") or date.min, reverse=True)
    for row in rows:
        row.pop("sort_date", None)
    return rows


class EmployeeWorkShiftAPIView(APIView):
    permission_classes = [IsAuthenticated]
    http_method_names = ["get", "head", "options"]

    def get(self, request, employee_id):
        employee = _employee_or_404(employee_id)
        if employee is None:
            return _not_found()
        if not workshift_accessibility(request, employee):
            return _forbidden()
        return _paginate(request, _work_shift_rows(employee_id))
