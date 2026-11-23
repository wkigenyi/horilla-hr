"""
models.py

This module is used to register models for project app

"""

import datetime
from datetime import date

from django.apps import apps
from django.core.exceptions import ValidationError
from django.db import models
from django.urls import reverse, reverse_lazy
from django.utils import timezone
from django.utils.formats import localize
from django.utils.html import format_html
from django.utils.translation import gettext_lazy as _

from attendance.methods.utils import validate_time_format
from base.horilla_company_manager import HorillaCompanyManager
from base.models import Company
from employee.methods.duration_methods import format_time, strtime_seconds
from employee.models import Employee
from horilla import horilla_middlewares
from horilla.horilla_middlewares import _thread_locals
from horilla.models import HorillaModel, upload_path
from horilla_views.cbv_methods import render_template

# Create your models here.


def validate_time_format(value):
    """
    this method is used to validate the format of duration like fields.
    """
    if len(value) > 5:
        raise ValidationError(_("Invalid format, it should be HH:MM format"))
    try:
        hour, minute = value.split(":")

        if len(hour) < 2 or len(minute) < 2:
            raise ValidationError(_("Invalid format, it should be HH:MM format"))

        minute = int(minute)
        if len(hour) > 2 or minute not in range(60):
            raise ValidationError(_("Invalid time"))
    except ValueError as error:
        raise ValidationError(_("Invalid format")) from error


class Project(HorillaModel):
    PROJECT_STATUS = [
        ("new", _("New")),
        ("in_progress", _("In Progress")),
        ("completed", _("Completed")),
        ("on_hold", _("On Hold")),
        ("cancelled", _("Cancelled")),
        ("expired", _("Expired")),
    ]
    title = models.CharField(max_length=200, verbose_name=_("Name"))
    managers = models.ManyToManyField(
        Employee,
        blank=True,
        related_name="project_managers",
        verbose_name=_("Project Managers"),
    )
    status = models.CharField(
        choices=PROJECT_STATUS, max_length=250, default="new", verbose_name=_("Status")
    )
    start_date = models.DateField(verbose_name=_("Start Date"))
    end_date = models.DateField(null=True, blank=True, verbose_name=_("End Date"))
    document = models.FileField(
        upload_to=upload_path, blank=True, null=True, verbose_name=_("Project File")
    )
    description = models.TextField(verbose_name=_("Description"))
    company_id = models.ForeignKey(
        Company, null=True, editable=False, on_delete=models.PROTECT
    )
    objects = HorillaCompanyManager("company_id")

    def get_company_name(self):
        """
        Company column of the list view; "All Companies" when none is assigned.
        """
        return self.company_id.company if self.company_id else _("All Companies")

    def get_description(self, length=50):
        """
        Returns a truncated version of the description attribute.

        Parameters:
        length (int): The maximum length of the returned description.
        """
        return (
            self.description
            if len(self.description) <= length
            else self.description[:length] + "..."
        )

    def get_managers(self):
        """
        managers column
        """
        employees = self.managers.all()
        if employees:
            employee_names_string = ", ".join(
                [str(employee.get_full_name()) for employee in employees]
            )
            return employee_names_string

    def get_avatar(self):
        """
        Method will retun the api to the avatar or path to the profile image
        """
        url = f"https://ui-avatars.com/api/?name={self.title}&background=random"
        return url

    def get_document_html(self):
        if self.document:
            document_url = self.document.url
            return format_html(
                '<a href="{0}" style="text-decoration: none" rel="noopener noreferrer" class="oh-btn oh-btn--light" target="_blank" onclick="event.stopPropagation();">'
                '<span class="oh-file-icon oh-file-icon--pdf"></span>'
                "&nbsp View"
                "</a>",
                document_url,
            )

    def redirect(self):
        """
        This method generates an onclick URL for task viewing.
        """
        request = getattr(_thread_locals, "request", None)
        employee = request.user.employee_get
        url = reverse_lazy("task-view", kwargs={"project_id": self.pk})

        if (
            employee in self.managers.all()
            or any(employee in task.task_managers.all() for task in self.task_set.all())
            or any(employee in task.task_members.all() for task in self.task_set.all())
            or request.user.has_perm("project.view_project")
        ):
            return f"onclick=\"window.location.href='{url}?view=card'\""
        return ""

    def get_detail_url(self):
        """
        This method to get detail  url
        """
        url = reverse_lazy("project-detailed-view", kwargs={"pk": self.pk})
        return url

    def get_update_url(self):
        """
        This method to get update url
        """
        url = reverse_lazy("update-project", kwargs={"pk": self.pk})
        return url

    def get_archive_url(self):
        """
        This method to get archive url
        """
        url = reverse_lazy("project-archive", kwargs={"project_id": self.pk})
        return url

    def get_task_badge_html(self):
        task_count = self.task_set.count()
        title = self.title
        return format_html(
            '<div style="display: flex; align-items: center;">'
            '    <div class="oh-tabs__input-badge-container">'
            '        <span class="oh-badge oh-badge--secondary oh-badge--small oh-badge--round mr-1" title="{1} Tasks">'
            "            {1}"
            "        </span>"
            "    </div>"
            "    <div>{0}</div>"
            "</div>",
            title,
            task_count,
        )

    def get_card_view_subtitle(self):

        col = format_html(
            """
                <div class="my-2">{status_label} : <span class="font-semibold">{status}</span></div>
                <div class="mb-2">{start_label} : <span class="dateformat_changer font-semibold"> {start} </span></div>
                <div>{end_label} : <span class="dateformat_changer font-semibold"> {end} </span></div>
            """,
            status_label=_("Status"),
            start_label=_("Start date"),
            end_label=_("End date"),
            status=self.get_status_display(),
            start=localize(self.start_date),
            end=localize(self.end_date),
        )
        return col

    def get_delete_url(self):
        """
        This method to get delete url
        """
        url = reverse_lazy("delete-project", kwargs={"project_id": self.pk})
        message = _("Are you sure you want to delete this project?")
        return f"'{url}'" + "," + f"'{message}'"

    def actions(self):
        """
        This method for get custom column for action.
        """

        return render_template(
            path="cbv/projects/actions.html",
            context={"instance": self},
        )

    def archive_status(self):
        """
        archive status
        """
        if self.is_active:
            return _("Archive")
        else:
            return _("Un-Archive")

    def clean(self) -> None:
        # validating end date
        if self.end_date is not None:
            if self.end_date < self.start_date:
                raise ValidationError({"document": "End date is less than start date"})
            if self.end_date < date.today():
                self.status = "expired"

    def save(self, *args, **kwargs):
        is_new, request = self.pk is None, getattr(
            horilla_middlewares._thread_locals, "request", None
        )
        if (
            is_new
            and request is not None
            and (cid := request.session.get("selected_company"))
            and cid != "all"
        ):
            self.company_id = Company.find(cid)
        super().save(*args, **kwargs)
        if is_new:
            ProjectStage.objects.create(
                title="Todo", project=self, sequence=1, is_end_stage=False
            )

    def __str__(self):
        return self.title

    class Meta:
        """
        Meta class to add the additional info
        """

        verbose_name = _("Project")
        verbose_name_plural = _("Projects")
        ordering = ["-id"]
        unique_together = ["title", "company_id"]


class ProjectStage(HorillaModel):
    """
    ProjectStage model
    """

    title = models.CharField(max_length=200, verbose_name=_("Title"))
    project = models.ForeignKey(
        Project,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="project_stages",
        verbose_name=_("Project"),
    )
    sequence = models.IntegerField(null=True, blank=True, editable=False)
    is_end_stage = models.BooleanField(default=False, verbose_name=_("End stage"))
    objects = HorillaCompanyManager("project__company_id")

    def __str__(self) -> str:
        return f"{self.title}"

    def clean(self) -> None:
        if self.is_end_stage:
            project = self.project
            existing_end_stage = project.project_stages.filter(
                is_end_stage=True
            ).exclude(id=self.id)

            if existing_end_stage:
                end_stage = project.project_stages.filter(is_end_stage=True).first()
                raise ValidationError(
                    _(f"Already exist an end stage - {end_stage.title}.")
                )

    def save(self, *args, **kwargs):
        if self.sequence is None:
            last_stage = (
                ProjectStage.objects.filter(project=self.project)
                .order_by("sequence")
                .last()
            )
            if last_stage:
                self.sequence = last_stage.sequence + 1
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        project_stages_after = ProjectStage.objects.filter(
            project=self.project, sequence__gt=self.sequence
        )

        # Decrement the sequence of the following stages
        for stage in project_stages_after:
            stage.sequence -= 1
            stage.save()

        super().delete(*args, **kwargs)

    class Meta:
        """
        Meta class to add the additional info
        """

        unique_together = ["project", "title"]
        verbose_name = _("Project Stage")
        verbose_name_plural = _("Project Stages")


class Task(HorillaModel):
    """
    Task model
    """

    TASK_STATUS = [
        ("to_do", _("To Do")),
        ("in_progress", _("In Progress")),
        ("completed", _("Completed")),
        ("expired", _("Expired")),
    ]
    title = models.CharField(max_length=200, verbose_name=_("Title"))
    project = models.ForeignKey(
        Project, on_delete=models.CASCADE, null=True, verbose_name=_("Project")
    )
    stage = models.ForeignKey(
        ProjectStage,
        on_delete=models.CASCADE,
        null=True,
        related_name="tasks",
        verbose_name=_("Project Stage"),
    )
    task_managers = models.ManyToManyField(
        Employee,
        blank=True,
        verbose_name=_("Task Managers"),
    )
    task_members = models.ManyToManyField(
        Employee, blank=True, related_name="tasks", verbose_name=_("Task Members")
    )
    status = models.CharField(
        choices=TASK_STATUS, max_length=250, default="to_do", verbose_name=_("Status")
    )
    start_date = models.DateField(null=True, blank=True, verbose_name=_("Start Date"))
    end_date = models.DateField(null=True, blank=True, verbose_name=_("End Date"))
    allocated_hours = models.CharField(
        null=True,
        blank=True,
        default="00:00",
        max_length=10,
        validators=[validate_time_format],
        verbose_name=_("Allocated Hours"),
    )
    document = models.FileField(
        upload_to=upload_path, blank=True, null=True, verbose_name=_("Task File")
    )
    description = models.TextField(verbose_name=_("Description"))
    sequence = models.IntegerField(default=0)
    # Piece-rate payroll: payable tasks use TaskPayAllocation rows (per
    # participant). completed_at is when status became completed (end_date is
    # the due date). payroll_adjustment links a task once it has been included
    # in a draft/confirmed Pay Adjustment so it is not posted twice.
    is_payable = models.BooleanField(
        default=False,
        verbose_name=_("Payable"),
        help_text=_("Include this task in payroll when it is completed."),
    )
    completed_at = models.DateField(
        null=True,
        blank=True,
        editable=False,
        verbose_name=_("Completed On"),
    )
    payroll_adjustment = models.ForeignKey(
        "payroll.PayAdjustment",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        editable=False,
        related_name="tasks",
        verbose_name=_("Payroll Adjustment"),
    )
    objects = HorillaCompanyManager("project__company_id")

    def sync_completed_at(self):
        """Stamp or clear completed_at from the current status.

        A date already on the task is kept, so a backdated completion
        entered by hand is not overwritten with today.
        """
        if self.status == "completed":
            if self.completed_at is None:
                self.completed_at = date.today()
        else:
            self.completed_at = None

    def save(self, *args, **kwargs):
        self.sync_completed_at()
        super().save(*args, **kwargs)

    def clean(self) -> None:
        if (
            self.end_date is not None
            and self.project is not None
            and self.project.end_date is not None
        ):
            if (
                self.project.end_date < self.end_date
                or self.project.start_date > self.end_date
            ):
                raise ValidationError(
                    {
                        "end_date": _(
                            "The task end date must be between the project's start and end dates."
                        )
                    }
                )
        # Status is never derived from the end date: tasks are entered
        # backdated, so a past end date says nothing about the work itself.
        # "Expired" is a status someone chooses.

    class Meta:
        """
        Meta class to add the additional info
        """

        unique_together = ["project", "title"]
        verbose_name = _("Task")
        verbose_name_plural = _("Tasks")
        ordering = ["-id"]

    def __str__(self):
        return f"{self.title}"

    def if_project(self):
        """
        Return project if have,otherwise return none
        """

        return self.project if self.project else "None"

    @property
    def is_overdue(self):
        """
        Past its end date and not completed -- checked against the date
        directly, since "expired" is a status someone chooses and is never
        set automatically.
        """
        return bool(
            self.end_date
            and self.status != "completed"
            and self.end_date < date.today()
        )

    @property
    def is_due_soon(self):
        """
        Due within the next 2 days and not already overdue/completed --
        used for the card view's due-date indicator.
        """
        if not self.end_date or self.is_overdue or self.status == "completed":
            return False
        return self.end_date <= date.today() + datetime.timedelta(days=2)

    @property
    def due_status_display(self):
        """
        Human-readable due-state label for the card ("Overdue by 3 days",
        "Due today", "Due in 2 days", ...), empty when there's nothing
        worth flagging (no end date, or already completed).
        """
        if not self.end_date or self.status == "completed":
            return ""
        days = (self.end_date - date.today()).days
        if days < 0:
            return (
                _("Overdue by 1 day")
                if days == -1
                else _("Overdue by %(days)d days") % {"days": -days}
            )
        if days == 0:
            return _("Due today")
        if days == 1:
            return _("Due tomorrow")
        return _("Due in %(days)d days") % {"days": days}

    def task_detail_view(self):
        """
        detail view of task
        """

        url = reverse("task-detail-view", kwargs={"pk": self.pk})
        return url

    def card_view_subtitle(self):
        """
        subtitle for card view
        """
        col = format_html(
            """
                <div class="my-2">{project_label} : <span class="font-semibold">{project}</span></div>
                <div class="mb-2">{stage_label} : <span class="font-semibold">{stage}</span></div>
                <div>{end_label} : <span class="dateformat_changer font-semibold">{end}</span></div>
            """,
            project_label=_("Project Name"),
            stage_label=_("Stage Name"),
            end_label=_("End date"),
            project=self.if_project(),
            stage=self.stage,
            end=localize(self.end_date),
        )
        return col

    def status_column(self):
        """
        to get status
        """
        return dict(self.TASK_STATUS).get(self.status)

    def get_managers(self):
        """
        return task managers
        """
        managers = self.task_managers.all()
        if managers:
            managers_name_string = ", ".join(
                [str(manager.get_full_name()) for manager in managers]
            )
            return managers_name_string
        else:
            return ""

    def get_members(self):
        """
        return task members
        """
        members = self.task_members.all()
        if members:
            members_name_string = ", ".join(
                [str(member.get_full_name()) for member in members]
            )
            return members_name_string
        else:
            return ""

    def actions(self):
        """
        This method for get custom column for action.
        """
        return render_template(
            path="cbv/tasks/task_actions.html",
            context={"instance": self},
        )

    @property
    def allocated_seconds(self):
        """
        allocated_hours (HH:MM) converted to seconds, 0 when unset/invalid.
        """
        if not self.allocated_hours:
            return 0
        try:
            return strtime_seconds(self.allocated_hours)
        except (ValueError, AttributeError):
            return 0

    @property
    def timesheet_spent_seconds(self):
        """
        Sum of time_spent across every timesheet logged against this task.
        """
        total = 0
        for time_spent in self.task_timesheet.values_list("time_spent", flat=True):
            if not time_spent:
                continue
            try:
                total += strtime_seconds(time_spent)
            except (ValueError, AttributeError):
                continue
        return total

    def timesheet_progress_col(self):
        """
        Progress bar comparing logged timesheet hours against allocated_hours,
        rendered full-width in the task detail view.
        """
        allocated = self.allocated_seconds
        spent = self.timesheet_spent_seconds
        if not allocated:
            return ""
        percent = min(100, round((spent / allocated) * 100))
        bar_color = (
            "var(--md-red, #ef4444)"
            if percent >= 100
            else "var(--primary-600, #e54f38)"
        )
        return format_html(
            """
            <div class="oh-timeoff-modal__stat">
                <span class="oh-timeoff-modal__stat-title">{label}</span>
                <span class="oh-timeoff-modal__stat-count">{spent} / {allocated} {hrs}</span>
            </div>
            <div style="background:#e5e7eb;border-radius:6px;height:10px;overflow:hidden;margin-top:6px;">
                <div style="width:{percent}%;background:{bar_color};height:100%;"></div>
            </div>
            """,
            label=_("Timesheet Progress"),
            spent=format_time(spent),
            allocated=format_time(allocated),
            hrs=_("hrs"),
            percent=percent,
            bar_color=bar_color,
        )

    def get_avatar(self):
        """
        Method will retun the api to the avatar or path to the profile image
        """
        url = f"https://ui-avatars.com/api/?name={self.title}&background=random"
        return url

    def document_col(self):
        """
        This method for get custom document coloumn .
        """

        return render_template(
            path="cbv/tasks/task_document.html",
            context={"instance": self},
        )

    def detail_view_actions(self):
        """
        This method for get detail view actions.
        """

        return render_template(
            path="cbv/tasks/task_detail_actions.html",
            context={"instance": self},
        )

    def get_update_url(self):
        """
        to get the update url
        """
        url = reverse("update-task-all", kwargs={"pk": self.pk})
        return url

    def archive_status(self):
        """
        archive status
        """
        if self.is_active:
            return "Archive"
        else:
            return "Un-Archive"

    def get_archive_url(self):
        """
        to get archive url
        """

        url = reverse("task-all-archive", kwargs={"task_id": self.pk})
        return url

    def get_delete_url(self):
        """
        to get delete url
        """

        url = reverse("delete-task", kwargs={"task_id": self.pk})
        url_with_params = f"{url}?task_all=true"
        message = _("Are you sure you want to delete this task?")
        return f"'{url_with_params}'" + "," + f"'{message}'"


class TaskPayAllocation(HorillaModel):
    """
    Per-participant amount for a payable task. The task total is the sum of
    these rows; payroll posts each employee's own amount with no split.
    """

    task = models.ForeignKey(
        Task,
        on_delete=models.CASCADE,
        related_name="pay_allocations",
        verbose_name=_("Task"),
    )
    employee = models.ForeignKey(
        Employee,
        on_delete=models.CASCADE,
        related_name="task_pay_allocations",
        verbose_name=_("Employee"),
    )
    amount = models.FloatField(verbose_name=_("Amount"))

    objects = HorillaCompanyManager("task__project__company_id")

    class Meta:
        unique_together = [("task", "employee")]
        verbose_name = _("Task Pay Allocation")
        verbose_name_plural = _("Task Pay Allocations")
        ordering = ["pk"]

    def __str__(self):
        return f"{self.task_id}:{self.employee_id}={self.amount}"

    def clean(self):
        errors = {}
        if self.amount is None or self.amount <= 0:
            errors["amount"] = _("Enter an amount greater than zero.")
        if self.task_id and self.employee_id:
            if not self.task.task_members.filter(pk=self.employee_id).exists():
                errors["employee"] = _(
                    "Pay amounts can only be set for task members."
                )
        if errors:
            raise ValidationError(errors)


class TimeSheet(HorillaModel):
    """
    TimeSheet model
    """

    TIME_SHEET_STATUS = [
        ("in_Progress", _("In Progress")),
        ("completed", _("Completed")),
    ]
    project_id = models.ForeignKey(
        Project,
        on_delete=models.CASCADE,
        null=True,
        related_name="project_timesheet",
        verbose_name=_("Project"),
    )
    task_id = models.ForeignKey(
        Task,
        on_delete=models.CASCADE,
        null=True,
        related_name="task_timesheet",
        verbose_name=_("Task"),
    )
    employee_id = models.ForeignKey(
        Employee,
        on_delete=models.CASCADE,
        verbose_name=_("Employee"),
    )
    date = models.DateField(default=timezone.now, verbose_name=_("Date"))
    time_spent = models.CharField(
        null=True,
        default="00:00",
        max_length=10,
        validators=[validate_time_format],
        verbose_name=_("Hours Spent"),
    )
    status = models.CharField(
        choices=TIME_SHEET_STATUS,
        max_length=250,
        default="in_Progress",
        verbose_name=_("Status"),
    )
    description = models.TextField(blank=True, null=True, verbose_name=_("Description"))
    objects = HorillaCompanyManager("project_id__company_id")

    def clean(self):
        if self.project_id is None:
            raise ValidationError({"project_id": "Project name is Required."})
        if self.description is None or self.description == "":
            raise ValidationError(
                {"description": "Please provide a description to your Time sheet"}
            )
        if self.employee_id:
            employee = self.employee_id
            if self.task_id:
                task = self.task_id
                if (
                    not employee in task.task_managers.all()
                    and not employee in task.task_members.all()
                    and not employee in task.project.managers.all()
                ):
                    raise ValidationError(_("Employee not included in this task"))
            elif self.project_id:
                project = self.project_id
                if (
                    not employee in project.managers.all()
                    and not any(
                        employee in task.task_managers.all()
                        for task in project.task_set.all()
                    )
                    and not any(
                        employee in task.task_members.all()
                        for task in project.task_set.all()
                    )
                ):
                    raise ValidationError(_("Employee not included in this project"))
            if self.date > datetime.datetime.today().date():
                raise ValidationError({"date": _("You cannot choose a future date.")})

    def __str__(self):
        return f"{self.employee_id} {self.project_id} {self.task_id} {self.date} {self.time_spent}"

    def status_column(self):
        return dict(self.TIME_SHEET_STATUS).get(self.status)

    def actions(self):
        """
        This method for get custom column for action.
        """

        return render_template(
            path="cbv/timesheet/actions.html",
            context={"instance": self},
        )

    def get_description_col(self):
        """
        This method for get custom column for action.
        """

        return render_template(
            path="cbv/timesheet/description_col.html",
            context={"instance": self},
        )

    def detail_actions(self):
        """
        This method for get custom column for action.
        """

        return render_template(
            path="cbv/timesheet/detail_actions.html",
            context={"instance": self},
        )

    def get_update_url(self):
        """
        This method to get update url
        """
        url = reverse_lazy("update-time-sheet", kwargs={"pk": self.pk})
        return url

    def get_delete_url(self):
        """
        This method to get delete url
        """
        url = reverse_lazy("delete-time-sheet", kwargs={"time_sheet_id": self.pk})
        message = _("Are you sure you want to delete this timesheet?")
        return f"'{url}'" + "," + f"'{message}'"

    def detail_view(self):
        """
        for detail view of page
        """
        url = reverse("time-sheet-detail-view", kwargs={"pk": self.pk})
        return url

    class Meta:
        verbose_name = _("Timesheet")
        verbose_name_plural = _("Timesheets")
