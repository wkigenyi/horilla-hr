"""
A contract follows the employee's joining date.

A new employee's contract used to be made on the first save, before the joining
date or salary were filled in: active, dated the day they were added, at a wage
of 0. Now it waits for the joining date, starts on it, and is a draft. Adding an
employee needs a company and a joining date, and no contract may start before
the employee joined.
"""

from datetime import date

import pandas as pd
from django.core.exceptions import ValidationError
from django.test import TestCase
from rest_framework.test import APIClient

from employee.methods.methods import process_employee_records
from employee.models import Employee, EmployeeWorkInformation
from horilla.horilla_middlewares import set_selected_company
from horilla.testkit import make_company, make_employee, make_user
from payroll.models.models import Contract

EMPLOYEES = "/api/v1/employee/employees/"
CONTRACTS = "/api/v1/payroll/contract/"
JOINED = date(2026, 1, 5)


def contracts_of(employee):
    return list(Contract.objects.entire().filter(employee_id=employee).order_by("id"))


class DraftContractFollowsJoiningDateTests(TestCase):
    def setUp(self):
        set_selected_company(None)
        self.company = make_company("Joining Co")

    def test_no_contract_until_there_is_a_joining_date(self):
        employee = make_employee(company=self.company, email="nodate@test.horilla")
        self.assertEqual(contracts_of(employee), [])

    def test_joining_date_makes_a_draft_starting_on_it(self):
        employee = make_employee(company=self.company, email="joins@test.horilla")
        work = employee.employee_work_info
        work.date_joining = JOINED
        work.basic_salary = 450000
        work.save()

        [contract] = contracts_of(employee)
        self.assertEqual(contract.contract_status, "draft")
        self.assertEqual(contract.contract_start_date, JOINED)
        self.assertEqual(contract.wage, 450000)

    def test_a_draft_moves_with_the_joining_date(self):
        employee = make_employee(company=self.company, email="moves@test.horilla")
        work = employee.employee_work_info
        work.date_joining = JOINED
        work.save()
        work.date_joining = date(2026, 2, 2)
        work.save()

        [contract] = contracts_of(employee)
        self.assertEqual(contract.contract_start_date, date(2026, 2, 2))

    def test_an_active_contract_keeps_its_start(self):
        employee = make_employee(company=self.company, email="active@test.horilla")
        work = employee.employee_work_info
        work.date_joining = JOINED
        work.save()
        Contract.objects.entire().filter(employee_id=employee).update(
            contract_status="active"
        )
        work.date_joining = date(2026, 2, 2)
        work.save()

        [contract] = contracts_of(employee)
        self.assertEqual(contract.contract_start_date, JOINED)

    def test_choosing_no_contract_makes_none(self):
        employee = make_employee(company=self.company, email="skip@test.horilla")
        work = employee.employee_work_info
        work.date_joining = JOINED
        work.skip_draft_contract = True
        work.save()
        self.assertEqual(contracts_of(employee), [])

    def test_an_inactive_employee_gets_no_contract(self):
        employee = make_employee(company=self.company, email="gone@test.horilla")
        Employee.objects.filter(pk=employee.pk).update(is_active=False)
        work = EmployeeWorkInformation.objects.get(employee_id=employee)
        work.date_joining = JOINED
        work.save()
        self.assertEqual(contracts_of(employee), [])


class StartBeforeJoiningTests(TestCase):
    def setUp(self):
        set_selected_company(None)
        self.company = make_company("Start Co")
        self.employee = make_employee(
            company=self.company, email="starter@test.horilla", date_joining=JOINED
        )
        Contract.objects.entire().filter(employee_id=self.employee).delete()
        self.client = APIClient()
        self.client.force_authenticate(user=make_user("payroll_admin", is_superuser=True))

    def _post(self, start):
        return self.client.post(
            CONTRACTS,
            {
                "contract_name": "Main",
                "employee_id": self.employee.pk,
                "contract_start_date": start,
                "wage_type": "monthly",
                "wage": 300000,
                "pay_frequency": "monthly",
            },
            format="json",
        )

    def test_api_refuses_a_start_before_joining(self):
        response = self._post("2026-01-04")
        self.assertEqual(response.status_code, 400, response.content)
        self.assertIn("contract_start_date", response.json())
        self.assertIn("5 Jan 2026", str(response.json()["contract_start_date"]))

    def test_api_accepts_a_start_on_the_joining_date(self):
        response = self._post("2026-01-05")
        self.assertEqual(response.status_code, 200, response.content)

    def test_an_early_contract_can_still_be_edited_without_moving_its_start(self):
        early = Contract.objects.create(
            contract_name="Old",
            employee_id=self.employee,
            contract_start_date=date(2025, 6, 1),
            wage=100,
        )
        body = {
            "contract_name": "Old",
            "employee_id": self.employee.pk,
            "contract_start_date": "2025-06-01",
            "wage_type": "monthly",
            "wage": 200,
            "pay_frequency": "monthly",
        }
        response = self.client.put(f"{CONTRACTS}{early.pk}", body, format="json")
        self.assertEqual(response.status_code, 200, response.content)

        moved = self.client.put(
            f"{CONTRACTS}{early.pk}",
            {**body, "contract_start_date": "2025-07-01"},
            format="json",
        )
        self.assertEqual(moved.status_code, 400, moved.content)
        self.assertIn("contract_start_date", moved.json())

    def test_model_clean_refuses_a_start_before_joining(self):
        contract = Contract(
            contract_name="Classic",
            employee_id=self.employee,
            contract_start_date=date(2025, 12, 31),
            wage=100,
        )
        with self.assertRaises(ValidationError) as raised:
            contract.clean()
        self.assertIn("contract_start_date", raised.exception.message_dict)


class AddEmployeeTests(TestCase):
    def setUp(self):
        set_selected_company(None)
        self.company = make_company("Hire Co")
        self.client = APIClient()
        self.client.force_authenticate(user=make_user("hr_admin", is_superuser=True))

    def _create(self, tag="grace", **extra):
        body = {
            "employee_first_name": "Grace",
            "employee_last_name": "Akello",
            "email": f"{tag}@test.horilla",
            "company_id": self.company.pk,
            "date_joining": "2026-01-05",
            **extra,
        }
        return self.client.post(EMPLOYEES, body, format="json")

    def test_company_and_joining_date_are_required(self):
        response = self.client.post(
            EMPLOYEES, {"employee_first_name": "Nobody"}, format="json"
        )
        self.assertEqual(response.status_code, 400, response.content)
        self.assertIn("company_id", response.json())
        self.assertIn("date_joining", response.json())
        self.assertFalse(Employee.objects.filter(employee_first_name="Nobody").exists())

    def test_new_employee_gets_company_joining_date_and_a_draft(self):
        response = self._create()
        self.assertEqual(response.status_code, 201, response.content)
        employee = Employee.objects.get(pk=response.json()["id"])
        work = EmployeeWorkInformation.objects.get(employee_id=employee)
        self.assertEqual(work.company_id, self.company)
        self.assertEqual(work.date_joining, JOINED)
        [contract] = contracts_of(employee)
        self.assertEqual(
            (contract.contract_status, contract.contract_start_date), ("draft", JOINED)
        )

    def test_contract_is_optional(self):
        response = self._create(create_contract=False, tag="nocontract")
        self.assertEqual(response.status_code, 201, response.content)
        self.assertEqual(contracts_of(response.json()["id"]), [])


class ImportNeedsCompanyAndJoiningDateTests(TestCase):
    def setUp(self):
        set_selected_company(None)
        self.company = make_company("Import Co")

    def _rows(self, **cells):
        row = {
            "Badge ID": "IMP1",
            "First Name": "Okot",
            "Last Name": "Peter",
            "Email": "okot@test.horilla",
            "Phone": "0700000000",
            "Gender": "male",
            "Company": "Import Co",
            "Date Joining": "2026-01-05",
        }
        row.update(cells)
        return process_employee_records(pd.DataFrame([row]))

    def test_a_complete_row_is_accepted(self):
        success, errors, _count = self._rows()
        self.assertEqual((len(success), len(errors)), (1, 0), errors)

    def test_joining_date_is_required(self):
        success, errors, _count = self._rows(**{"Date Joining": None})
        self.assertEqual(len(success), 0)
        self.assertEqual(errors[0]["Joining Date Error"], "Joining date is required.")

    def test_company_is_required(self):
        success, errors, _count = self._rows(Company=None)
        self.assertEqual(len(success), 0)
        self.assertEqual(errors[0]["Company Error"], "Company is required.")
