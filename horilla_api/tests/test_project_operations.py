"""Project API operations the classic screens depend on."""

import io
import json
from datetime import date, timedelta

import pandas as pd
from django.contrib.auth.models import Permission
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from rest_framework.test import APIClient

from horilla.testkit import make_company, make_employee, make_user
from project.models import Project, ProjectStage, Task, TimeSheet


def _perm(*codenames):
    return Permission.objects.filter(
        content_type__app_label="project", codename__in=codenames
    )


class ProjectOperationTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.company = make_company("Project Ops")
        cls.today = date.today()

    def setUp(self):
        self.client = APIClient()

    def _user(self, username, *codenames):
        user = make_user(username, password="secret123")
        employee = make_employee(
            company=self.company,
            email=f"{username}@test.horilla",
            user=user,
            first_name=username,
        )
        if codenames:
            user.user_permissions.add(*_perm(*codenames))
        return user, employee

    def _auth(self, user):
        self.client.force_authenticate(user=type(user).objects.get(pk=user.pk))

    def _project(self, title, **overrides):
        values = {
            "title": title,
            "status": "new",
            "start_date": self.today,
            "description": "Work site",
        }
        values.update(overrides)
        return Project.objects.create(**values)

    def test_create_project_task_and_timesheet_with_ui_field_names(self):
        user, employee = self._user(
            "ops_creator",
            "add_project",
            "add_task",
            "add_timesheet",
            "view_project",
            "view_task",
            "view_timesheet",
        )
        self._auth(user)
        created = self.client.post(
            "/api/v1/project/project/",
            {
                "title": "Site alpha",
                "status": "new",
                "start_date": self.today.isoformat(),
                "description": "Casual crew",
                "managers_ids": [employee.id],
            },
            format="json",
        )
        self.assertEqual(created.status_code, 201, created.content)
        self.assertEqual(created.data["task_count"], 0)
        project_id = created.data["id"]
        stage_id = created.data["project_stages"][0]["id"]

        task = self.client.post(
            "/api/v1/project/task/",
            {
                "title": "Unload cement",
                "description": "Bay 2",
                "project_id": project_id,
                "stage_id": stage_id,
                "allocated_hours": "01:30",
                "task_members_ids": [employee.id],
            },
            format="json",
        )
        self.assertEqual(task.status_code, 201, task.content)
        self.assertEqual(task.data["allocated_seconds"], 5400)
        self.assertEqual(task.data["timesheet_spent_seconds"], 0)
        self.assertEqual(task.data["project"]["id"], project_id)

        sheet = self.client.post(
            "/api/v1/project/timesheet/",
            {
                "project_id_write": project_id,
                "task_id_write": task.data["id"],
                "employee_id_write": employee.id,
                "time_spent": "01:00",
                "description": "Morning shift",
                "status": "in_Progress",
            },
            format="json",
        )
        self.assertEqual(sheet.status_code, 201, sheet.content)
        self.assertEqual(sheet.data["project_id"]["title"], "Site alpha")

    def test_end_date_before_start_is_rejected(self):
        user, _employee = self._user("ops_dates", "add_project")
        self._auth(user)
        response = self.client.post(
            "/api/v1/project/project/",
            {
                "title": "Backwards",
                "start_date": self.today.isoformat(),
                "end_date": (self.today - timedelta(days=1)).isoformat(),
                "description": "Dates",
            },
            format="json",
        )
        self.assertEqual(response.status_code, 400)

    def test_stage_from_another_project_is_rejected(self):
        user, _employee = self._user("ops_stage", "add_task", "view_task")
        self._auth(user)
        first = self._project("First site")
        second = self._project("Second site")
        other_stage = ProjectStage.objects.filter(project=second).first()
        response = self.client.post(
            "/api/v1/project/task/",
            {
                "title": "Wrong column",
                "description": "Mismatch",
                "project_id": first.id,
                "stage_id": other_stage.id,
            },
            format="json",
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("stage_id", response.data)

    def test_nested_task_create_keeps_the_project(self):
        user, _employee = self._user("ops_nested", "add_task")
        self._auth(user)
        project = self._project("Nested site")
        stage = ProjectStage.objects.filter(project=project).first()
        response = self.client.post(
            f"/api/v1/project/project/{project.id}/task/",
            {
                "title": "On this site",
                "description": "Created under the project",
                "stage_id": stage.id,
            },
            format="json",
        )
        self.assertEqual(response.status_code, 201, response.content)
        self.assertEqual(response.data["project"]["id"], project.id)

    def test_manager_without_view_permission_reads_their_project(self):
        user, employee = self._user("ops_manager")
        own = self._project("Managed site")
        own.managers.add(employee)
        self._project("Someone else's site")
        self._auth(user)
        listing = self.client.get("/api/v1/project/project/")
        self.assertEqual(listing.status_code, 200)
        self.assertIn("Managed site", listing.content.decode())
        self.assertNotIn("Someone else's site", listing.content.decode())
        detail = self.client.get(f"/api/v1/project/project/{own.id}/")
        self.assertEqual(detail.status_code, 200)

    def test_timesheet_detail_is_hidden_from_other_employees(self):
        owner, owner_employee = self._user(
            "ops_sheet_owner", "add_timesheet", "view_timesheet"
        )
        other, _other_employee = self._user("ops_sheet_other")
        project = self._project("Timesheet site")
        stage = ProjectStage.objects.filter(project=project).first()
        task = Task.objects.create(
            title="Logged work",
            project=project,
            stage=stage,
            description="Hours",
        )
        task.task_members.add(owner_employee)
        self._auth(owner)
        created = self.client.post(
            "/api/v1/project/timesheet/",
            {
                "project_id_write": project.id,
                "task_id_write": task.id,
                "employee_id_write": owner_employee.id,
                "description": "Logged",
                "time_spent": "00:30",
            },
            format="json",
        )
        self.assertEqual(created.status_code, 201, created.content)
        self._auth(other)
        hidden = self.client.get(f"/api/v1/project/timesheet/{created.data['id']}/")
        self.assertEqual(hidden.status_code, 404)
        self.assertNotIn("Logged", hidden.content.decode())

    def test_stage_reorder_and_past_due_task_still_moves(self):
        user, employee = self._user("ops_board", "change_projectstage", "change_task")
        self._auth(user)
        project = self._project("Board site")
        project.managers.add(employee)
        first = ProjectStage.objects.filter(project=project).first()
        second = ProjectStage.objects.create(title="Doing", project=project)
        moved = self.client.post(
            f"/api/v1/project/project/{project.id}/stage/reorder/",
            {"sequence": {str(second.id): 1, str(first.id): 2}},
            format="json",
        )
        self.assertEqual(moved.status_code, 200, moved.content)
        self.assertTrue(moved.data["change"])
        first.refresh_from_db()
        second.refresh_from_db()
        self.assertEqual(second.sequence, 1)
        self.assertEqual(first.sequence, 2)

        past_due = Task.objects.create(
            title="Entered late",
            project=project,
            stage=first,
            description="Past",
            end_date=self.today - timedelta(days=1),
        )
        dragged = self.client.post(
            f"/api/v1/project/project/{project.id}/task/reorder/",
            {"stage_id": second.id, "sequence": {str(past_due.id): 1}},
            format="json",
        )
        self.assertEqual(dragged.status_code, 200, dragged.content)
        past_due.refresh_from_db()
        self.assertEqual(past_due.stage_id, second.id)

    def test_backdated_task_is_never_expired_automatically(self):
        user, employee = self._user(
            "ops_late", "add_task", "change_task", "view_task"
        )
        self._auth(user)
        project = self._project(
            "Late site", start_date=self.today - timedelta(days=60)
        )
        stage = ProjectStage.objects.filter(project=project).first()
        ended = self.today - timedelta(days=30)
        created = self.client.post(
            "/api/v1/project/task/",
            {
                "title": "Entered after the fact",
                "description": "Backdated",
                "project_id": project.id,
                "stage_id": stage.id,
                "start_date": (ended - timedelta(days=2)).isoformat(),
                "end_date": ended.isoformat(),
            },
            format="json",
        )
        self.assertEqual(created.status_code, 201, created.content)
        self.assertEqual(created.data["status"], "to_do")
        url = f"/api/v1/project/task/{created.data['id']}/"

        # Saving a past-due task leaves its status alone.
        renamed = self.client.put(url, {"title": "Still open"}, format="json")
        self.assertEqual(renamed.status_code, 200, renamed.content)
        self.assertEqual(renamed.data["status"], "to_do")

        # The completion date is the one entered, not the day it was keyed in.
        done = self.client.put(
            url,
            {"status": "completed", "completed_at": ended.isoformat()},
            format="json",
        )
        self.assertEqual(done.status_code, 200, done.content)
        task = Task.objects.get(pk=created.data["id"])
        self.assertEqual(task.status, "completed")
        self.assertEqual(task.completed_at, ended)

        # A later save without the date keeps it.
        again = self.client.put(url, {"title": "Closed out"}, format="json")
        self.assertEqual(again.status_code, 200, again.content)
        task.refresh_from_db()
        self.assertEqual(task.completed_at, ended)

    def test_expired_task_can_be_completed_and_defaults_to_today(self):
        user, employee = self._user("ops_expired", "change_task", "view_task")
        self._auth(user)
        project = self._project("Expired site")
        stage = ProjectStage.objects.filter(project=project).first()
        task = Task.objects.create(
            title="Marked expired",
            project=project,
            stage=stage,
            description="Past",
            status="expired",
            end_date=self.today - timedelta(days=1),
        )
        url = f"/api/v1/project/task/{task.id}/"
        done = self.client.put(url, {"status": "completed"}, format="json")
        self.assertEqual(done.status_code, 200, done.content)
        task.refresh_from_db()
        self.assertEqual(task.status, "completed")
        self.assertEqual(task.completed_at, self.today)

        reopened = self.client.put(url, {"status": "in_progress"}, format="json")
        self.assertEqual(reopened.status_code, 200, reopened.content)
        task.refresh_from_db()
        self.assertEqual(task.status, "in_progress")
        self.assertIsNone(task.completed_at)

    def test_backdated_project_is_never_expired_automatically(self):
        user, employee = self._user(
            "ops_old_project", "add_project", "change_project", "view_project"
        )
        self._auth(user)
        ended = self.today - timedelta(days=30)
        created = self.client.post(
            "/api/v1/project/project/",
            {
                "title": "Entered after the fact",
                "status": "in_progress",
                "start_date": (ended - timedelta(days=30)).isoformat(),
                "end_date": ended.isoformat(),
                "description": "Backdated",
                "managers_ids": [employee.id],
            },
            format="json",
        )
        self.assertEqual(created.status_code, 201, created.content)
        self.assertEqual(created.data["status"], "in_progress")
        url = f"/api/v1/project/project/{created.data['id']}/"

        done = self.client.put(url, {"status": "completed"}, format="json")
        self.assertEqual(done.status_code, 200, done.content)
        self.assertEqual(done.data["status"], "completed")

        renamed = self.client.put(url, {"title": "Closed out"}, format="json")
        self.assertEqual(renamed.status_code, 200, renamed.content)
        self.assertEqual(renamed.data["status"], "completed")

    def test_bulk_archive_skips_a_project_the_user_cannot_change(self):
        user, employee = self._user("ops_bulk")
        own = self._project("Archivable")
        own.managers.add(employee)
        other = self._project("Locked")
        self._auth(user)
        response = self.client.post(
            "/api/v1/project/project/bulk-archive/",
            {"ids": [own.id, other.id], "is_active": False},
            format="json",
        )
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.data["done"], 1)
        self.assertEqual(response.data["failed"], 1)
        own.refresh_from_db()
        other.refresh_from_db()
        self.assertFalse(own.is_active)
        self.assertTrue(other.is_active)

    def test_import_one_valid_row(self):
        user, _employee = self._user("ops_import", "add_project", "view_project")
        self._auth(user)
        upload = SimpleUploadedFile(
            "projects.csv",
            (
                "Title,Status,Start Date,Description\n"
                f"Imported site,new,{self.today.isoformat()},Brought in from a file\n"
            ).encode(),
            content_type="text/csv",
        )
        response = self.client.post(
            "/api/v1/project/project/import/",
            {"file": upload},
            format="multipart",
        )
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.data["created_count"], 1)
        self.assertEqual(response.data["error_count"], 0)
        self.assertTrue(Project.objects.filter(title="Imported site").exists())

    def test_dashboard_task_kpi_and_timesheet_widgets(self):
        user, _employee = self._user("ops_dash", "view_project")
        self._auth(user)
        kpi = self.client.get("/api/v1/project/dashboard/task-kpi/")
        self.assertEqual(kpi.status_code, 200, kpi.content)
        kpi_body = json.loads(kpi.content)
        for key in (
            "today_tasks",
            "nearing_deadline_tasks",
            "overdue_tasks",
            "projects_ending_soon",
        ):
            self.assertIn(key, kpi_body)
        trend = self.client.get(
            "/api/v1/project/dashboard/timesheet/",
            {
                "from_date": self.today.replace(day=1).isoformat(),
                "to_date": self.today.isoformat(),
            },
        )
        self.assertEqual(trend.status_code, 200, trend.content)
        trend_body = json.loads(trend.content)
        for key in ("labels", "series", "total_hours", "entries"):
            self.assertIn(key, trend_body)

    def test_export_contains_a_visible_project(self):
        user, _employee = self._user("ops_export", "view_project")
        self._project("Exportable site")
        self._auth(user)
        response = self.client.post("/api/v1/project/project/export/", {}, format="json")
        self.assertEqual(response.status_code, 200, response.content)
        frame = pd.read_excel(io.BytesIO(response.content))
        self.assertIn("Exportable site", list(frame["Title"]))
