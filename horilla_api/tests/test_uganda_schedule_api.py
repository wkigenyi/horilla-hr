"""Uganda statutory schedule through the JSON API, as Imara uses it."""

import csv
from datetime import date
from io import BytesIO, StringIO

from django.contrib.auth.models import Permission
from django.test import TestCase
from rest_framework.test import APIClient

from horilla.horilla_middlewares import set_selected_company
from horilla.testkit import make_company, make_employee, make_user
from payroll.models.models import Deduction, Payslip

URL = "/api/v1/payroll/statutory/uganda/"
EXPORT = "/api/v1/payroll/statutory/uganda/export/"


def pay_head(nssf_ee, nssf_er, lst, gross, taxable, paye, ee_id, er_id, lst_id):
    return {
        "gross_pay": gross,
        "taxable_gross_pay": taxable,
        "federal_tax": paye,
        "pretax_deductions": [
            {"deduction_id": lst_id, "title": "LST", "amount": lst, "is_pretax": True}
        ],
        "post_tax_deductions": [
            {"deduction_id": ee_id, "title": "Employee NSSF Contribution", "amount": nssf_ee},
            {
                "deduction_id": er_id,
                "title": "Employer NSSF Contribution",
                "amount": 0,
                "employer_contribution_amount": nssf_er,
            },
        ],
        # A tax-flagged deduction is not PAYE and must not be added to it.
        "tax_deductions": [{"deduction_id": None, "title": "Professional Tax", "amount": 999}],
    }


class UgandaScheduleApiTests(TestCase):
    def setUp(self):
        set_selected_company(None)
        self.company = make_company("Kampala Schedule Co")
        self.user = make_user("schedule_api", password="secret123", is_superuser=True)
        make_employee(company=self.company, email="schedule_api@test.horilla", user=self.user)
        self.user.refresh_from_db()
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)

        self.ee = Deduction.objects.create(
            title="Employee NSSF Contribution", is_fixed=False, based_on="gross_pay", rate=5
        )
        self.er = Deduction.objects.create(
            title="Employer NSSF Contribution",
            is_fixed=False,
            based_on="gross_pay",
            rate=0,
            employer_rate=10,
        )
        self.lst = Deduction.objects.create(
            title="LST", is_fixed=False, based_on="uganda_lst", is_pretax=True
        )

        self.grace = make_employee(
            company=self.company, email="grace@test.horilla", first_name="Grace", last_name="Nakato"
        )
        self.grace.tax_id = "1000123456"
        self.grace.nssf_id = "NS0001"
        self.grace.national_id = "CM900000"
        self.grace.save()
        self.john = make_employee(
            company=self.company, email="john@test.horilla", first_name="John", last_name="Okello"
        )

        # Grace: one monthly slip in July 2026 at 5,000,000.
        self.slip(self.grace, date(2026, 7, 1), date(2026, 7, 31), 5_000_000, 4_975_000, 1_394_500, 250_000, 500_000, 25_000)
        # John: paid twice in July (semi-monthly); one row, added together.
        self.slip(self.john, date(2026, 7, 1), date(2026, 7, 15), 200_000, 199_375, 0, 10_000, 20_000, 625)
        self.slip(self.john, date(2026, 7, 16), date(2026, 7, 31), 200_000, 199_375, 0, 10_000, 20_000, 625)
        # A draft is not issued, so it is left out by default.
        self.drafted = make_employee(
            company=self.company, email="drafted@test.horilla", first_name="Draft"
        )
        self.slip(self.drafted, date(2026, 7, 1), date(2026, 7, 31), 1, 1, 1, 1, 1, 1, status="draft")
        # Another month is not in July's schedule.
        self.slip(self.grace, date(2026, 8, 1), date(2026, 8, 31), 7, 7, 7, 7, 7, 7)

    def tearDown(self):
        set_selected_company(None)

    def slip(self, employee, start, end, gross, taxable, paye, ee, er, lst, status="confirmed"):
        return Payslip.objects.create(
            employee_id=employee,
            start_date=start,
            end_date=end,
            gross_pay=gross,
            status=status,
            pay_head_data=pay_head(
                ee, er, lst, gross, taxable, paye, self.ee.pk, self.er.pk, self.lst.pk
            ),
        )

    def schedule(self, **params):
        response = self.client.get(URL, {"month": "2026-07", **params})
        self.assertEqual(response.status_code, 200, response.data)
        return response.data

    def test_one_row_per_employee_with_the_statutory_figures(self):
        data = self.schedule()
        rows = {row["name"]: row for row in data["rows"]}
        self.assertEqual(set(rows), {"Grace Nakato", "John Okello"})
        grace = rows["Grace Nakato"]
        self.assertEqual(grace["tin"], "1000123456")
        self.assertEqual(grace["nssf_number"], "NS0001")
        self.assertEqual(grace["national_id"], "CM900000")
        self.assertEqual(grace["gross_pay"], 5_000_000)
        self.assertEqual(grace["chargeable_income"], 4_975_000)
        self.assertEqual(grace["paye"], 1_394_500)
        self.assertEqual(grace["nssf_employee"], 250_000)
        self.assertEqual(grace["nssf_employer"], 500_000)
        self.assertEqual(grace["nssf_total"], 750_000)
        self.assertEqual(grace["lst"], 25_000)
        self.assertEqual(grace["missing"], [])

    def test_two_payslips_in_the_month_are_added_together(self):
        john = next(row for row in self.schedule()["rows"] if row["name"] == "John Okello")
        self.assertEqual(john["payslips"], 2)
        self.assertEqual(john["gross_pay"], 400_000)
        self.assertEqual(john["lst"], 1_250)
        self.assertEqual(john["nssf_total"], 60_000)

    def test_totals_and_missing_numbers(self):
        data = self.schedule()
        self.assertEqual(data["totals"]["paye"], 1_394_500)
        self.assertEqual(data["totals"]["nssf_employee"], 270_000)
        self.assertEqual(data["totals"]["nssf_employer"], 540_000)
        self.assertEqual(data["totals"]["nssf_total"], 810_000)
        self.assertEqual(data["totals"]["lst"], 26_250)
        self.assertEqual(data["totals"]["employees"], 2)
        self.assertEqual(data["missing"]["tin"], [self.john.pk])
        self.assertEqual(data["missing"]["nssf_number"], [self.john.pk])
        john = next(row for row in data["rows"] if row["name"] == "John Okello")
        self.assertEqual(john["missing"], ["TIN", "NSSF number"])

    def test_drafts_only_when_asked_for(self):
        self.assertEqual(self.schedule()["totals"]["payslips"], 3)
        self.assertEqual(self.schedule(status="all")["totals"]["payslips"], 4)
        self.assertEqual(self.schedule(status="draft")["totals"]["payslips"], 1)

    def test_other_companies_are_left_out(self):
        other = make_company("Elsewhere Ltd")
        stranger = make_employee(company=other, email="stranger@test.horilla")
        self.slip(stranger, date(2026, 7, 1), date(2026, 7, 31), 9, 9, 9, 9, 9, 9)
        self.assertEqual(self.schedule()["totals"]["employees"], 2)

    def test_csv_download_has_a_header_rows_and_totals(self):
        response = self.client.get(EXPORT, {"month": "2026-07", "file_format": "csv"})
        self.assertEqual(response.status_code, 200)
        self.assertIn("uganda-statutory-2026-07-summary.csv", response["Content-Disposition"])
        lines = list(csv.reader(StringIO(response.content.decode())))
        self.assertEqual(lines[0][:4], ["Employee", "Employee number", "TIN", "NSSF number"])
        self.assertEqual(len(lines), 4)  # header, two people, totals
        self.assertEqual(lines[-1][0], "Total")
        self.assertIn("1394500.0", lines[-1])

    def test_xlsx_download_opens_as_a_spreadsheet(self):
        from openpyxl import load_workbook

        response = self.client.get(EXPORT, {"month": "2026-07", "file_format": "xlsx"})
        self.assertEqual(response.status_code, 200)
        sheet = load_workbook(BytesIO(response.content)).active
        self.assertEqual(sheet.title, "2026-07")
        self.assertEqual(sheet.cell(row=1, column=1).value, "Employee")
        self.assertEqual(sheet.cell(row=sheet.max_row, column=1).value, "Total")

    def test_bad_input_is_refused(self):
        self.assertEqual(self.client.get(URL, {"month": "July"}).status_code, 400)
        self.assertEqual(self.client.get(URL).status_code, 400)
        self.assertEqual(
            self.client.get(URL, {"month": "2026-07", "status": "nope"}).status_code, 400
        )
        self.assertEqual(
            self.client.get(EXPORT, {"month": "2026-07", "file_format": "pdf"}).status_code,
            400,
        )
        self.assertEqual(
            self.client.get(EXPORT, {"month": "2026-07", "layout": "ura"}).status_code,
            400,
        )

    def test_needs_permission_to_view_payslips(self):
        user = make_user("schedule_nobody", password="secret123")
        client = APIClient()
        client.force_authenticate(user=user)
        self.assertEqual(client.get(URL, {"month": "2026-07"}).status_code, 403)
        user.user_permissions.add(Permission.objects.get(codename="view_payslip"))
        user = type(user).objects.get(pk=user.pk)
        client.force_authenticate(user=user)
        self.assertEqual(client.get(URL, {"month": "2026-07"}).status_code, 200)
