"""
horilla_api/api_views/project/views.py
"""

from django.db.models import Count
from django.utils.translation import gettext_lazy as _
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from horilla_api.api_methods.base.pagination import HorillaPageNumberPagination
from horilla_api.api_methods.project.access import (
    can_add_stage,
    can_add_task,
    can_archive_or_delete_project,
    can_change_project,
    can_change_stage,
    can_change_task,
    can_change_timesheet,
    can_delete_stage,
    can_delete_task,
    can_delete_timesheet,
    notify_project_status,
    visible_projects,
    visible_stages,
    visible_tasks,
    visible_timesheets,
)
from horilla_api.api_serializers.project.serializers import (
    ProjectSerializer,
    ProjectStageSerializer,
    TaskSerializer,
    TimeSheetSerializer,
)
from project.filters import ProjectFilter, TaskAllFilter, TimeSheetFilter
from project.models import Project, ProjectStage, Task, TimeSheet

from ...api_decorators.base.decorators import permission_required
from ...api_methods.base.methods import groupby_queryset


def object_check(cls, pk):
    try:
        obj = cls.objects.get(id=pk)
        return obj
    except cls.DoesNotExist:
        return None


def _denied():
    return Response({"message": _("No permission")}, status=401)


def _projects_for(user):
    return visible_projects(user).annotate(task_count=Count("task", distinct=True))


def _paginate(request, queryset, serializer_class):
    paginator = HorillaPageNumberPagination()
    page = paginator.paginate_queryset(queryset, request)
    serializer = serializer_class(page, many=True)
    return paginator.get_paginated_response(serializer.data)


# Project Views
class ProjectGetCreateAPIView(APIView):
    permission_classes = [IsAuthenticated]
    filter_backends = [DjangoFilterBackend]
    filterset_class = ProjectFilter
    queryset = Project.objects.none()  # For drf-yasg schema generation

    def get_queryset(self, request=None):
        # Handle schema generation for DRF-YASG
        if getattr(self, "swagger_fake_view", False) or request is None:
            return Project.objects.none()
        return _projects_for(request.user)

    def get(self, request, pk=None):
        if pk:
            project = _projects_for(request.user).filter(pk=pk).first()
            if project is None:
                return Response({"error": _("Project not found")}, status=404)
            serializer = ProjectSerializer(project)
            return Response(serializer.data, status=200)

        projects = self.get_queryset(request)
        filterset = self.filterset_class(request.GET, queryset=projects)

        # groupby section
        field_name = request.GET.get("groupby_field", None)
        if field_name:
            url = request.build_absolute_uri()
            return groupby_queryset(request, url, field_name, filterset.qs)

        return _paginate(request, filterset.qs, ProjectSerializer)

    @permission_required("project.add_project")
    def post(self, request):
        serializer = ProjectSerializer(data=request.data)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class ProjectGetUpdateDeleteAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, pk):
        project = _projects_for(request.user).filter(pk=pk).first()
        if project is None:
            return Response({"error": _("Project not found")}, status=404)
        serializer = ProjectSerializer(project)
        return Response(serializer.data, status=200)

    def put(self, request, pk):
        project = object_check(Project, pk)
        if project is None:
            return Response({"error": _("Project not found")}, status=404)
        if not can_change_project(request.user, project):
            return _denied()
        previous_status = project.status
        serializer = ProjectSerializer(project, data=request.data, partial=True)
        if serializer.is_valid():
            serializer.save()
            if serializer.instance.status != previous_status:
                notify_project_status(request, serializer.instance)
            return Response(serializer.data, status=200)
        return Response(serializer.errors, status=400)

    def delete(self, request, pk):
        project = object_check(Project, pk)
        if project is None:
            return Response({"error": _("Project not found")}, status=404)
        if not can_archive_or_delete_project(request.user, project):
            return _denied()
        try:
            project.delete()
            return Response(status=status.HTTP_204_NO_CONTENT)
        except Exception as e:
            return Response({"error": str(e)}, status=400)


# Project Stage Views
class ProjectStageGetCreateAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def get_queryset(self, request=None, project_id=None):
        # Handle schema generation for DRF-YASG
        if getattr(self, "swagger_fake_view", False) or request is None:
            return ProjectStage.objects.none()
        stages = visible_stages(request.user)
        if project_id:
            stages = stages.filter(project_id=project_id)
        return stages

    def get(self, request, project_id=None):
        return _paginate(
            request, self.get_queryset(request, project_id), ProjectStageSerializer
        )

    def post(self, request, project_id=None, **kwargs):
        data = request.data.copy()
        if project_id and not data.get("project_id"):
            data["project_id"] = project_id
        project = Project.objects.filter(pk=data.get("project_id")).first()
        if project is None:
            return Response(
                {"project_id": [_("Project is required.")]},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if not can_add_stage(request.user, project):
            return _denied()
        serializer = ProjectStageSerializer(data=data)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class ProjectStageGetUpdateDeleteAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, pk):
        stage = visible_stages(request.user).filter(pk=pk).first()
        if stage is None:
            return Response({"error": _("ProjectStage not found")}, status=404)
        serializer = ProjectStageSerializer(stage)
        return Response(serializer.data, status=200)

    def put(self, request, pk):
        stage = object_check(ProjectStage, pk)
        if stage is None:
            return Response({"error": _("ProjectStage not found")}, status=404)
        if not can_change_stage(request.user, stage):
            return _denied()
        serializer = ProjectStageSerializer(stage, data=request.data, partial=True)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data, status=200)
        return Response(serializer.errors, status=400)

    def delete(self, request, pk):
        stage = object_check(ProjectStage, pk)
        if stage is None:
            return Response({"error": _("ProjectStage not found")}, status=404)
        if not can_delete_stage(request.user, stage):
            return _denied()
        try:
            stage.delete()
            return Response(status=status.HTTP_204_NO_CONTENT)
        except Exception as e:
            return Response({"error": str(e)}, status=400)


# Task Views
class TaskGetCreateAPIView(APIView):
    permission_classes = [IsAuthenticated]
    filter_backends = [DjangoFilterBackend]
    filterset_class = TaskAllFilter
    queryset = Task.objects.none()  # For drf-yasg schema generation

    def get_queryset(self, request=None, project_id=None):
        # Handle schema generation for DRF-YASG
        if getattr(self, "swagger_fake_view", False) or request is None:
            return Task.objects.none()
        queryset = visible_tasks(request.user)
        if project_id:
            queryset = queryset.filter(project_id=project_id)
        return queryset

    def get(self, request, pk=None, project_id=None):
        if pk:
            task = visible_tasks(request.user).filter(pk=pk).first()
            if task is None:
                return Response({"error": _("Task not found")}, status=404)
            serializer = TaskSerializer(task)
            return Response(serializer.data, status=200)

        tasks = self.get_queryset(request, project_id)
        filterset = self.filterset_class(request.GET, queryset=tasks)

        # groupby section
        field_name = request.GET.get("groupby_field", None)
        if field_name:
            url = request.build_absolute_uri()
            return groupby_queryset(request, url, field_name, filterset.qs)

        return _paginate(request, filterset.qs, TaskSerializer)

    def post(self, request, project_id=None, **kwargs):
        data = request.data.copy()
        if project_id and not data.get("project_id"):
            data["project_id"] = project_id
        project = Project.objects.filter(pk=data.get("project_id")).first()
        if project is None and data.get("stage_id"):
            stage = ProjectStage.objects.filter(pk=data.get("stage_id")).first()
            project = stage.project if stage else None
            if project is not None and not data.get("project_id"):
                data["project_id"] = project.id
        if not can_add_task(request.user, project):
            return _denied()
        serializer = TaskSerializer(data=data)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class TaskGetUpdateDeleteAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, pk):
        task = visible_tasks(request.user).filter(pk=pk).first()
        if task is None:
            return Response({"error": _("Task not found")}, status=404)
        serializer = TaskSerializer(task)
        return Response(serializer.data, status=200)

    def put(self, request, pk):
        task = object_check(Task, pk)
        if task is None:
            return Response({"error": _("Task not found")}, status=404)
        if not can_change_task(request.user, task):
            return _denied()
        serializer = TaskSerializer(task, data=request.data, partial=True)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data, status=200)
        return Response(serializer.errors, status=400)

    def delete(self, request, pk):
        task = object_check(Task, pk)
        if task is None:
            return Response({"error": _("Task not found")}, status=404)
        if not can_delete_task(request.user, task):
            return _denied()
        try:
            task.delete()
            return Response(status=status.HTTP_204_NO_CONTENT)
        except Exception as e:
            return Response({"error": str(e)}, status=400)


# TimeSheet Views
class TimeSheetGetCreateAPIView(APIView):
    permission_classes = [IsAuthenticated]
    filter_backends = [DjangoFilterBackend]
    filterset_class = TimeSheetFilter
    queryset = TimeSheet.objects.none()  # For drf-yasg schema generation

    def get_queryset(self, request=None, project_id=None, task_id=None):
        # Handle schema generation for DRF-YASG
        if getattr(self, "swagger_fake_view", False) or request is None:
            return TimeSheet.objects.none()
        queryset = visible_timesheets(request.user)
        if project_id:
            queryset = queryset.filter(project_id=project_id)
        if task_id:
            queryset = queryset.filter(task_id=task_id)
        return queryset

    def get(self, request, pk=None, project_id=None, task_id=None):
        if pk:
            timesheet = visible_timesheets(request.user).filter(pk=pk).first()
            if timesheet is None:
                return Response({"error": _("TimeSheet not found")}, status=404)
            serializer = TimeSheetSerializer(timesheet)
            return Response(serializer.data, status=200)

        timesheets = self.get_queryset(request, project_id, task_id)
        filterset = self.filterset_class(request.GET, queryset=timesheets)

        # groupby section
        field_name = request.GET.get("groupby_field", None)
        if field_name:
            url = request.build_absolute_uri()
            return groupby_queryset(request, url, field_name, filterset.qs)

        return _paginate(request, filterset.qs, TimeSheetSerializer)

    @permission_required("project.add_timesheet")
    def post(self, request, project_id=None, task_id=None, **kwargs):
        data = request.data.copy()
        if (
            project_id
            and not data.get("project_id_write")
            and not data.get("project_id")
        ):
            data["project_id_write"] = project_id
        if task_id and not data.get("task_id_write") and not data.get("task_id"):
            data["task_id_write"] = task_id
        if (
            task_id
            and not data.get("project_id_write")
            and not data.get("project_id")
        ):
            task = Task.objects.filter(pk=task_id).first()
            if task is not None and task.project_id:
                data["project_id_write"] = task.project_id
        serializer = TimeSheetSerializer(data=data)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class TimeSheetGetUpdateDeleteAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, pk):
        timesheet = visible_timesheets(request.user).filter(pk=pk).first()
        if timesheet is None:
            return Response({"error": _("TimeSheet not found")}, status=404)
        serializer = TimeSheetSerializer(timesheet)
        return Response(serializer.data, status=200)

    def put(self, request, pk):
        timesheet = object_check(TimeSheet, pk)
        if timesheet is None:
            return Response({"error": _("TimeSheet not found")}, status=404)
        if not can_change_timesheet(request, timesheet):
            return _denied()
        serializer = TimeSheetSerializer(timesheet, data=request.data, partial=True)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data, status=200)
        return Response(serializer.errors, status=400)

    def delete(self, request, pk):
        timesheet = object_check(TimeSheet, pk)
        if timesheet is None:
            return Response({"error": _("TimeSheet not found")}, status=404)
        if not can_delete_timesheet(request, timesheet):
            return _denied()
        try:
            timesheet.delete()
            return Response(status=status.HTTP_204_NO_CONTENT)
        except Exception as e:
            return Response({"error": str(e)}, status=400)
