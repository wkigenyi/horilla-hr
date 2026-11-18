"""Payable Horilla Tasks posted into draft Pay Adjustments."""

from datetime import date

from django.core.exceptions import ValidationError
from django.test import TestCase

from horilla.testkit import make_company, make_employee
from payroll.methods.task_pay import post_task_earnings, preview_task_earnings
from payroll.models.models import PayAdjustment, Payslip
from project.models import Project, Task, TaskPayAllocation


class TaskCompletionAndAllocationTests(TestCase):
    def setUp(self):
        self.company = make_company("Task Pay Co")
        self.adam = make_employee(
            company=self.company, email="adam-alloc@test.horilla", first_name="Adam"
        )
        self.project = Project.objects.create(
            title="Jobs",
            status="new",
            start_date=date(2026, 1, 1),
            description="Piece work",
            company_id=self.company,
        )

    def _task(self, **fields):
        values = {
            "title": "Job A",
            "project": self.project,
            "description": "Do the work",
            "status": "to_do",
        }
        values.update(fields)
        return Task.objects.create(**values)

    def test_completed_at_stamps_and_clears_with_status(self):
        task = self._task()
        self.assertIsNone(task.completed_at)
        task.status = "completed"
        task.save()
        task.refresh_from_db()
        self.assertEqual(task.completed_at, date.today())
        task.status = "in_progress"
        task.save()
        task.refresh_from_db()
        self.assertIsNone(task.completed_at)

    def test_allocation_requires_positive_amount(self):
        task = self._task()
        task.task_members.add(self.adam)
        row = TaskPayAllocation(task=task, employee=self.adam, amount=0)
        with self.assertRaises(ValidationError) as caught:
            row.full_clean()
        self.assertIn("amount", caught.exception.message_dict)

    def test_allocation_rejects_non_members(self):
        task = self._task()
        row = TaskPayAllocation(task=task, employee=self.adam, amount=50)
        with self.assertRaises(ValidationError) as caught:
            row.full_clean()
        self.assertIn("employee", caught.exception.message_dict)


class TaskPayPostingTests(TestCase):
    def setUp(self):
        self.company = make_company("Task Post Co")
        self.adam = make_employee(
            company=self.company, email="adam-task@test.horilla", first_name="Adam"
        )
        self.bea = make_employee(
            company=self.company, email="bea-task@test.horilla", first_name="Bea"
        )
        self.project = Project.objects.create(
            title="Site",
            status="new",
            start_date=date(2026, 3, 1),
            description="Site work",
            company_id=self.company,
        )
        self.start = date(2026, 3, 1)
        self.end = date(2026, 3, 31)

    def _completed_task(self, title, member_amounts, completed_at=None):
        task = Task(
            title=title,
            project=self.project,
            description=title,
            status="completed",
            is_payable=True,
            completed_at=completed_at or date(2026, 3, 15),
        )
        task.save()
        members = [employee for employee, _amount in member_amounts]
        task.task_members.set(members)
        for employee, amount in member_amounts:
            TaskPayAllocation.objects.create(
                task=task, employee=employee, amount=amount
            )
        return task

    def test_preview_uses_individual_amounts_and_skips_empty(self):
        self._completed_task("Paint", [(self.adam, 500), (self.bea, 300)])
        lonely = Task(
            title="No crew",
            project=self.project,
            description="Orphan",
            status="completed",
            is_payable=True,
            completed_at=date(2026, 3, 10),
        )
        lonely.save()
        preview = preview_task_earnings(self.start, self.end, company=self.company)
        by_id = {row["employee_id"]: row for row in preview["employees"]}
        self.assertEqual(by_id[self.adam.pk]["amount"], 500.0)
        self.assertEqual(by_id[self.bea.pk]["amount"], 300.0)
        self.assertEqual(len(preview["skips"]), 1)
        self.assertEqual(preview["skips"][0]["task_id"], lonely.pk)

    def test_post_is_idempotent_and_links_tasks(self):
        task = self._completed_task("Fix", [(self.adam, 80)])
        first = post_task_earnings(self.start, self.end, company=self.company)
        self.assertEqual(len(first["created"]), 1)
        self.assertEqual(first["created"][0]["amount"], 80.0)
        task.refresh_from_db()
        self.assertEqual(task.payroll_adjustment_id, first["created"][0]["id"])
        entry = PayAdjustment.objects.get(pk=first["created"][0]["id"])
        self.assertEqual(entry.status, "draft")
        self.assertEqual(entry.kind, "arrears")
        second = post_task_earnings(self.start, self.end, company=self.company)
        self.assertEqual(second["created"], [])
        self.assertEqual(PayAdjustment.objects.filter(employee_id=self.adam).count(), 1)

    def test_month_with_payslip_skips_the_employee(self):
        self._completed_task("Wall", [(self.adam, 60)])
        Payslip.objects.create(
            employee_id=self.adam,
            start_date=date(2026, 3, 1),
            end_date=date(2026, 3, 31),
            pay_head_data={},
        )
        result = post_task_earnings(self.start, self.end, company=self.company)
        self.assertEqual(result["created"], [])
        self.assertEqual(len(result["employees_skipped"]), 1)
        self.assertEqual(result["employees_skipped"][0]["employee_id"], self.adam.pk)

    def test_delete_draft_unlinks_tasks_for_repost(self):
        task = self._completed_task("Roof", [(self.adam, 70)])
        posted = post_task_earnings(self.start, self.end, company=self.company)
        entry = PayAdjustment.objects.get(pk=posted["created"][0]["id"])
        entry.delete()
        task.refresh_from_db()
        self.assertIsNone(task.payroll_adjustment_id)
        again = post_task_earnings(self.start, self.end, company=self.company)
        self.assertEqual(len(again["created"]), 1)

    def test_revert_unlinks_tasks_for_repost(self):
        task = self._completed_task("Floor", [(self.adam, 90)])
        posted = post_task_earnings(self.start, self.end, company=self.company)
        entry = PayAdjustment.objects.get(pk=posted["created"][0]["id"])
        entry.approve()
        entry.revert()
        task.refresh_from_db()
        self.assertIsNone(task.payroll_adjustment_id)
        again = post_task_earnings(self.start, self.end, company=self.company)
        self.assertEqual(len(again["created"]), 1)
        self.assertNotEqual(again["created"][0]["id"], entry.pk)
