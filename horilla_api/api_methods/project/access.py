"""Who may see or change a project record.

The classic lists and decorators are the source of these rules. A caller with
the Django codename keeps that access. A manager or member is included where
the matching screen already lets them in.
"""

from django.db.models import Q

from employee.models import Employee
from project.methods import time_sheet_delete_permissions, time_sheet_update_permissions
from project.models import Project, ProjectStage, Task, TimeSheet


def employee_of(user):
    try:
        return user.employee_get
    except Exception:
        return None


def visible_projects(user):
    queryset = Project.objects.all().order_by("-id")
    if user.has_perm("project.view_project"):
        return queryset
    employee = employee_of(user)
    if employee is None:
        return queryset.none()
    return queryset.filter(
        Q(managers=employee)
        | Q(task__task_members=employee)
        | Q(task__task_managers=employee)
    ).distinct()


def visible_tasks(user):
    queryset = Task.objects.all().order_by("-id")
    if user.has_perm("project.view_task"):
        return queryset
    employee = employee_of(user)
    if employee is None:
        return queryset.none()
    subordinate_ids = Employee.objects.filter(
        employee_work_info__reporting_manager_id=employee
    ).values_list("id", flat=True)
    return queryset.filter(
        Q(task_members=employee)
        | Q(task_managers=employee)
        | Q(task_members__in=subordinate_ids)
        | Q(task_managers__in=subordinate_ids)
        | Q(project__managers=employee)
        | Q(project__managers__in=subordinate_ids)
    ).distinct()


def visible_stages(user):
    return ProjectStage.objects.filter(project__in=visible_projects(user)).order_by(
        "sequence", "id"
    )


def visible_timesheets(user):
    """Match TimeSheetList: permission holders see every row, everyone else
    sees their own plus rows on projects or tasks they manage."""
    queryset = TimeSheet.objects.all().order_by("-id")
    if user.has_perm("project.view_timesheet"):
        return queryset
    employee = employee_of(user)
    if employee is None:
        return queryset.none()
    return queryset.filter(
        Q(task_id__task_managers=employee)
        | Q(project_id__managers=employee)
        | Q(employee_id=employee)
    ).distinct()


def _on_project(user, project):
    employee = employee_of(user)
    if employee is None or project is None:
        return False
    if project.managers.filter(pk=employee.pk).exists():
        return True
    tasks = project.task_set.all()
    return tasks.filter(task_managers=employee).exists() or tasks.filter(
        task_members=employee
    ).exists()


def can_change_project(user, project):
    return user.has_perm("project.change_project") or _on_project(user, project)


def can_archive_or_delete_project(user, project):
    if (
        user.is_superuser
        or user.has_perm("project.delete_project")
        or user.has_perm("project.change_project")
    ):
        return True
    employee = employee_of(user)
    return employee is not None and project.managers.filter(pk=employee.pk).exists()


def can_add_stage(user, project):
    if user.is_superuser or user.has_perm("project.add_projectstage"):
        return True
    employee = employee_of(user)
    return employee is not None and project.managers.filter(pk=employee.pk).exists()


def can_change_stage(user, stage):
    if user.has_perm("project.change_projectstage") or user.has_perm(
        "project.change_project"
    ):
        return True
    return _on_project(user, stage.project)


def can_delete_stage(user, stage):
    if user.is_superuser or user.has_perm("project.delete_projectstage"):
        return True
    employee = employee_of(user)
    project = stage.project
    return employee is not None and project.managers.filter(pk=employee.pk).exists()


def can_add_task(user, project):
    if user.is_superuser or user.has_perm("project.add_task"):
        return True
    if project is None:
        return False
    employee = employee_of(user)
    return employee is not None and project.managers.filter(pk=employee.pk).exists()


def can_change_task(user, task):
    if user.has_perm("project.change_task") or user.has_perm("project.change_project"):
        return True
    employee = employee_of(user)
    if employee is None:
        return False
    if task.task_managers.filter(pk=employee.pk).exists():
        return True
    if task.task_members.filter(pk=employee.pk).exists():
        return True
    project = task.project
    return project is not None and project.managers.filter(pk=employee.pk).exists()


def can_delete_task(user, task):
    if user.is_superuser or user.has_perm("project.delete_task"):
        return True
    employee = employee_of(user)
    if employee is None:
        return False
    if task.task_managers.filter(pk=employee.pk).exists():
        return True
    project = task.project
    return project is not None and project.managers.filter(pk=employee.pk).exists()


def can_change_timesheet(request, timesheet):
    return time_sheet_update_permissions(request, timesheet.id)


def can_delete_timesheet(request, timesheet):
    if timesheet is None:
        return False
    if timesheet.task_id_id:
        return time_sheet_delete_permissions(request, timesheet.id)
    if request.user.has_perm("project.delete_timesheet"):
        return True
    employee = employee_of(request.user)
    return employee is not None and timesheet.employee_id_id == employee.id


def notify_project_status(request, project):
    """Same notice the classic status action sends to managers and members."""
    import logging

    from django.urls import reverse
    from django.utils.translation import gettext_noop

    logger = logging.getLogger(__name__)
    sender = employee_of(request.user)
    if sender is None:
        return
    try:
        from notifications.signals import notify
    except Exception:
        logger.exception("project status notify unavailable")
        return
    employees = project.managers.all()
    for task in project.task_set.all():
        employees = employees | task.task_managers.all() | task.task_members.all()
    for employee in employees.distinct():
        recipient = getattr(employee, "employee_user_id", None)
        if recipient is None:
            continue
        try:
            notify.send(
                sender,
                recipient=recipient,
                verb=gettext_noop(
                    "The status of the project '%(project)s' has been changed to %(get_status_display)s."
                ),
                verb_params={
                    "project": str(project),
                    "get_status_display": str(project.get_status_display()),
                },
                redirect=reverse("task-view", kwargs={"project_id": project.id}),
            )
        except Exception:
            logger.exception("project status notify failed")
