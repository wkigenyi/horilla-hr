"""Pay periods are opened and closed by hand, one at a time, and a closed one is locked."""

from datetime import date

from django.core.exceptions import ValidationError
from django.db import transaction
from django.test import TestCase
from rest_framework.test import APIClient

from horilla.horilla_middlewares import set_selected_company
from horilla.testkit import make_company, make_employee, make_user
from horilla.testkit.factories import (
    make_attendance,
    make_leave_request,
    make_leave_type,
    make_payslip,
)
from payroll.methods.period_lock import PeriodClosed, suspended
from payroll.models.models import PayAdjustment, PayPeriodSettings, PayrollBatch
from payroll.models.pay_period import PayPeriod
from project.models import Project, Task, TaskPayAllocation

OCT_21 = date(2026, 10, 21)
NOV_20 = date(2026, 11, 20)
NOV_21 = date(2026, 11, 21)
DEC_20 = date(2026, 12, 20)


class PayPeriodCase(TestCase):
    def setUp(self):
        set_selected_company(None)
        self.company = make_company("Period Co")
        self.sister = make_company("Period Sister")
        PayPeriodSettings.objects.create(company_id=self.company, cycle_start_day=21)
        user = make_user("period_admin", password="secret123", is_superuser=True)
        self.admin = make_employee(
            company=self.company,
            email="period-admin@test.horilla",
            first_name="Ada",
            user=user,
        )
        # Reloaded so the user's cached employee carries its work company.
        self.user = type(user).objects.get(pk=user.pk)
        self.worker = make_employee(
            company=self.company, email="period-worker@test.horilla", first_name="Wes"
        )

    def tearDown(self):
        set_selected_company(None)

    def assertLocked(self, change):
        # A refused delete leaves Django's own atomic block broken; the
        # savepoint keeps the rest of the test usable.
        with self.assertRaises(PeriodClosed), transaction.atomic():
            change()

    def _open(self, start=OCT_21, end=NOV_20):
        return PayPeriod.open_next(self.company, start, end, user=self.user)

    def _adjustment(self, pay_date, status="draft"):
        entry = PayAdjustment(
            employee_id=self.worker,
            kind="arrears",
            title="Late pay",
            amount=100,
            pay_date=pay_date,
            status=status,
        )
        entry.save()
        return entry


class OpeningTests(PayPeriodCase):
    def test_only_one_period_is_open_at_a_time(self):
        self._open()
        with self.assertRaises(ValidationError) as caught:
            PayPeriod.open_next(self.company, NOV_21, DEC_20)
        self.assertIn("still open", str(caught.exception))

    def test_the_next_period_starts_the_day_after_the_last(self):
        self._open().close(user=self.user)
        with self.assertRaises(ValidationError) as caught:
            PayPeriod.open_next(self.company, date(2026, 11, 25), DEC_20)
        self.assertIn("start_date", caught.exception.message_dict)
        opened = PayPeriod.open_next(self.company, NOV_21, DEC_20)
        self.assertEqual(opened.status, PayPeriod.OPEN)

    def test_suggestion_follows_on_and_ends_on_the_cycle(self):
        self._open().close(user=self.user)
        start, end, fixed = PayPeriod.suggest_next(self.company, date(2026, 11, 24))
        self.assertEqual((start, end, fixed), (NOV_21, DEC_20, True))

    def test_a_first_period_starts_where_unposted_work_is(self):
        project = Project.objects.create(
            title="Old work",
            status="new",
            start_date=OCT_21,
            description="Work",
            company_id=self.company,
        )
        Task(
            title="Slashing",
            project=project,
            description="Slashing",
            status="completed",
            is_payable=True,
            completed_at=date(2026, 10, 24),
        ).save()
        start, end, fixed = PayPeriod.suggest_next(self.company, date(2026, 11, 24))
        self.assertEqual((start, end, fixed), (OCT_21, NOV_20, False))

    def test_each_company_has_its_own_period(self):
        self._open()
        other = PayPeriod.open_next(self.sister, date(2026, 11, 1), date(2026, 11, 30))
        self.assertEqual(PayPeriod.current(self.sister), other)
        self.assertEqual(PayPeriod.current(self.company).start_date, OCT_21)

    def test_screens_default_to_the_open_period_not_todays_date(self):
        self._open()
        self.assertEqual(
            PayPeriod.dates_for(self.company, date(2026, 11, 24)), (OCT_21, NOV_20)
        )
        self.assertEqual(
            PayPeriod.dates_for(self.sister, date(2026, 11, 24)),
            (date(2026, 11, 1), date(2026, 11, 30)),
        )


class ClosingTests(PayPeriodCase):
    def test_a_draft_entry_blocks_closing(self):
        period = self._open()
        self._adjustment(date(2026, 11, 10))
        codes = [blocker["code"] for blocker in period.close_blockers()]
        self.assertEqual(codes, ["draft_adjustments"])
        with self.assertRaises(ValidationError):
            period.close(user=self.user)

    def test_an_unpaid_run_blocks_closing_and_a_paid_one_does_not(self):
        period = self._open()
        batch = PayrollBatch.objects.create(
            batch_name="Nov",
            period_start=OCT_21,
            period_end=NOV_20,
            company_id=self.company,
        )
        self.assertEqual(
            [blocker["code"] for blocker in period.close_blockers()], ["unpaid_runs"]
        )
        PayrollBatch.objects.filter(pk=batch.pk).update(status=PayrollBatch.PAID)
        self.assertEqual(period.close_blockers(), [])
        period.close(user=self.user)
        period.refresh_from_db()
        self.assertEqual(period.status, PayPeriod.CLOSED)
        self.assertEqual(period.closed_by, self.user)

    def test_a_period_with_no_payroll_can_be_closed_with_a_warning(self):
        period = self._open()
        self.assertIn(
            "no_payroll", [warning["code"] for warning in period.close_warnings()]
        )
        period.close(user=self.user)
        self.assertEqual(period.status, PayPeriod.CLOSED)


class LockTests(PayPeriodCase):
    def setUp(self):
        super().setUp()
        self.inside = date(2026, 11, 10)
        self.after = date(2026, 11, 24)
        self.entry = self._adjustment(self.inside, status="approved")
        self.attendance = make_attendance(
            employee=self.worker, attendance_date=self.inside
        )
        self.leave_type = make_leave_type()
        self.project = Project.objects.create(
            title="Locked work",
            status="new",
            start_date=OCT_21,
            description="Work",
            company_id=self.company,
        )
        self.task = Task(
            title="Pitting",
            project=self.project,
            description="Pitting",
            status="completed",
            is_payable=True,
            completed_at=self.inside,
        )
        self.task.save()
        self.task.task_members.add(self.worker)
        self.pay = TaskPayAllocation.objects.create(
            task=self.task, employee=self.worker, amount=50
        )
        self.period = self._open()
        self.period.close(user=self.user)

    def test_arrears_in_a_closed_period_cannot_be_added_changed_or_deleted(self):
        self.assertLocked(lambda: self._adjustment(self.inside))
        self.entry.amount = 500
        self.assertLocked(self.entry.save)
        self.assertTrue(self._adjustment(self.after).pk)

    def test_an_entry_cannot_be_moved_into_a_closed_period(self):
        entry = self._adjustment(self.after)
        entry.pay_date = self.inside
        self.assertLocked(entry.save)

    def test_attendance_in_a_closed_period_is_locked(self):
        self.assertLocked(
            lambda: make_attendance(
                employee=self.worker, attendance_date=date(2026, 11, 11)
            )
        )
        self.assertLocked(self.attendance.delete)
        self.assertTrue(
            make_attendance(employee=self.worker, attendance_date=self.after).pk
        )

    def test_leave_touching_a_closed_period_is_locked(self):
        self.assertLocked(
            lambda: make_leave_request(
                employee=self.worker,
                leave_type=self.leave_type,
                start_date=date(2026, 11, 19),
                end_date=date(2026, 11, 23),
            )
        )
        self.assertTrue(
            make_leave_request(
                employee=self.worker,
                leave_type=self.leave_type,
                start_date=self.after,
                end_date=self.after,
            ).pk
        )

    def test_a_payable_tasks_completion_and_pay_are_locked(self):
        self.task.status = "in_progress"
        self.assertLocked(self.task.save)
        self.pay.amount = 75
        self.assertLocked(self.pay.save)
        self.assertLocked(self.pay.delete)
        # Other edits to the same task are not about pay.
        task = Task.objects.get(pk=self.task.pk)
        task.description = "Pitting, block E11"
        task.save()

    def test_a_task_cannot_be_completed_back_into_a_closed_period(self):
        late = Task(
            title="Found later",
            project=self.project,
            description="Found later",
            status="completed",
            is_payable=True,
            completed_at=self.inside,
        )
        self.assertLocked(late.save)

    def test_payslips_and_runs_for_a_closed_period_are_refused(self):
        self.assertLocked(
            lambda: make_payslip(
                employee=self.worker, start_date=OCT_21, end_date=NOV_20
            )
        )
        self.assertLocked(
            lambda: PayrollBatch.objects.create(
                batch_name="Late run",
                period_start=OCT_21,
                period_end=NOV_20,
                company_id=self.company,
            )
        )

    def test_another_companys_records_are_not_locked(self):
        outsider = make_employee(
            company=self.sister, email="period-out@test.horilla", first_name="Olu"
        )
        self.assertTrue(make_attendance(employee=outsider, attendance_date=self.inside).pk)

    def test_reopening_unlocks_the_period(self):
        self.period.reopen(user=self.user)
        self.entry.amount = 500
        self.entry.save()
        self.assertEqual(PayPeriod.current(self.company), self.period)

    def test_reopening_is_refused_once_a_later_period_is_closed(self):
        PayPeriod.open_next(self.company, NOV_21, DEC_20).close(user=self.user)
        self.period.refresh_from_db()
        self.assertIsNotNone(self.period.reopen_refusal())
        with self.assertRaises(ValidationError):
            self.period.reopen(user=self.user)

    def test_repair_work_can_suspend_the_lock(self):
        with suspended():
            self.entry.amount = 1
            self.entry.save()


class PayPeriodApiTests(PayPeriodCase):
    def setUp(self):
        super().setUp()
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)

    def test_open_close_reopen_round_trip(self):
        listed = self.client.get("/api/v1/payroll/pay-periods/")
        self.assertEqual(listed.status_code, 200, listed.data)
        self.assertIsNone(listed.data["current"])
        self.assertTrue(listed.data["can_open"])

        opened = self.client.post(
            "/api/v1/payroll/pay-periods/",
            {"start_date": "2026-10-21", "end_date": "2026-11-20"},
            format="json",
        )
        self.assertEqual(opened.status_code, 201, opened.data)
        period_id = opened.data["current"]["id"]
        self.assertFalse(opened.data["can_open"])
        self.assertEqual(opened.data["suggested"]["start_date"], NOV_21)

        again = self.client.post("/api/v1/payroll/pay-periods/", {}, format="json")
        self.assertEqual(again.status_code, 400, again.data)

        self._adjustment(date(2026, 11, 10))
        refused = self.client.post(f"/api/v1/payroll/pay-periods/{period_id}/close/")
        self.assertEqual(refused.status_code, 400, refused.data)
        PayAdjustment.objects.all().delete()

        closed = self.client.post(f"/api/v1/payroll/pay-periods/{period_id}/close/")
        self.assertEqual(closed.status_code, 200, closed.data)
        self.assertIsNone(closed.data["current"])
        self.assertTrue(closed.data["periods"][0]["can_reopen"])

        reopened = self.client.post(f"/api/v1/payroll/pay-periods/{period_id}/reopen/")
        self.assertEqual(reopened.status_code, 200, reopened.data)
        self.assertEqual(reopened.data["current"]["id"], period_id)

    def test_a_locked_change_through_the_api_is_a_400_not_a_500(self):
        self._open().close(user=self.user)
        response = self.client.post(
            "/api/v1/payroll/pay-adjustment/",
            {
                "employee_id": self.worker.pk,
                "kind": "arrears",
                "title": "Too late",
                "amount": 10,
                "pay_date": "2026-11-10",
            },
            format="json",
        )
        self.assertEqual(response.status_code, 400, response.content)
        self.assertIn("closed", str(response.data))

    def test_the_pay_period_setting_reports_the_open_period(self):
        self._open()
        response = self.client.get("/api/v1/payroll/pay-period/")
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data[0]["current_period"]["start"], OCT_21)
        self.assertEqual(response.data[0]["current_period"]["end"], NOV_20)

    def test_permissions_are_required(self):
        plain = make_user("period_plain", password="secret123")
        make_employee(company=self.company, email="period-plain@test.horilla", user=plain)
        self.client.force_authenticate(user=plain)
        self.assertEqual(self.client.get("/api/v1/payroll/pay-periods/").status_code, 403)
        self.assertEqual(
            self.client.post("/api/v1/payroll/pay-periods/", {}, format="json").status_code,
            403,
        )
