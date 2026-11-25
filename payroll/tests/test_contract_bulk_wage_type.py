"""Changing the wage type on several contracts at once."""

from datetime import date

from django.test import TestCase
from rest_framework.test import APIClient

from horilla.horilla_middlewares import set_selected_company
from horilla.testkit import make_company, make_employee, make_user
from horilla.testkit.factories import make_contract
from payroll.models.models import Contract, SalaryStructure

URL = "/api/v1/payroll/contract/bulk-wage-type/"
START = date(2026, 1, 1)


class BulkWageTypeTests(TestCase):
    def setUp(self):
        set_selected_company(None)
        self.company = make_company("Wage Co")
        self.client = APIClient()
        self.client.force_authenticate(user=make_user("wage_admin", is_superuser=True))

    def contract(self, email, status="active", wage=300000, wage_type="monthly"):
        employee = make_employee(company=self.company, email=email)
        contract = make_contract(
            employee=employee, start_date=START, wage=wage, status=status
        )
        Contract.objects.filter(pk=contract.pk).update(wage_type=wage_type)
        return Contract.objects.get(pk=contract.pk)

    def post(self, contracts, wage_type):
        return self.client.post(
            URL, {"ids": [c.pk for c in contracts], "wage_type": wage_type}, format="json"
        )

    def test_draft_and_active_contracts_change(self):
        draft = self.contract("draft@test.horilla", status="draft")
        active = self.contract("active@test.horilla")
        response = self.post([draft, active], "daily")
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(sorted(response.json()["updated"]), sorted([draft.pk, active.pk]))
        for contract in (draft, active):
            contract.refresh_from_db()
            self.assertEqual(contract.wage_type, "daily")

    def test_an_ended_contract_keeps_its_wage_type(self):
        ended = self.contract("ended@test.horilla", status="terminated")
        response = self.post([ended], "daily")
        data = response.json()
        self.assertEqual(data["updated"], [])
        self.assertEqual([row["id"] for row in data["skipped"]], [ended.pk])
        ended.refresh_from_db()
        self.assertEqual(ended.wage_type, "monthly")

    def test_per_task_clears_the_pay_figures(self):
        active = self.contract("task@test.horilla")
        self.post([active], "task")
        active.refresh_from_db()
        self.assertEqual((active.wage_type, active.wage), ("task", 0))
        self.assertFalse(active.deduct_leave_from_basic_pay)

    def test_contracts_to_check_are_named(self):
        moved = self.contract("moved@test.horilla")
        unpaid = self.contract("unpaid@test.horilla", wage=0, wage_type="task")
        data = self.post([moved, unpaid], "daily").json()
        reasons = {row["id"]: row["reason"] for row in data["check"]}
        self.assertIn("per day", reasons[moved.pk])
        self.assertIn("no wage", reasons[unpaid.pk])

    def test_a_change_a_structure_refuses_is_skipped_with_the_reason(self):
        structure = SalaryStructure.objects.create(
            title="Packaged", company_id=self.company, structure_mode="ctc_down"
        )
        bound = self.contract("ctc@test.horilla", wage_type="task", wage=0)
        Contract.objects.filter(pk=bound.pk).update(salary_structure_id=structure)
        data = self.post([bound], "monthly").json()
        self.assertEqual(data["updated"], [])
        self.assertIn("Monthly CTC", data["skipped"][0]["reason"])
        bound.refresh_from_db()
        self.assertEqual(bound.wage_type, "task")

    def test_the_same_wage_type_is_left_alone(self):
        active = self.contract("same@test.horilla")
        data = self.post([active], "monthly").json()
        self.assertEqual((data["updated"], data["unchanged"]), ([], [active.pk]))

    def test_an_unknown_wage_type_is_refused(self):
        active = self.contract("odd@test.horilla")
        self.assertEqual(self.post([active], "weekly").status_code, 400)

    def test_needs_change_contract(self):
        active = self.contract("perm@test.horilla")
        clerk = APIClient()
        clerk.force_authenticate(user=make_user("wage_clerk"))
        response = clerk.post(URL, {"ids": [active.pk], "wage_type": "daily"}, format="json")
        self.assertEqual(response.status_code, 403)
