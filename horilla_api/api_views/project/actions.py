"""Board, bulk, import, and export actions for the project screens.

The classic views return HTML. These return JSON (or the same spreadsheet)
and apply the same permission each screen already uses.
"""

import logging
from io import BytesIO

import numpy as np
import pandas as pd
from django.http import HttpResponse
from django.utils.translation import gettext_lazy as _
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from base.auth_backends import company_scoped_active, get_allowed_company_ids
from base.import_template_data import import_template_frame, write_import_xlsx
from base.methods import get_session_company, has_export_access
from employee.models import Employee
from horilla_api.api_methods.project.access import (
    can_add_task,
    can_archive_or_delete_project,
    can_change_stage,
    can_change_task,
    can_delete_task,
    can_delete_timesheet,
    employee_of,
    visible_projects,
)
from project.methods import process_project_records, valid_project_import_headers
from project.models import Project, ProjectStage, Task, TimeSheet

from ...api_decorators.base.decorators import permission_required

logger = logging.getLogger(__name__)


def _denied():
    return Response({"message": _("No permission")}, status=401)


def _id_list(value):
    if not isinstance(value, (list, tuple)) or not value:
        return None
    ids = []
    for item in value:
        try:
            ids.append(int(item))
        except (TypeError, ValueError):
            return None
    return ids


def _sequence_map(value):
    if not isinstance(value, dict) or not value:
        return None
    parsed = {}
    for key, item in value.items():
        try:
            parsed[int(key)] = int(item)
        except (TypeError, ValueError):
            return None
    return parsed


def _bool(value):
    if isinstance(value, bool):
        return value
    if isinstance(value, str) and value.lower() in ("true", "false"):
        return value.lower() == "true"
    return None


class ProjectBulkArchiveAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        ids = _id_list(request.data.get("ids"))
        is_active = _bool(request.data.get("is_active"))
        if ids is None or is_active is None:
            return Response(
                {"error": _("Provide ids and is_active true or false.")},
                status=400,
            )
        done = failed = 0
        for project_id in ids:
            project = Project.objects.filter(pk=project_id).first()
            if project and can_archive_or_delete_project(request.user, project):
                project.is_active = is_active
                project.save()
                done += 1
            else:
                failed += 1
        return Response({"done": done, "failed": failed})


class ProjectBulkDeleteAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        ids = _id_list(request.data.get("ids"))
        if ids is None:
            return Response({"error": _("Provide ids.")}, status=400)
        done = failed = 0
        for project_id in ids:
            project = Project.objects.filter(pk=project_id).first()
            if not project or not can_archive_or_delete_project(request.user, project):
                failed += 1
                continue
            try:
                project.delete()
                done += 1
            except Exception:
                logger.exception("project bulk delete failed")
                failed += 1
        return Response({"done": done, "failed": failed})


class TaskBulkArchiveAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        ids = _id_list(request.data.get("ids"))
        is_active = _bool(request.data.get("is_active"))
        if ids is None or is_active is None:
            return Response(
                {"error": _("Provide ids and is_active true or false.")},
                status=400,
            )
        done = failed = 0
        for task_id in ids:
            task = Task.objects.filter(pk=task_id).first()
            if task and can_change_task(request.user, task):
                task.is_active = is_active
                task.save()
                done += 1
            else:
                failed += 1
        return Response({"done": done, "failed": failed})


class TaskBulkDeleteAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        ids = _id_list(request.data.get("ids"))
        if ids is None:
            return Response({"error": _("Provide ids.")}, status=400)
        done = failed = 0
        for task_id in ids:
            task = Task.objects.filter(pk=task_id).first()
            if not task or not can_delete_task(request.user, task):
                failed += 1
                continue
            try:
                task.delete()
                done += 1
            except Exception:
                logger.exception("task bulk delete failed")
                failed += 1
        return Response({"done": done, "failed": failed})


class TimeSheetBulkDeleteAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        ids = _id_list(request.data.get("ids"))
        if ids is None:
            return Response({"error": _("Provide ids.")}, status=400)
        done = failed = 0
        for timesheet_id in ids:
            timesheet = TimeSheet.objects.filter(pk=timesheet_id).first()
            if not timesheet or not can_delete_timesheet(request, timesheet):
                failed += 1
                continue
            try:
                timesheet.delete()
                done += 1
            except Exception:
                logger.exception("timesheet bulk delete failed")
                failed += 1
        return Response({"done": done, "failed": failed})


class StageReorderAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, project_id):
        project = Project.objects.filter(pk=project_id).first()
        if project is None:
            return Response({"error": _("Project not found")}, status=404)
        sequence = _sequence_map(request.data.get("sequence"))
        if sequence is None:
            return Response({"error": _("Provide a sequence map.")}, status=400)
        stages = {
            stage.id: stage
            for stage in ProjectStage.objects.filter(
                project_id=project_id, id__in=sequence
            )
        }
        if set(stages) != set(sequence):
            return Response(
                {"error": _("Every stage must belong to this project.")},
                status=400,
            )
        if not can_change_stage(request.user, next(iter(stages.values()))):
            return _denied()
        changed = False
        for stage_id, position in sequence.items():
            if stages[stage_id].sequence != position:
                ProjectStage.objects.filter(pk=stage_id).update(sequence=position)
                changed = True
        return Response({"change": changed})


class TaskReorderAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, project_id):
        project = Project.objects.filter(pk=project_id).first()
        if project is None:
            return Response({"error": _("Project not found")}, status=404)
        sequence = _sequence_map(request.data.get("sequence"))
        try:
            stage_id = int(request.data.get("stage_id"))
        except (TypeError, ValueError):
            stage_id = None
        stage = (
            ProjectStage.objects.filter(pk=stage_id, project_id=project_id).first()
            if stage_id
            else None
        )
        if sequence is None or stage is None:
            return Response(
                {"error": _("Provide stage_id and a sequence map.")},
                status=400,
            )
        tasks = {
            task.id: task
            for task in Task.objects.filter(project_id=project_id, id__in=sequence)
        }
        if set(tasks) != set(sequence):
            return Response(
                {"error": _("Every task must belong to this project.")},
                status=400,
            )
        for task in tasks.values():
            if not can_change_task(request.user, task):
                return _denied()
        changed = False
        for task in tasks.values():
            if task.stage_id != stage.id:
                task.stage = stage
                task.save()
                changed = True
        for task_id, position in sequence.items():
            if tasks[task_id].sequence != position:
                Task.objects.filter(pk=task_id).update(sequence=position)
                changed = True
        return Response({"change": changed})


class ProjectMembersAPIView(APIView):
    """Employees the timesheet form may log time for on this task."""

    permission_classes = [IsAuthenticated]

    def get(self, request, project_id):
        project = Project.objects.filter(pk=project_id).first()
        task = Task.objects.filter(
            pk=request.GET.get("task_id"), project_id=project_id
        ).first()
        if project is None or task is None:
            return Response({"error": _("Project or task not found")}, status=404)
        allowed = (
            request.user.has_perm("project.add_timesheet")
            or request.user.has_perm("project.view_project")
            or visible_projects(request.user).filter(pk=project_id).exists()
            or can_add_task(request.user, project)
        )
        if not allowed:
            return Response({"error": _("Project or task not found")}, status=404)
        employee = employee_of(request.user)
        if employee is None:
            members = Employee.objects.none()
        elif project.managers.filter(pk=employee.pk).exists():
            members = (
                task.task_managers.all()
                | task.task_members.all()
                | Employee.objects.filter(pk=employee.pk)
            ).distinct()
        elif task.task_managers.filter(pk=employee.pk).exists():
            members = (
                task.task_members.all() | Employee.objects.filter(pk=employee.pk)
            ).distinct()
        else:
            members = Employee.objects.filter(pk=employee.pk)
        return Response(
            [
                {
                    "id": member.id,
                    "employee_first_name": member.employee_first_name,
                    "employee_last_name": member.employee_last_name,
                    "get_full_name": member.get_full_name(),
                }
                for member in members
            ]
        )


class ProjectImportTemplateAPIView(APIView):
    permission_classes = [IsAuthenticated]

    @permission_required("project.add_project")
    def get(self, request):
        data_frame = import_template_frame("project")
        response = HttpResponse(content_type="application/ms-excel")
        response["Content-Disposition"] = 'attachment; filename="project_template.xlsx"'
        write_import_xlsx(data_frame, response)
        return response


class ProjectImportAPIView(APIView):
    permission_classes = [IsAuthenticated]

    @permission_required("project.add_project")
    def post(self, request):
        upload = request.FILES.get("file")
        if not upload:
            return Response({"error": _("No file uploaded.")}, status=400)
        extension = upload.name.rsplit(".", 1)[-1].lower()
        try:
            if extension == "csv":
                data_frame = pd.read_csv(upload)
            elif extension in ("xls", "xlsx"):
                data_frame = pd.read_excel(upload)
            else:
                return Response(
                    {
                        "error": _(
                            "Unsupported file format. Please upload a CSV or Excel file."
                        )
                    },
                    status=400,
                )
        except Exception as exception:
            logger.exception("project import read failed")
            return Response(
                {"error": _("Failed to read file.") + f" {exception}"},
                status=400,
            )
        valid, error_message = valid_project_import_headers(data_frame)
        if not valid:
            return Response({"error": str(error_message)}, status=400)
        allowed_ids = None
        if company_scoped_active() and not request.user.is_superuser:
            allowed_ids = set(get_allowed_company_ids(request.user) or [])
        created_count, error_list = process_project_records(
            data_frame.astype(object).replace({np.nan: None}),
            selected_company=get_session_company(request),
            allowed_ids=allowed_ids,
        )
        return Response(
            {
                "created_count": created_count,
                "error_count": len(error_list),
                "errors": [_json_row(row) for row in error_list],
            }
        )


def _json_row(row):
    safe = {}
    for key, value in row.items():
        if value is None or (isinstance(value, float) and pd.isna(value)):
            safe[str(key)] = None
        elif hasattr(value, "isoformat"):
            safe[str(key)] = value.isoformat()
        elif isinstance(value, (str, int, float, bool)):
            safe[str(key)] = value
        else:
            safe[str(key)] = str(value)
    return safe


class ProjectExportAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        if not has_export_access(request, Project):
            return _denied()
        projects = visible_projects(request.user)
        ids = request.data.get("ids")
        if ids not in (None, "", []):
            parsed = _id_list(ids)
            if parsed is None:
                return Response({"error": _("Provide ids.")}, status=400)
            projects = projects.filter(pk__in=parsed)
        headers = [
            "Title",
            "Managers",
            "Status",
            "Start Date",
            "End Date",
            "Description",
        ]
        rows = []
        for project in projects.distinct():
            rows.append(
                {
                    "Title": project.title,
                    "Managers": ", ".join(
                        f"{manager.employee_first_name or ''} {manager.employee_last_name or ''}".strip()
                        for manager in project.managers.all()
                    ),
                    "Status": project.status,
                    "Start Date": project.start_date.strftime("%Y-%m-%d")
                    if project.start_date
                    else "",
                    "End Date": project.end_date.strftime("%Y-%m-%d")
                    if project.end_date
                    else "",
                    "Description": project.description or "",
                }
            )
        frame = pd.DataFrame(rows, columns=headers)
        buffer = BytesIO()
        with pd.ExcelWriter(buffer, engine="xlsxwriter") as writer:
            frame.to_excel(writer, sheet_name="Project details", index=False)
        response = HttpResponse(
            buffer.getvalue(),
            content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
        response["Content-Disposition"] = 'attachment; filename="project details.xlsx"'
        return response
