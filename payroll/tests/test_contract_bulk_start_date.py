"""Moving the start date of several contracts at once."""

from datetime import date

from django.test import TestCase
from rest_framework.test import APIClient

from horilla.horilla_middlewares import set_selected_company
from horilla.testkit import make_company, make_employee, make_user
from horilla.testkit.factories import make_contract, make_payslip
from payroll.models.models import Contract

URL = "/api/v1/payroll/contract/bulk-start-date/"
JOINED = date(2026, 1, 5)


class BulkStartDateTests(TestCase):
    def setUp(self):
        set_selected_company(None)
        self.company = make_company("Start Co")
        self.client = APIClient()
        self.client.force_authenticate(user=make_user("start_admin", is_superuser=True))

    def contract(self, email, status="active", start=date(2026, 3, 1), end=None):
        employee = make_employee(
            company=self.company, email=email, date_joining=JOINED
        )
        Contract.objects.entire().filter(employee_id=employee).delete()
        return make_contract(
            employee=employee, start_date=start, end_date=end, status=status
        )

    def post(self, contracts, start):
        return self.client.post(
            URL, {"ids": [c.pk for c in contracts], "start_date": start}, format="json"
        )

    def test_draft_and_active_contracts_move(self):
        draft = self.contract("draft@test.horilla", status="draft")
        active = self.contract("active@test.horilla")
        data = self.post([draft, active], "2026-02-01").json()
        self.assertEqual(sorted(data["updated"]), sorted([draft.pk, active.pk]))
        for contract in (draft, active):
            contract.refresh_from_db()
            self.assertEqual(contract.contract_start_date, date(2026, 2, 1))

    def test_an_ended_contract_keeps_its_start(self):
        ended = self.contract("ended@test.horilla", status="terminated")
        data = self.post([ended], "2026-02-01").json()
        self.assertEqual(data["updated"], [])
        self.assertIn("ended", data["skipped"][0]["reason"])

    def test_not_before_the_joining_date(self):
        active = self.contract("early@test.horilla")
        data = self.post([active], "2026-01-04").json()
        self.assertEqual(data["updated"], [])
        self.assertIn("5 Jan 2026", data["skipped"][0]["reason"])
        active.refresh_from_db()
        self.assertEqual(active.contract_start_date, date(2026, 3, 1))

    def test_not_after_its_own_end_date(self):
        active = self.contract("short@test.horilla", end=date(2026, 12, 31))
        data = self.post([active], "2027-01-15").json()
        self.assertEqual(data["updated"], [])
        self.assertTrue(data["skipped"])

    def test_a_payslip_on_the_days_that_move_keeps_the_start(self):
        active = self.contract("paid@test.horilla")
        make_payslip(
            employee=active.employee_id,
            start_date=date(2026, 2, 1),
            end_date=date(2026, 2, 28),
        )
        data = self.post([active], "2026-02-10").json()
        self.assertEqual(data["updated"], [])
        self.assertIn("payslip", data["skipped"][0]["reason"])

    def test_a_payslip_outside_the_days_that_move_does_not_block(self):
        active = self.contract("later@test.horilla")
        make_payslip(
            employee=active.employee_id,
            start_date=date(2026, 3, 1),
            end_date=date(2026, 3, 31),
        )
        data = self.post([active], "2026-02-10").json()
        self.assertEqual(data["updated"], [active.pk])

    def test_the_same_date_is_left_alone(self):
        active = self.contract("same@test.horilla")
        data = self.post([active], "2026-03-01").json()
        self.assertEqual((data["updated"], data["unchanged"]), ([], [active.pk]))

    def test_a_missing_date_is_refused(self):
        active = self.contract("none@test.horilla")
        self.assertEqual(self.post([active], "").status_code, 400)

    def test_needs_change_contract(self):
        active = self.contract("perm@test.horilla")
        clerk = APIClient()
        clerk.force_authenticate(user=make_user("start_clerk"))
        response = clerk.post(
            URL, {"ids": [active.pk], "start_date": "2026-02-01"}, format="json"
        )
        self.assertEqual(response.status_code, 403)
