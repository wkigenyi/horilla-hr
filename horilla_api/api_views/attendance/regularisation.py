"""
JSON APIs for Run Payroll Review & Regularize.

Parallel to the HTMX monthly-summary calendar, conflict-resolve, and totals-sheet
import under attendance/views — same helpers and permissions, JSON payloads.
"""

import calendar
import datetime

import pandas as pd
from django.http import HttpResponse
from django.utils.translation import gettext as _
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from attendance.models import Attendance, AttendanceConflictResolution
from attendance.views.regularisation_import import (
    COLUMNS,
    COUNT_COLUMNS,
    SESSION_KEY,
    XLSX,
    _apply,
    _check,
    _decorate,
    _read,
    _stash,
    by_badge_pks,
)
from attendance.views.summary import (
    _build_calendar_context,
    _parse_date,
    approve_overtime_if_eligible,
    build_monthly_summary,
    parse_split,
)
from base.import_template_data import write_import_xlsx
from base.methods import employees_in_scope, filtersubordinatesemployeemodel
from employee.filters import EmployeeFilter
from employee.models import Employee
from horilla_api.api_decorators.base.decorators import manager_permission_required

SINGLE_RESOLUTIONS = {
    "full_present",
    "half_present",
    "half_absent",
    "partial_hours",
    "absent",
    "paid_leave",
    "unpaid_leave",
    "holiday",
    "week_off",
    "approve_ot",
    "attendance",
    "leave",
}

BULK_RESOLUTIONS = {
    "full_present",
    "half_present",
    "half_absent",
    "absent",
    "paid_leave",
    "unpaid_leave",
    "holiday",
    "week_off",
    "approve_ot",
}


def _json_value(value):
    if value is None:
        return None
    if isinstance(value, datetime.date) and not isinstance(value, datetime.datetime):
        return value.isoformat()
    if isinstance(value, datetime.datetime):
        return value.isoformat()
    if isinstance(value, datetime.time):
        return value.strftime("%H:%M:%S")
    if isinstance(value, (set, tuple)):
        return [_json_value(item) for item in value]
    if isinstance(value, list):
        return [_json_value(item) for item in value]
    if isinstance(value, dict):
        return {key: _json_value(item) for key, item in value.items()}
    if isinstance(value, Employee):
        return {
            "id": value.pk,
            "name": value.get_full_name(),
            "badge_id": value.badge_id,
        }
    return value


def calendar_payload(emp, from_date, to_date):
    """Serialize ``_build_calendar_context`` for the React client."""
    context = _build_calendar_context(emp, from_date, to_date)
    months = []
    for month in context["months"]:
        weeks = []
        for week in month["weeks"]:
            cells = []
            for cell in week:
                if cell is None:
                    cells.append(None)
                    continue
                cells.append(
                    {
                        "day": cell["day"],
                        "date": cell["date"].isoformat() if cell.get("date") else None,
                        "status": cell["status"],
                        "detail": cell.get("detail") or "",
                        "conflict_with": cell.get("conflict_with"),
                        "resolution": cell.get("resolution"),
                        "is_conflict": bool(cell.get("is_conflict")),
                        "future_part": _json_value(cell.get("future_part")),
                        "conflict_reason": cell.get("conflict_reason") or "",
                        "ot_kind": cell.get("ot_kind"),
                        "ot_pending": bool(cell.get("ot_pending")),
                        "hours_second": cell.get("hours_second") or 0,
                        "hours_label": cell.get("hours_label") or "",
                        "show_hours": bool(cell.get("show_hours")),
                        "is_hours_edited": bool(cell.get("is_hours_edited")),
                        "halves": list(cell.get("halves") or ()),
                        "groups": cell.get("groups") or "",
                        "halves_data": cell.get("halves_data") or "",
                        "split_label": cell.get("split_label") or "",
                    }
                )
            weeks.append(cells)
        months.append({"label": month["label"], "weeks": weeks})

    return {
        "employee": _json_value(emp),
        "from_date": from_date.isoformat(),
        "to_date": to_date.isoformat(),
        "months": months,
        "cal_summary": _json_value(context["cal_summary"]),
        "total_days": context["total_days"],
    }


def _period_from_data(data, defaults=True):
    today = datetime.date.today()
    default_from = today.replace(day=1) if defaults else None
    default_to = (
        today.replace(day=calendar.monthrange(today.year, today.month)[1])
        if defaults
        else None
    )
    from_date = _parse_date(data.get("from_date"), default_from)
    to_date = _parse_date(data.get("to_date"), default_to)
    if from_date and to_date and from_date > to_date:
        from_date, to_date = to_date, from_date
    return from_date, to_date


def _employee_ids_from(source):
    """Support repeated params, comma-separated strings, and JSON lists."""
    if hasattr(source, "getlist"):
        raw = source.getlist("employee_ids")
        if not raw and source.get("employee_ids") is not None:
            raw = [source.get("employee_ids")]
    else:
        value = source.get("employee_ids")
        if value is None:
            raw = []
        elif isinstance(value, (list, tuple)):
            raw = list(value)
        else:
            raw = [value]

    ids = []
    for item in raw:
        if item is None:
            continue
        text = str(item).strip()
        if not text:
            continue
        for part in text.split(","):
            part = part.strip()
            if part.isdigit():
                ids.append(int(part))
    return ids


def _template_scope(request):
    """Employees and period for the totals-sheet template (mirrors classic ``_scope``)."""
    source = request.query_params
    from_date, to_date = _period_from_data(source, defaults=True)
    selected = _employee_ids_from(source)
    employees = (
        Employee.objects.filter(pk__in=selected)
        if selected
        else EmployeeFilter(request.GET).qs
    )
    employees = filtersubordinatesemployeemodel(
        request, employees, "attendance.view_attendance"
    )
    return employees, from_date, to_date


def _load_employee(emp_id):
    if emp_id is None or str(emp_id).strip() == "":
        return None
    try:
        return Employee.objects.get(pk=emp_id)
    except (Employee.DoesNotExist, ValueError, TypeError):
        return None


def _apply_single_resolution(emp, date, resolution, conflict_type=""):
    if resolution in SINGLE_RESOLUTIONS or parse_split(resolution):
        AttendanceConflictResolution._base_manager.update_or_create(
            employee_id=emp,
            date=date,
            defaults={"resolution": resolution, "conflict_type": conflict_type or ""},
        )
        if resolution == "approve_ot":
            approve_overtime_if_eligible(emp, [date])
        return True
    if resolution == "clear":
        obj = AttendanceConflictResolution.objects.filter(
            employee_id=emp, date=date
        ).first()
        if obj:
            if obj.resolution == "approve_ot":
                Attendance.objects.filter(
                    employee_id=emp, attendance_date=date
                ).update(attendance_overtime_approve=False)
            obj.delete()
        return True
    return False


def _apply_bulk_resolution(emp, dates, resolution):
    if resolution == "approve_ot":
        approve_overtime_if_eligible(emp, dates)
        return True
    if resolution in BULK_RESOLUTIONS or parse_split(resolution):
        for day in dates:
            AttendanceConflictResolution._base_manager.update_or_create(
                employee_id=emp,
                date=day,
                defaults={"resolution": resolution, "conflict_type": ""},
            )
        return True
    return False


def _pending_brief(employee, counts, note, computed_row):
    dates = computed_row.get("unresolved_conflict_dates") or []
    return {
        "employee_id": employee.pk,
        "employee_name": employee.get_full_name(),
        "badge_id": employee.badge_id,
        "counts": counts,
        "note": note or "",
        "unresolved_conflicts": computed_row.get("unresolved_conflicts", 0),
        "unresolved_conflict_dates": [
            d.isoformat() if hasattr(d, "isoformat") else str(d) for d in dates
        ],
    }


class MonthlySummaryCalendarAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        emp_id = request.query_params.get("employee_id")
        from_date, to_date = _period_from_data(request.query_params, defaults=True)
        if not from_date or not to_date:
            return Response(
                {"from_date": [_("Enter a valid from_date and to_date.")]},
                status=400,
            )
        if not emp_id:
            return Response({"employee_id": [_("Employee is required.")]}, status=400)
        if not employees_in_scope(
            request, [emp_id], "attendance.view_attendance", include_self=True
        ):
            return Response({"detail": _("Permission denied.")}, status=403)
        emp = _load_employee(emp_id)
        if emp is None:
            return Response({"employee_id": [_("Employee not found.")]}, status=404)
        return Response(calendar_payload(emp, from_date, to_date), status=200)


class MonthlySummaryConflictResolveAPIView(APIView):
    permission_classes = [IsAuthenticated]

    @manager_permission_required("attendance.change_attendance")
    def post(self, request):
        data = request.data
        emp_id = data.get("employee_id")
        date = _parse_date(data.get("date"), None)
        from_date, to_date = _period_from_data(data, defaults=True)
        resolution = data.get("resolution")
        conflict_type = data.get("conflict_type") or ""

        errors = {}
        if not emp_id:
            errors["employee_id"] = [_("Employee is required.")]
        if date is None:
            errors["date"] = [_("Enter a valid date.")]
        if not resolution:
            errors["resolution"] = [_("Resolution is required.")]
        if errors:
            return Response(errors, status=400)

        if not employees_in_scope(request, [emp_id], "attendance.change_attendance"):
            return Response({"detail": _("Permission denied.")}, status=403)

        emp = _load_employee(emp_id)
        if emp is None:
            return Response({"employee_id": [_("Employee not found.")]}, status=404)

        if not _apply_single_resolution(emp, date, resolution, conflict_type):
            return Response(
                {
                    "resolution": [
                        _("Unknown resolution. Use a calendar resolution or clear.")
                    ]
                },
                status=400,
            )

        return Response(calendar_payload(emp, from_date, to_date), status=200)


class MonthlySummaryConflictBulkResolveAPIView(APIView):
    permission_classes = [IsAuthenticated]

    @manager_permission_required("attendance.change_attendance")
    def post(self, request):
        data = request.data
        emp_id = data.get("employee_id")
        from_date, to_date = _period_from_data(data, defaults=True)
        resolution = data.get("resolution")
        raw_dates = data.get("dates") or []
        if isinstance(raw_dates, str):
            raw_dates = [part.strip() for part in raw_dates.split(",") if part.strip()]

        errors = {}
        if not emp_id:
            errors["employee_id"] = [_("Employee is required.")]
        if not resolution:
            errors["resolution"] = [_("Resolution is required.")]
        dates = sorted(
            {d for d in (_parse_date(v, None) for v in raw_dates) if d is not None}
        )
        if not dates:
            errors["dates"] = [_("Select at least one valid date.")]
        if errors:
            return Response(errors, status=400)

        if not employees_in_scope(request, [emp_id], "attendance.change_attendance"):
            return Response({"detail": _("Permission denied.")}, status=403)

        emp = _load_employee(emp_id)
        if emp is None:
            return Response({"employee_id": [_("Employee not found.")]}, status=404)

        if not _apply_bulk_resolution(emp, dates, resolution):
            return Response(
                {"resolution": [_("Unknown or unsupported bulk resolution.")]},
                status=400,
            )

        return Response(calendar_payload(emp, from_date, to_date), status=200)


class MonthlySummaryRegularisationTemplateAPIView(APIView):
    permission_classes = [IsAuthenticated]

    @manager_permission_required("attendance.change_attendance")
    def get(self, request):
        employees, from_date, to_date = _template_scope(request)
        period_days = (to_date - from_date).days + 1
        rows, _total_working, _totals = build_monthly_summary(
            from_date, to_date, employees
        )

        sheet = pd.DataFrame(
            [
                {
                    "Badge ID": row["employee"].badge_id or "",
                    "Employee": str(row["employee"]),
                    "Present": row["present"],
                    "Paid Leave": row["paid_leave"],
                    "Unpaid Leave": row["unpaid_leave"],
                    "Absent": row["absent"],
                    "Week Off": row["week_off"],
                    "Holiday": row["holiday"],
                    "Total": None,
                    "Working Days": row["working_days"],
                    "Conflicts": row["unresolved_conflicts"],
                    "Reason": "",
                }
                for row in rows
            ],
            columns=COLUMNS,
        )

        notes = pd.DataFrame(
            {
                "Column": [*COUNT_COLUMNS, "Week Off", "Holiday", "Total", "Conflicts"],
                "Editable": ["yes"] * len(COUNT_COLUMNS) + ["no", "no", "no", "no"],
                "Notes": [
                    str(_("Days present. Half days count as 0.5.")),
                    str(_("Days of approved paid leave.")),
                    str(_("Days of approved unpaid leave.")),
                    str(_("Working days with nothing recorded.")),
                    str(_("From the roster. Change the roster, not this.")),
                    str(_("From the company calendar.")),
                    str(
                        _(
                            "Adds up the day columns as you type. Every day of "
                            "the period belongs in one of those columns, so this "
                            "should equal the days in the period."
                        )
                    ),
                    str(
                        _(
                            "Days with both attendance and leave. Stating the "
                            "totals settles them."
                        )
                    ),
                ],
            }
        )

        response = HttpResponse(content_type=XLSX)
        name = f"attendance_summary_{from_date:%Y%m%d}_{to_date:%Y%m%d}.xlsx"
        response["Content-Disposition"] = f'attachment; filename="{name}"'
        with pd.ExcelWriter(response, engine="xlsxwriter") as writer:
            sheet.to_excel(writer, sheet_name="Summary", index=False)
            notes.to_excel(writer, sheet_name="How to fill this in", index=False)
            _decorate(writer, len(sheet), period_days)
        return response


class MonthlySummaryRegularisationImportAPIView(APIView):
    permission_classes = [IsAuthenticated]

    @manager_permission_required("attendance.change_attendance")
    def post(self, request):
        upload = request.FILES.get("file") or request.FILES.get("regularisation_file")
        if upload is None:
            return Response({"file": [_("Choose a file to import.")]}, status=400)

        frame = _read(upload)
        if frame is None:
            return Response({"file": [_("That file could not be read.")]}, status=400)

        period_from = _parse_date(request.data.get("from_date"), None)
        period_to = _parse_date(request.data.get("to_date"), None)
        if not period_from or not period_to:
            return Response(
                {
                    "from_date": [_("The period this sheet covers was not given.")],
                    "to_date": [_("The period this sheet covers was not given.")],
                },
                status=400,
            )
        if period_from > period_to:
            period_from, period_to = period_to, period_from

        period_days = (period_to - period_from).days + 1

        if "Badge ID" not in frame.columns:
            return Response({"file": [_("The file has no Badge ID column.")]}, status=400)
        if not any(column in frame.columns for column in COUNT_COLUMNS):
            return Response(
                {
                    "file": [
                        _("The file has none of these columns: %(cols)s")
                        % {"cols": ", ".join(COUNT_COLUMNS)}
                    ]
                },
                status=400,
            )

        badges = [
            str(v).strip()
            for v in frame["Badge ID"]
            if v is not None and str(v).strip() and str(v).strip().lower() != "nan"
        ]
        visible = filtersubordinatesemployeemodel(
            request,
            Employee.objects.filter(badge_id__in=badges),
            "attendance.view_attendance",
        )
        by_badge = {employee.badge_id: employee for employee in visible}

        counted_rows, _working, _totals = build_monthly_summary(
            period_from,
            period_to,
            Employee.objects.filter(pk__in=by_badge_pks(by_badge)),
        )
        computed = {row["employee"].pk: row for row in counted_rows}

        applied, failures, failure_rows = [], [], []
        for position, record in enumerate(frame.to_dict("records"), start=2):
            employee, counts, note, reason = _check(
                record, by_badge, period_days, computed
            )
            if reason:
                failures.append(
                    {
                        "row": position,
                        "badge_id": str(record.get("Badge ID") or "").strip(),
                        "problem": str(reason),
                    }
                )
                failure_rows.append({**record, "Row": position, "Problem": str(reason)})
            elif employee is not None:
                applied.append((employee, counts, note))

        if failures:
            # Prefer structured JSON for Imara; attach a workbook when asked.
            wants_workbook = "application/vnd.openxmlformats" in (
                request.headers.get("Accept") or ""
            )
            if wants_workbook:
                response = HttpResponse(content_type=XLSX)
                response["Content-Disposition"] = (
                    'attachment; filename="summary_errors.xlsx"'
                )
                write_import_xlsx(pd.DataFrame(failure_rows), response)
                return response
            return Response(
                {"errors": failures, "failed_count": len(failures)},
                status=400,
            )

        pending_conflicts = [
            _pending_brief(employee, counts, note, computed[employee.pk])
            for employee, counts, note in applied
            if computed.get(employee.pk, {}).get("unresolved_conflicts", 0)
        ]

        if pending_conflicts:
            _stash(request, period_from, period_to, applied)
            return Response(
                {
                    "needs_confirm": True,
                    "from_date": period_from.isoformat(),
                    "to_date": period_to.isoformat(),
                    "pending": pending_conflicts,
                    "applied_count": 0,
                },
                status=200,
            )

        _apply(applied, period_from, period_to)
        return Response(
            {
                "applied_count": len(applied),
                "settled_conflicts": 0,
                "from_date": period_from.isoformat(),
                "to_date": period_to.isoformat(),
            },
            status=200,
        )


class MonthlySummaryRegularisationConfirmAPIView(APIView):
    permission_classes = [IsAuthenticated]

    @manager_permission_required("attendance.change_attendance")
    def post(self, request):
        data = request.data
        if data.get("cancel"):
            request.session.pop(SESSION_KEY, None)
            return Response({"applied_count": 0, "cancelled": True}, status=200)

        if not data.get("confirm") and data.get("pending") is None:
            return Response(
                {"confirm": [_("Set confirm to true, or pass pending rows.")]},
                status=400,
            )

        explicit = data.get("pending")
        if explicit is not None:
            return self._confirm_explicit(request, data, explicit)

        pending = request.session.get(SESSION_KEY)
        if not pending:
            return Response(
                {"detail": [_("Nothing is waiting to be confirmed.")]},
                status=400,
            )

        period_from = datetime.date.fromisoformat(pending["from_date"])
        period_to = datetime.date.fromisoformat(pending["to_date"])
        by_pk = {row["pk"]: row for row in pending["rows"]}

        employees = filtersubordinatesemployeemodel(
            request,
            Employee.objects.filter(pk__in=by_pk),
            "attendance.view_attendance",
        )
        rows, _working, _totals = build_monthly_summary(
            period_from, period_to, employees
        )
        applied = [
            (
                row["employee"],
                by_pk[row["employee"].pk]["counts"],
                by_pk[row["employee"].pk]["note"],
            )
            for row in rows
            if row["employee"].pk in by_pk
        ]
        settled = sum(
            1 for row in rows if row["employee"].pk in by_pk and row["unresolved_conflicts"]
        )

        request.session.pop(SESSION_KEY, None)
        _apply(applied, period_from, period_to)
        return Response(
            {
                "applied_count": len(applied),
                "settled_conflicts": settled,
                "from_date": period_from.isoformat(),
                "to_date": period_to.isoformat(),
            },
            status=200,
        )

    def _confirm_explicit(self, request, data, explicit):
        if not isinstance(explicit, list) or not explicit:
            return Response({"pending": [_("Nothing to confirm.")]}, status=400)

        period_from = _parse_date(data.get("from_date"), None)
        period_to = _parse_date(data.get("to_date"), None)
        if not period_from or not period_to:
            # Fall back to a previously stashed period when the client only
            # echoes pending rows from the import response.
            stashed = request.session.get(SESSION_KEY) or {}
            period_from = period_from or _parse_date(stashed.get("from_date"), None)
            period_to = period_to or _parse_date(stashed.get("to_date"), None)
        if not period_from or not period_to:
            return Response(
                {
                    "from_date": [_("The period this sheet covers was not given.")],
                    "to_date": [_("The period this sheet covers was not given.")],
                },
                status=400,
            )

        employee_ids = []
        for item in explicit:
            emp_id = item.get("employee_id") if isinstance(item, dict) else item
            if emp_id is not None:
                employee_ids.append(emp_id)

        if not employees_in_scope(
            request, employee_ids, "attendance.change_attendance"
        ):
            return Response({"detail": _("Permission denied.")}, status=403)

        by_id = {
            emp.pk: emp
            for emp in filtersubordinatesemployeemodel(
                request,
                Employee.objects.filter(pk__in=employee_ids),
                "attendance.view_attendance",
            )
        }

        applied = []
        for item in explicit:
            if not isinstance(item, dict):
                continue
            emp = by_id.get(item.get("employee_id"))
            if emp is None:
                continue
            counts = item.get("counts") or {}
            note = item.get("note") or ""
            applied.append((emp, counts, note))

        if not applied:
            return Response({"pending": [_("No in-scope employees to apply.")]}, status=400)

        # Re-count so settled_conflicts reflects what the override will clear.
        rows, _w, _t = build_monthly_summary(
            period_from,
            period_to,
            Employee.objects.filter(pk__in=[emp.pk for emp, _c, _n in applied]),
        )
        by_row = {row["employee"].pk: row for row in rows}
        settled = sum(
            by_row.get(emp.pk, {}).get("unresolved_conflicts", 0)
            for emp, _c, _n in applied
        )

        request.session.pop(SESSION_KEY, None)
        _apply(applied, period_from, period_to)
        return Response(
            {
                "applied_count": len(applied),
                "settled_conflicts": settled,
                "from_date": period_from.isoformat(),
                "to_date": period_to.isoformat(),
            },
            status=200,
        )
