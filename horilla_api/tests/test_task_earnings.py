"""API: preview and post task earnings into draft pay adjustments."""

from datetime import date
from unittest import mock

from django.contrib.auth.models import Permission
from django.test import TestCase
from rest_framework.test import APIClient

from horilla.horilla_middlewares import set_selected_company
from horilla.testkit import make_company, make_employee, make_user
from payroll.models.models import PayAdjustment
from project.models import Project, Task, TaskPayAllocation


class TaskEarningsApiTests(TestCase):
    def setUp(self):
        set_selected_company(None)
        self.client = APIClient()
        self.company = make_company("Task Earn Co")
        self.user = make_user("task_earn_api", password="secret123", is_superuser=True)
        self.employee = make_employee(
            company=self.company,
            email="task_earn@test.horilla",
            first_name="Ada",
            user=self.user,
        )
        self.other = make_employee(
            company=self.company,
            email="task_earn_other@test.horilla",
            first_name="Bea",
        )
        self.client.force_authenticate(user=self.user)
        self.project = Project.objects.create(
            title="Billable",
            status="new",
            start_date=date(2026, 4, 1),
            description="Work",
            company_id=self.company,
        )
        self.task = Task(
            title="Install",
            project=self.project,
            description="Install kit",
            status="completed",
            is_payable=True,
            completed_at=date(2026, 4, 12),
        )
        self.task.save()
        self.task.task_members.add(self.employee, self.other)
        TaskPayAllocation.objects.create(
            task=self.task, employee=self.employee, amount=120
        )
        TaskPayAllocation.objects.create(
            task=self.task, employee=self.other, amount=80
        )

    def tearDown(self):
        set_selected_company(None)

    def test_preview_and_post_round_trip(self):
        preview = self.client.get(
            "/api/v1/payroll/task-earnings/preview/",
            {"start_date": "2026-04-01", "end_date": "2026-04-30"},
        )
        self.assertEqual(preview.status_code, 200, preview.data)
        by_id = {row["employee_id"]: row for row in preview.data["employees"]}
        self.assertEqual(by_id[self.employee.pk]["amount"], 120.0)
        self.assertEqual(by_id[self.other.pk]["amount"], 80.0)

        posted = self.client.post(
            "/api/v1/payroll/task-earnings/post/",
            {"start_date": "2026-04-01", "end_date": "2026-04-30"},
            format="json",
        )
        self.assertEqual(posted.status_code, 201, posted.data)
        self.assertEqual(len(posted.data["created"]), 2)
        amounts = {row["employee_id"]: row["amount"] for row in posted.data["created"]}
        self.assertEqual(amounts[self.employee.pk], 120.0)
        self.assertEqual(amounts[self.other.pk], 80.0)
        self.assertEqual(
            PayAdjustment.objects.filter(status="draft").count(),
            2,
        )

        again = self.client.post(
            "/api/v1/payroll/task-earnings/post/",
            {"start_date": "2026-04-01", "end_date": "2026-04-30"},
            format="json",
        )
        self.assertEqual(again.status_code, 200, again.data)
        self.assertEqual(again.data["created"], [])

    def _preview_names_for(self, selected):
        with mock.patch(
            "horilla_api.api_views.payroll.task_earnings.get_selected_company",
            return_value=selected,
        ):
            preview = self.client.get(
                "/api/v1/payroll/task-earnings/preview/",
                {"start_date": "2026-04-01", "end_date": "2026-04-30"},
            )
        self.assertEqual(preview.status_code, 200, preview.data)
        return {
            title for row in preview.data["employees"] for title in row["titles"]
        }

    def test_scope_is_the_selected_company_not_the_callers_own(self):
        # The caller works for Task Earn Co; the work was done for a sister
        # company. Posting used to look only in the caller's own employer.
        sister = make_company("Task Earn Sister")
        project = Project.objects.create(
            title="Sister work",
            status="new",
            start_date=date(2026, 4, 1),
            description="Work",
            company_id=sister,
        )
        task = Task(
            title="Sister install",
            project=project,
            description="Install kit",
            status="completed",
            is_payable=True,
            completed_at=date(2026, 4, 15),
        )
        task.save()
        task.task_members.add(self.other)
        TaskPayAllocation.objects.create(task=task, employee=self.other, amount=60)

        self.assertEqual(
            self._preview_names_for(None), {"Install", "Sister install"}
        )
        self.assertEqual(self._preview_names_for("all"), {"Install", "Sister install"})
        self.assertEqual(self._preview_names_for(sister.pk), {"Sister install"})
        self.assertEqual(self._preview_names_for(self.company.pk), {"Install"})

    def test_task_serializer_accepts_pay_allocations(self):
        created = self.client.post(
            f"/api/v1/project/project/{self.project.pk}/task/",
            {
                "title": "Wire up",
                "description": "Cabling",
                "status": "to_do",
                "is_payable": True,
                "task_members_ids": [self.employee.pk, self.other.pk],
                "pay_allocations": [
                    {"employee_id": self.employee.pk, "amount": 40},
                    {"employee_id": self.other.pk, "amount": 25},
                ],
            },
            format="json",
        )
        self.assertEqual(created.status_code, 201, created.data)
        self.assertEqual(len(created.data["pay_allocations"]), 2)
        amounts = {
            row["employee_id"]: row["amount"]
            for row in created.data["pay_allocations"]
        }
        self.assertEqual(amounts[self.employee.pk], 40.0)
        self.assertEqual(amounts[self.other.pk], 25.0)

    def test_task_serializer_rejects_non_member_allocation(self):
        stranger = make_employee(
            company=self.company,
            email="stranger@test.horilla",
            first_name="Sam",
        )
        response = self.client.post(
            f"/api/v1/project/project/{self.project.pk}/task/",
            {
                "title": "Bad pay",
                "description": "Nope",
                "status": "to_do",
                "is_payable": True,
                "task_members_ids": [self.employee.pk],
                "pay_allocations": [
                    {"employee_id": stranger.pk, "amount": 10},
                ],
            },
            format="json",
        )
        self.assertEqual(response.status_code, 400, response.data)
        self.assertIn("pay_allocations", response.data)

    def test_missing_permission_is_forbidden(self):
        outsider = make_user("task_earn_outsider", password="secret123")
        make_employee(
            company=self.company,
            email="task_earn_out@test.horilla",
            user=outsider,
        )
        self.client.force_authenticate(user=outsider)
        preview = self.client.get(
            "/api/v1/payroll/task-earnings/preview/",
            {"start_date": "2026-04-01", "end_date": "2026-04-30"},
        )
        self.assertEqual(preview.status_code, 403, preview.data)
        posted = self.client.post(
            "/api/v1/payroll/task-earnings/post/",
            {"start_date": "2026-04-01", "end_date": "2026-04-30"},
            format="json",
        )
        self.assertEqual(posted.status_code, 403, posted.data)

    def test_view_perm_can_preview_but_not_post(self):
        user = make_user("task_earn_viewer", password="secret123")
        make_employee(
            company=self.company,
            email="task_earn_view@test.horilla",
            user=user,
        )
        user.user_permissions.add(
            Permission.objects.get(
                content_type__app_label="payroll", codename="view_payadjustment"
            )
        )
        self.client.force_authenticate(user=user)
        preview = self.client.get(
            "/api/v1/payroll/task-earnings/preview/",
            {"start_date": "2026-04-01", "end_date": "2026-04-30"},
        )
        self.assertEqual(preview.status_code, 200, preview.data)
        posted = self.client.post(
            "/api/v1/payroll/task-earnings/post/",
            {"start_date": "2026-04-01", "end_date": "2026-04-30"},
            format="json",
        )
        self.assertEqual(posted.status_code, 403, posted.data)
