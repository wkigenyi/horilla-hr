"""
horilla_api/api_urls/project/urls.py
"""

from django.urls import path

from horilla_api.api_views.dashboard.views import ProjectDashboardWidgetAPIView
from horilla_api.api_views.project.actions import (
    ProjectBulkArchiveAPIView,
    ProjectBulkDeleteAPIView,
    ProjectExportAPIView,
    ProjectImportAPIView,
    ProjectImportTemplateAPIView,
    ProjectMembersAPIView,
    StageReorderAPIView,
    TaskBulkArchiveAPIView,
    TaskBulkDeleteAPIView,
    TaskReorderAPIView,
    TimeSheetBulkDeleteAPIView,
)
from horilla_api.api_views.project.views import *

urlpatterns = [
    path(
        "dashboard/<slug:widget>/",
        ProjectDashboardWidgetAPIView.as_view(),
        name="api-project-dashboard-widget",
    ),
    # Project URLs. Fixed paths come before the id path.
    path("project/", ProjectGetCreateAPIView.as_view()),
    path("project/bulk-archive/", ProjectBulkArchiveAPIView.as_view()),
    path("project/bulk-delete/", ProjectBulkDeleteAPIView.as_view()),
    path("project/import/template/", ProjectImportTemplateAPIView.as_view()),
    path("project/import/", ProjectImportAPIView.as_view()),
    path("project/export/", ProjectExportAPIView.as_view()),
    path("project/<int:pk>/", ProjectGetUpdateDeleteAPIView.as_view()),
    path("project/<int:project_id>/members/", ProjectMembersAPIView.as_view()),
    path("project/<int:project_id>/stage/reorder/", StageReorderAPIView.as_view()),
    path("project/<int:project_id>/task/reorder/", TaskReorderAPIView.as_view()),
    # Project Stage URLs
    path("project-stage/", ProjectStageGetCreateAPIView.as_view()),
    path("project-stage/<int:pk>/", ProjectStageGetUpdateDeleteAPIView.as_view()),
    path("project/<int:project_id>/stage/", ProjectStageGetCreateAPIView.as_view()),
    # Task URLs
    path("task/", TaskGetCreateAPIView.as_view()),
    path("task/bulk-archive/", TaskBulkArchiveAPIView.as_view()),
    path("task/bulk-delete/", TaskBulkDeleteAPIView.as_view()),
    path("task/<int:pk>/", TaskGetUpdateDeleteAPIView.as_view()),
    path("project/<int:project_id>/task/", TaskGetCreateAPIView.as_view()),
    # TimeSheet URLs
    path("timesheet/", TimeSheetGetCreateAPIView.as_view()),
    path("timesheet/bulk-delete/", TimeSheetBulkDeleteAPIView.as_view()),
    path("timesheet/<int:pk>/", TimeSheetGetUpdateDeleteAPIView.as_view()),
    path("project/<int:project_id>/timesheet/", TimeSheetGetCreateAPIView.as_view()),
    path("task/<int:task_id>/timesheet/", TimeSheetGetCreateAPIView.as_view()),
]
