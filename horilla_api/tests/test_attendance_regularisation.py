"""JSON APIs for Run Payroll attendance regularisation."""

import datetime
from io import BytesIO

import pandas as pd
from django.contrib.auth.models import Permission
from django.contrib.contenttypes.models import ContentType
from django.test import TestCase
from rest_framework.test import APIClient

from attendance.models import (
    Attendance,
    AttendanceConflictResolution,
    AttendanceSummaryOverride,
)
from attendance.views.summary import build_monthly_summary
from employee.models import Employee
from horilla.testkit import make_company, make_employee, make_user
from leave.models import LeaveRequest, LeaveType

FROM_DATE = datetime.date(2026, 4, 1)
TO_DATE = datetime.date(2026, 4, 30)
CALENDAR = "/api/v1/attendance/monthly-summary/calendar/"
RESOLVE = "/api/v1/attendance/monthly-summary/conflict-resolve/"
BULK = "/api/v1/attendance/monthly-summary/conflict-bulk-resolve/"
TEMPLATE = "/api/v1/attendance/monthly-summary/regularisation-template/"
IMPORT = "/api/v1/attendance/monthly-summary/regularisation-import/"
CONFIRM = "/api/v1/attendance/monthly-summary/regularisation-confirm/"


def sheet(rows, columns=("Badge ID", "Present", "Paid Leave", "Unpaid Leave", "Absent", "Reason")):
    buffer = BytesIO()
    pd.DataFrame(rows, columns=list(columns)).to_excel(buffer, index=False)
    buffer.seek(0)
    buffer.name = "summary.xlsx"
    return buffer


class RegularisationApiFixture(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.company = make_company("Reg API Co")
        self.user = make_user("reg_api_admin", password="secret123", is_superuser=True)
        make_employee(
            company=self.company,
            email="reg_api_admin@test.horilla",
            user=self.user,
        )
        self.employee = make_employee(
            company=self.company,
            email="reg_worker@test.horilla",
            first_name="Worker",
        )
        self.employee.badge_id = "REG-API-1"
        self.employee.save(update_fields=["badge_id"])
        self.client.force_authenticate(user=self.user)

    def summary_row(self):
        rows, _w, _t = build_monthly_summary(
            FROM_DATE, TO_DATE, Employee.objects.filter(pk=self.employee.pk)
        )
        return rows[0]

    def reconciling(self, present=0, paid_leave=0, unpaid_leave=0, **extra):
        counted = self.summary_row()
        working = (
            counted["present"]
            + counted["paid_leave"]
            + counted["unpaid_leave"]
            + counted["absent"]
        )
        row = {
            "Badge ID": self.employee.badge_id,
            "Present": present,
            "Paid Leave": paid_leave,
            "Unpaid Leave": unpaid_leave,
            "Absent": working - present - paid_leave - unpaid_leave,
        }
        row.update(extra)
        return sheet([row])

    def give_conflict(self, day=None):
        day = day or datetime.date(2026, 4, 15)
        leave_type = LeaveType.objects.create(name="Annual", payment="paid")
        LeaveRequest.objects.create(
            employee_id=self.employee,
            leave_type_id=leave_type,
            start_date=day,
            end_date=day,
            status="approved",
        )
        Attendance.objects.create(
            employee_id=self.employee,
            attendance_date=day,
            attendance_clock_in_date=day,
            attendance_clock_in=datetime.time(9, 0),
            attendance_validated=True,
        )
        return day


class CalendarApiTests(RegularisationApiFixture):
    def test_calendar_returns_months_cells_and_summary(self):
        response = self.client.get(
            CALENDAR,
            {
                "employee_id": self.employee.pk,
                "from_date": FROM_DATE.isoformat(),
                "to_date": TO_DATE.isoformat(),
            },
        )
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["employee"]["id"], self.employee.pk)
        self.assertEqual(response.data["from_date"], FROM_DATE.isoformat())
        self.assertTrue(response.data["months"])
        self.assertIn("cal_summary", response.data)
        self.assertIn("present", response.data["cal_summary"])
        first_month = response.data["months"][0]
        self.assertTrue(first_month["weeks"])
        cell = next(
            c
            for week in first_month["weeks"]
            for c in week
            if c and c["date"] == FROM_DATE.isoformat()
        )
        self.assertIn("status", cell)
        self.assertIn("is_conflict", cell)
        self.assertIn("halves", cell)

    def test_calendar_requires_employee_scope(self):
        outsider = make_user("reg_api_out", password="secret123")
        make_employee(
            company=self.company,
            email="reg_api_out@test.horilla",
            user=outsider,
        )
        self.client.force_authenticate(user=outsider)
        response = self.client.get(
            CALENDAR,
            {
                "employee_id": self.employee.pk,
                "from_date": FROM_DATE.isoformat(),
                "to_date": TO_DATE.isoformat(),
            },
        )
        self.assertEqual(response.status_code, 403)


class ConflictResolveApiTests(RegularisationApiFixture):
    def test_resolve_settles_conflict_and_returns_calendar(self):
        day = self.give_conflict()
        response = self.client.post(
            RESOLVE,
            {
                "employee_id": self.employee.pk,
                "date": day.isoformat(),
                "from_date": FROM_DATE.isoformat(),
                "to_date": TO_DATE.isoformat(),
                "resolution": "full_present",
                "conflict_type": "paid_leave",
            },
            format="json",
        )
        self.assertEqual(response.status_code, 200, response.data)
        saved = AttendanceConflictResolution.objects.get(
            employee_id=self.employee, date=day
        )
        self.assertEqual(saved.resolution, "full_present")
        cell = next(
            c
            for month in response.data["months"]
            for week in month["weeks"]
            for c in week
            if c and c["date"] == day.isoformat()
        )
        self.assertEqual(cell["status"], "present")
        self.assertFalse(cell["is_conflict"])

    def test_bulk_resolve_applies_to_each_date(self):
        days = [datetime.date(2026, 4, 10), datetime.date(2026, 4, 11)]
        response = self.client.post(
            BULK,
            {
                "employee_id": self.employee.pk,
                "dates": [d.isoformat() for d in days],
                "from_date": FROM_DATE.isoformat(),
                "to_date": TO_DATE.isoformat(),
                "resolution": "absent",
            },
            format="json",
        )
        self.assertEqual(response.status_code, 200, response.data)
        for day in days:
            self.assertEqual(
                AttendanceConflictResolution.objects.get(
                    employee_id=self.employee, date=day
                ).resolution,
                "absent",
            )

    def test_resolve_rejects_unknown_resolution(self):
        response = self.client.post(
            RESOLVE,
            {
                "employee_id": self.employee.pk,
                "date": "2026-04-10",
                "from_date": FROM_DATE.isoformat(),
                "to_date": TO_DATE.isoformat(),
                "resolution": "not_a_thing",
            },
            format="json",
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("resolution", response.data)


class TemplateImportConfirmApiTests(RegularisationApiFixture):
    def test_template_columns_match_classic(self):
        response = self.client.get(
            TEMPLATE,
            {
                "from_date": FROM_DATE.isoformat(),
                "to_date": TO_DATE.isoformat(),
                "employee_ids": self.employee.pk,
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn("spreadsheetml", response["Content-Type"])
        frame = pd.read_excel(BytesIO(response.content), sheet_name="Summary")
        for column in ("Present", "Paid Leave", "Unpaid Leave", "Absent", "Week Off", "Holiday"):
            self.assertIn(column, frame.columns)
        notes = pd.read_excel(
            BytesIO(response.content), sheet_name="How to fill this in"
        )
        editable = dict(zip(notes["Column"], notes["Editable"]))
        self.assertEqual(editable["Present"], "yes")
        self.assertEqual(editable["Week Off"], "no")
        self.assertEqual(editable["Holiday"], "no")

    def test_import_applies_when_no_conflicts(self):
        response = self.client.post(
            IMPORT,
            {
                "file": self.reconciling(present=19),
                "from_date": FROM_DATE.isoformat(),
                "to_date": TO_DATE.isoformat(),
            },
            format="multipart",
        )
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["applied_count"], 1)
        override = AttendanceSummaryOverride.objects.get(employee_id=self.employee)
        self.assertEqual(override.present, 19)

    def test_import_then_confirm_when_conflicts(self):
        self.give_conflict()
        held = self.client.post(
            IMPORT,
            {
                "file": self.reconciling(present=19),
                "from_date": FROM_DATE.isoformat(),
                "to_date": TO_DATE.isoformat(),
            },
            format="multipart",
        )
        self.assertEqual(held.status_code, 200, held.data)
        self.assertTrue(held.data["needs_confirm"])
        self.assertTrue(held.data["pending"])
        self.assertIsNone(
            AttendanceSummaryOverride.objects.filter(employee_id=self.employee).first()
        )

        confirmed = self.client.post(
            CONFIRM,
            {"confirm": True},
            format="json",
        )
        self.assertEqual(confirmed.status_code, 200, confirmed.data)
        self.assertEqual(confirmed.data["applied_count"], 1)
        self.assertIsNotNone(
            AttendanceSummaryOverride.objects.filter(employee_id=self.employee).first()
        )
        row = self.summary_row()
        self.assertEqual(row["unresolved_conflicts"], 0)

    def test_confirm_accepts_explicit_pending(self):
        day = self.give_conflict()
        held = self.client.post(
            IMPORT,
            {
                "file": self.reconciling(present=19),
                "from_date": FROM_DATE.isoformat(),
                "to_date": TO_DATE.isoformat(),
            },
            format="multipart",
        )
        self.assertTrue(held.data["needs_confirm"])
        # Clear session so confirm must use the explicit body.
        session = self.client.session
        session.pop("attendance_summary_pending", None)
        session.save()

        confirmed = self.client.post(
            CONFIRM,
            {
                "confirm": True,
                "from_date": FROM_DATE.isoformat(),
                "to_date": TO_DATE.isoformat(),
                "pending": held.data["pending"],
            },
            format="json",
        )
        self.assertEqual(confirmed.status_code, 200, confirmed.data)
        self.assertEqual(confirmed.data["applied_count"], 1)
        self.assertGreaterEqual(confirmed.data.get("settled_conflicts", 0), 1)
        self.assertEqual(
            AttendanceSummaryOverride.objects.get(employee_id=self.employee).present, 19
        )
        # Day still carried attendance+leave; override settles it for payroll summary.
        self.assertEqual(self.summary_row()["unresolved_conflicts"], 0)
        self.assertNotIn(day, self.summary_row()["unresolved_conflict_dates"])

    def test_import_reports_row_errors(self):
        response = self.client.post(
            IMPORT,
            {
                "file": sheet(
                    [{"Badge ID": "NOPE999", "Present": 19}],
                    columns=("Badge ID", "Present"),
                ),
                "from_date": FROM_DATE.isoformat(),
                "to_date": TO_DATE.isoformat(),
            },
            format="multipart",
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data["failed_count"], 1)
        self.assertIn("problem", response.data["errors"][0])

    def test_change_permission_required_for_template(self):
        outsider = make_user("reg_api_noperm", password="secret123")
        make_employee(
            company=self.company,
            email="reg_api_noperm@test.horilla",
            user=outsider,
        )
        self.client.force_authenticate(user=outsider)
        response = self.client.get(
            TEMPLATE,
            {"from_date": FROM_DATE.isoformat(), "to_date": TO_DATE.isoformat()},
        )
        self.assertEqual(response.status_code, 403)

    def test_view_permission_allows_calendar_for_scoped_employee(self):
        viewer = make_user("reg_api_viewer", password="secret123")
        make_employee(
            company=self.company,
            email="reg_api_viewer@test.horilla",
            user=viewer,
        )
        ct = ContentType.objects.get_for_model(Attendance)
        viewer.user_permissions.add(
            Permission.objects.get(content_type=ct, codename="view_attendance")
        )
        self.client.force_authenticate(user=viewer)
        response = self.client.get(
            CALENDAR,
            {
                "employee_id": self.employee.pk,
                "from_date": FROM_DATE.isoformat(),
                "to_date": TO_DATE.isoformat(),
            },
        )
        self.assertEqual(response.status_code, 200, response.data)
