"""
Contracts paid per task: casual workers with no basic pay.

A contract with no wage is refused by the payroll run, because nothing states
basic pay and a filing status based on basic pay would tax nothing. A casual
worker is the case where no basic pay is the truth rather than a mistake, so
the contract says so with the "Per task" wage type, and then:

  * the payslip is made with basic pay zero, not refused;
  * the pay is the task pay confirmed for the period (arrears entries);
  * an earning flagged as basic pay is not paid on top;
  * no loss of pay is taken, because no day was promised any pay;
  * the contract cannot be paired with what needs a basic pay to work.
"""

from django.core.exceptions import ValidationError
from django.test import TestCase

from horilla.testkit import make_company, make_employee
from payroll.methods.batch_run import (
    WARNING,
    create_batch,
    eligible_employees,
    generate_slice,
    task_pay_warnings,
)
from payroll.methods.payroll_run import payroll_calculation
from payroll.models.models import (
    Contract,
    PayAdjustment,
    PayrollBatchLine,
    Payslip,
    SalaryStructure,
)
from payroll.tests.factories_payroll import (
    PERIOD_END,
    PERIOD_START,
    make_active_contract,
    make_allowance,
    make_filing_status,
)


def _task_contract(employee, **overrides):
    defaults = dict(
        wage_type="task",
        wage=0,
        deduct_leave_from_basic_pay=False,
        calculate_daily_leave_amount=True,
    )
    defaults.update(overrides)
    return make_active_contract(employee, **defaults)


class PaidPerTaskPayslipTests(TestCase):
    def setUp(self):
        company = make_company("Casual Co")
        self.employee = make_employee(company=company, email="casual@test.horilla")
        Contract.objects.filter(employee_id=self.employee).delete()

    def _run(self):
        return payroll_calculation(self.employee, PERIOD_START, PERIOD_END)

    def test_a_contract_paid_per_task_is_not_refused(self):
        _task_contract(self.employee)
        data = self._run()
        self.assertEqual(data["basic_pay"], 0)
        self.assertEqual(data["gross_pay"], 0)

    def test_task_pay_is_the_pay(self):
        _task_contract(self.employee)
        make_allowance(
            self.employee,
            "Task earnings",
            amount=12000.0,
            one_time_date=PERIOD_END,
        )
        data = self._run()
        self.assertEqual(data["basic_pay"], 0)
        self.assertAlmostEqual(data["gross_pay"], 12000.0, places=2)

    def test_task_pay_is_taxed(self):
        """
        The reason a missing basic is refused elsewhere is that tax could come
        out at nothing. Here tax follows taxable gross, which is the task pay.
        """
        filing = make_filing_status(
            "Casual PAYE",
            brackets=[(0, None, 10)],
            based_on="taxable_gross_pay",
            tax_scale="period",
        )
        _task_contract(self.employee, filing_status=filing)
        make_allowance(self.employee, "Task earnings", amount=12000.0, one_time_date=PERIOD_END)
        data = self._run()
        self.assertGreater(data["federal_tax"], 0)
        self.assertLess(data["net_pay"], data["gross_pay"])

    def test_a_confirmed_task_pay_entry_reaches_the_payslip(self):
        _task_contract(self.employee)
        entry = PayAdjustment.objects.create(
            employee_id=self.employee,
            kind="arrears",
            title="Task earnings",
            amount=8500.0,
            pay_date=PERIOD_END,
            status="draft",
        )
        entry.approve()
        data = self._run()
        self.assertAlmostEqual(data["gross_pay"], 8500.0, places=2)

    def test_an_earning_flagged_as_basic_pay_is_not_paid(self):
        structure = SalaryStructure.objects.create(title="Casual", structure_mode="gross_up")
        basic = make_allowance(self.employee, "Basic Pay", amount=5000.0, is_basic_pay=True)
        structure.allowances.add(basic)
        _task_contract(self.employee, salary_structure_id=structure)
        data = self._run()
        self.assertNotIn("Basic Pay", [line["title"] for line in data["allowances"]])
        self.assertEqual(data["gross_pay"], 0)

    def test_no_loss_of_pay_is_taken(self):
        _task_contract(self.employee)
        data = payroll_calculation(
            self.employee,
            PERIOD_START,
            PERIOD_END,
            month_summary={"present": 5, "absent": 17, "week_off": 9, "total_working": 22},
        )
        self.assertEqual(data["loss_of_pay"], 0)
        self.assertEqual(data["basic_pay"], 0)


class PaidPerTaskContractTests(TestCase):
    def setUp(self):
        company = make_company("Casual Rules Co")
        self.employee = make_employee(company=company, email="rules@test.horilla")
        Contract.objects.filter(employee_id=self.employee).delete()

    def _contract(self, **overrides):
        values = dict(
            contract_name="Casual",
            employee_id=self.employee,
            contract_start_date=PERIOD_START,
            wage_type="task",
            contract_status="draft",
        )
        values.update(overrides)
        return Contract(**values)

    def test_stray_pay_figures_are_cleared(self):
        contract = self._contract(wage=30000, hourly_wage=50, monthly_ctc=40000)
        contract.clean()
        self.assertEqual(contract.wage, 0)
        self.assertIsNone(contract.hourly_wage)
        self.assertIsNone(contract.monthly_ctc)
        self.assertEqual(contract.pay_rate, 0)

    def test_a_gross_up_structure_without_basic_is_allowed(self):
        structure = SalaryStructure.objects.create(title="Casual GU", structure_mode="gross_up")
        self._contract(salary_structure_id=structure).clean()

    def test_a_ctc_down_structure_is_refused(self):
        structure = SalaryStructure.objects.create(title="Casual CTC", structure_mode="ctc_down")
        with self.assertRaises(ValidationError) as caught:
            self._contract(salary_structure_id=structure).clean()
        self.assertIn("salary_structure_id", caught.exception.message_dict)

    def test_a_filing_status_based_on_basic_pay_is_refused(self):
        filing = make_filing_status("On basic", based_on="basic_pay")
        with self.assertRaises(ValidationError) as caught:
            self._contract(filing_status=filing).clean()
        self.assertIn("filing_status", caught.exception.message_dict)

    def test_a_filing_status_based_on_taxable_gross_is_allowed(self):
        filing = make_filing_status("On taxable gross", based_on="taxable_gross_pay")
        self._contract(filing_status=filing).clean()

    def test_the_structure_does_not_count_them_as_missing_basic(self):
        structure = SalaryStructure.objects.create(title="Mixed", structure_mode="gross_up")
        _task_contract(self.employee, salary_structure_id=structure)
        self.assertEqual(structure.employees_missing_basic, 0)
        rows = structure.employee_rows
        self.assertEqual(len(rows), 1)
        self.assertFalse(rows[0]["no_basic"])


class PaidPerTaskRunTests(TestCase):
    """
    A payslip of zero is no use, so someone paid only per task with no
    confirmed task pay is left out of the run, not paid nothing.
    """

    def setUp(self):
        company = make_company("Casual Run Co")
        self.employee = make_employee(company=company, email="run@test.horilla")
        Contract.objects.filter(employee_id=self.employee).delete()
        _task_contract(self.employee)

    def _entry(self, status="draft", amount=1000.0):
        entry = PayAdjustment.objects.create(
            employee_id=self.employee,
            kind="arrears",
            title="Task earnings",
            amount=amount,
            pay_date=PERIOD_END,
            status="draft",
        )
        if status == "approved":
            entry.approve()
        return entry

    def _scoped(self):
        return eligible_employees([self.employee], PERIOD_START, PERIOD_END)

    def test_no_task_pay_leaves_them_out(self):
        ok, excluded = self._scoped()
        self.assertEqual(ok, [])
        self.assertEqual(len(excluded), 1)
        self.assertIn("no task pay", str(excluded[0][1]))

    def test_only_draft_task_pay_leaves_them_out_and_says_so(self):
        self._entry("draft")
        ok, excluded = self._scoped()
        self.assertEqual(ok, [])
        self.assertIn("draft", str(excluded[0][1]))

    def test_confirmed_task_pay_puts_them_in(self):
        self._entry("approved")
        ok, excluded = self._scoped()
        self.assertEqual(ok, [self.employee])
        self.assertEqual(excluded, [])

    def test_a_waged_contract_is_not_affected(self):
        Contract.objects.filter(employee_id=self.employee).delete()
        make_active_contract(self.employee, wage=30000.0)
        ok, _excluded = self._scoped()
        self.assertEqual(ok, [self.employee])

    def test_generation_skips_them_when_task_pay_went_back_to_draft(self):
        entry = self._entry("approved")
        batch = create_batch(
            name="Casual run",
            start_date=PERIOD_START,
            end_date=PERIOD_END,
            employees=[self.employee],
        )
        entry.refresh_from_db()
        entry.revert()
        generate_slice(batch)
        line = PayrollBatchLine.objects.get(payroll_batch=batch)
        self.assertEqual(line.status, PayrollBatchLine.SKIPPED)
        self.assertIsNone(line.payslip)
        self.assertFalse(Payslip.objects.filter(employee_id=self.employee).exists())

    def test_generation_pays_confirmed_task_pay(self):
        self._entry("approved", amount=6400.0)
        batch = create_batch(
            name="Casual run paid",
            start_date=PERIOD_START,
            end_date=PERIOD_END,
            employees=[self.employee],
        )
        generate_slice(batch)
        line = PayrollBatchLine.objects.get(payroll_batch=batch)
        self.assertEqual(line.status, PayrollBatchLine.DONE, line.message)
        self.assertAlmostEqual(line.payslip.gross_pay, 6400.0, places=2)

    def test_drafts_beside_confirmed_pay_are_a_warning(self):
        self._entry("approved")
        self._entry("draft")
        problems = task_pay_warnings(self.employee, PERIOD_START, PERIOD_END)
        self.assertEqual([severity for severity, _message in problems], [WARNING])
        self.assertIn("Draft", str(problems[0][1]))

    def test_no_drafts_says_nothing(self):
        self._entry("approved")
        self.assertEqual(task_pay_warnings(self.employee, PERIOD_START, PERIOD_END), [])