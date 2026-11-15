"""Payroll JSON API: a run, the inputs it needs, and the configuration around it."""

from datetime import date

from django.contrib.auth.models import Permission
from django.test import TestCase
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from horilla.horilla_middlewares import set_selected_company
from horilla.testkit import make_company, make_employee, make_user
from payroll.methods.tax_calc import compute_yearly_tax
from payroll.models.models import (
    Contract,
    FilingStatus,
    PayrollBatch,
    Payslip,
    SalaryStructure,
)
from payroll.models.tax_models import TaxBracket
from payroll.system_components import policy, seed


class PayrollApiTests(TestCase):
    def setUp(self):
        set_selected_company(None)
        self.client = APIClient()
        self.company = make_company("Payroll Co")
        self.other = make_company("Other Co", hq=False)
        self.user = make_user("payroll_api", password="secret123", is_superuser=True)
        self.employee = make_employee(
            company=self.company,
            email="payroll_api@test.horilla",
            first_name="Ada",
            user=self.user,
        )
        self.employee.badge_id = "PAY-1"
        self.employee.save(update_fields=["badge_id"])
        self.client.force_authenticate(user=self.user)
        seed()

    def tearDown(self):
        set_selected_company(None)

    def _contract(self, wage=20000, employee=None):
        # Saving work info already creates one active contract. A second active
        # contract is refused, so the run tests reuse that row.
        employee = employee or self.employee
        contract = (
            Contract.objects.filter(employee_id=employee, contract_status="active")
            .order_by("-id")
            .first()
        )
        if contract is None:
            contract = Contract(
                contract_name="Main",
                employee_id=employee,
                contract_status="active",
            )
        contract.contract_start_date = date(2026, 1, 1)
        contract.wage = wage
        contract.hourly_wage = 0
        contract.wage_type = "monthly"
        contract.pay_frequency = "monthly"
        contract.save()
        return contract

    def test_missing_permission_is_forbidden(self):
        outsider = make_user("payroll_outsider", password="secret123")
        make_employee(
            company=self.company,
            email="outsider@test.horilla",
            user=outsider,
        )
        self.client.force_authenticate(user=outsider)
        response = self.client.get("/api/v1/payroll/batches/")
        self.assertEqual(response.status_code, 403)

    def test_review_blocks_a_contract_with_no_wage(self):
        self._contract(wage=0)
        response = self.client.post(
            "/api/v1/payroll/batches/review/",
            {
                "period_start": "2026-01-01",
                "period_end": "2026-01-31",
                "employee_ids": [self.employee.pk],
            },
            format="json",
        )
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["blocked_count"], 1)
        self.assertTrue(response.data["rows"][0]["blocked"])
        self.assertEqual(response.data["rows"][0]["problems"][0]["severity"], "blocking")

    def test_batch_refuses_approval_until_generation_finishes(self):
        self._contract()
        created = self.client.post(
            "/api/v1/payroll/batches/",
            {
                "batch_name": "January",
                "period_start": "2026-01-01",
                "period_end": "2026-01-31",
                "employee_ids": [self.employee.pk],
            },
            format="json",
        )
        self.assertEqual(created.status_code, 201, created.data)
        batch_id = created.data["id"]
        refused = self.client.post(
            f"/api/v1/payroll/batches/{batch_id}/status/",
            {"status": "approved"},
            format="json",
        )
        self.assertEqual(refused.status_code, 400, refused.data)

        batch = PayrollBatch.objects.get(pk=batch_id)
        batch.progress_state = PayrollBatch.DONE
        batch.save(update_fields=["progress_state"])
        approved = self.client.post(
            f"/api/v1/payroll/batches/{batch_id}/status/",
            {"status": "approved"},
            format="json",
        )
        self.assertEqual(approved.status_code, 200, approved.data)
        self.assertEqual(approved.data["status"], "approved")
        paid = self.client.post(
            f"/api/v1/payroll/batches/{batch_id}/status/",
            {"status": "paid"},
            format="json",
        )
        self.assertEqual(paid.status_code, 200, paid.data)
        backward = self.client.post(
            f"/api/v1/payroll/batches/{batch_id}/status/",
            {"status": "draft"},
            format="json",
        )
        self.assertEqual(backward.status_code, 400, backward.data)

    def test_generate_records_a_failed_line_and_finishes(self):
        self._contract()
        created = self.client.post(
            "/api/v1/payroll/batches/",
            {
                "batch_name": "January fail",
                "period_start": "2026-01-01",
                "period_end": "2026-01-31",
                "employee_ids": [self.employee.pk],
            },
            format="json",
        )
        self.assertEqual(created.status_code, 201, created.data)
        Contract.objects.filter(employee_id=self.employee).update(wage=0)
        response = self.client.post(
            f"/api/v1/payroll/batches/{created.data['id']}/generate/",
            {},
            format="json",
        )
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["progress_state"], "done")
        self.assertEqual(len(response.data["failed_lines"]), 1)
        self.assertEqual(response.data["failed_lines"][0]["status"], "failed")

    def test_payslip_status_is_locked_inside_a_paid_batch(self):
        batch = PayrollBatch.objects.create(
            batch_name="Paid",
            period_start=date(2026, 1, 1),
            period_end=date(2026, 1, 31),
            status=PayrollBatch.PAID,
            progress_state=PayrollBatch.DONE,
            company_id=self.company,
        )
        payslip = Payslip.objects.create(
            employee_id=self.employee,
            start_date=date(2026, 1, 1),
            end_date=date(2026, 1, 31),
            pay_head_data={"federal_tax": 0, "allowances": []},
            status="paid",
            payroll_batch=batch,
            basic_pay=1000,
            gross_pay=1000,
            deduction=0,
            net_pay=1000,
        )
        response = self.client.put(
            f"/api/v1/payroll/payslip/{payslip.pk}",
            {"status": "draft"},
            format="json",
        )
        self.assertEqual(response.status_code, 400, response.data)
        bulk = self.client.post(
            "/api/v1/payroll/payslip/bulk-status/",
            {"ids": [payslip.pk], "status": "draft"},
            format="json",
        )
        self.assertEqual(bulk.status_code, 200, bulk.data)
        self.assertEqual(bulk.data["updated"], 0)
        self.assertEqual(bulk.data["skipped"], 1)
        payslip.refresh_from_db()
        self.assertEqual(payslip.status, "paid")

    def test_structures_are_company_scoped(self):
        clerk = make_user("payroll_clerk", password="secret123")
        make_employee(
            company=self.company, email="clerk@test.horilla", user=clerk
        )
        clerk.user_permissions.add(
            Permission.objects.get(
                codename="view_salarystructure", content_type__app_label="payroll"
            )
        )
        own = SalaryStructure.objects.create(title="Own", company_id=self.company)
        other = SalaryStructure.objects.create(title="Other", company_id=self.other)
        token = str(RefreshToken.for_user(clerk).access_token)
        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")
        response = client.get("/api/v1/payroll/salary-structure/")
        self.assertEqual(response.status_code, 200, response.data)
        ids = [row["id"] for row in response.data["results"]]
        self.assertIn(own.pk, ids)
        self.assertNotIn(other.pk, ids)

    def test_system_component_rejects_fields_it_does_not_expose(self):
        row = policy("loan_repayment")
        self.assertIsNotNone(row)
        refused = self.client.put(
            "/api/v1/payroll/system-component/loan_repayment/",
            {"amount": 50},
            format="json",
        )
        self.assertEqual(refused.status_code, 400, refused.data)
        updated = self.client.put(
            "/api/v1/payroll/system-component/loan_repayment/",
            {"is_pretax": False},
            format="json",
        )
        self.assertEqual(updated.status_code, 200, updated.data)
        self.assertIs(updated.data["is_pretax"], False)

    def test_filing_status_preview_matches_the_payslip_tax(self):
        filing = FilingStatus.objects.create(
            filing_status="Preview",
            based_on="taxable_gross_pay",
            standard_deduction=0,
            company_id=self.company,
        )
        TaxBracket.objects.create(
            filing_status_id=filing, min_income=0, max_income=None, tax_rate=10
        )
        response = self.client.post(
            f"/api/v1/payroll/filing-status/{filing.pk}/preview/",
            {"yearly_income": 100000},
            format="json",
        )
        self.assertEqual(response.status_code, 200, response.data)
        _tax, breakdown = compute_yearly_tax(filing, 100000)
        self.assertEqual(response.data["tax"], breakdown["tax"])

    def test_pay_adjustment_confirm_creates_a_draft_then_a_line(self):
        created = self.client.post(
            "/api/v1/payroll/pay-adjustment/",
            {
                "employee_id": self.employee.pk,
                "kind": "arrears",
                "title": "Back pay",
                "amount": 500,
                "pay_date": "2026-02-15",
                "tax_treatment": False,
            },
            format="json",
        )
        self.assertEqual(created.status_code, 201, created.data)
        self.assertEqual(created.data["status"], "draft")
        confirmed = self.client.post(
            f"/api/v1/payroll/pay-adjustment/{created.data['id']}/status/",
            {"status": "approved"},
            format="json",
        )
        self.assertEqual(confirmed.status_code, 200, confirmed.data)
        self.assertEqual(confirmed.data["status"], "approved")

    def test_currency_round_trip(self):
        saved = self.client.put(
            "/api/v1/payroll/currency/",
            {"currency_symbol": "KSh", "position": "prefix"},
            format="json",
        )
        self.assertEqual(saved.status_code, 200, saved.data)
        self.assertEqual(saved.data["currency_symbol"], "KSh")
        read = self.client.get("/api/v1/payroll/currency/")
        self.assertEqual(read.data["position"], "prefix")
