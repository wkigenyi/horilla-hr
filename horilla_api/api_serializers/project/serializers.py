"""
horilla_api/api_serializers/project/serializers.py
"""

from datetime import date, datetime

from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import models as dj_models
from django.utils.translation import gettext_lazy as _
from rest_framework import serializers

from base.models import Company
from employee.models import Employee
from project.models import Project, ProjectStage, Task, TimeSheet


def _validation_error(exc):
    if getattr(exc, "message_dict", None):
        raise serializers.ValidationError(
            {
                key: [str(item) for item in value]
                for key, value in exc.message_dict.items()
            }
        )
    raise serializers.ValidationError(
        {"detail": [str(message) for message in exc.messages]}
    )


def _save_model(model, validated_data, instance=None, m2m_names=()):
    """Assign fields, run Model.clean(), then save.

    Serializer.save() skips clean(), so the API was accepting dates and
    membership the classic forms reject.
    """
    relations = {
        name: validated_data.pop(name) for name in m2m_names if name in validated_data
    }
    if instance is None:
        instance = model(**validated_data)
    else:
        for name, value in validated_data.items():
            setattr(instance, name, value)
    # DateField(default=timezone.now) leaves a datetime on the instance until
    # save(). TimeSheet.clean() compares that value to a date.
    for field in instance._meta.fields:
        if isinstance(field, dj_models.DateTimeField) or not isinstance(
            field, dj_models.DateField
        ):
            continue
        value = getattr(instance, field.name)
        if isinstance(value, datetime):
            setattr(instance, field.name, value.date())
    try:
        instance.full_clean()
    except DjangoValidationError as exc:
        _validation_error(exc)
    instance.save()
    for name, value in relations.items():
        getattr(instance, name).set(value or [])
    return instance


class ProjectStageSerializer(serializers.ModelSerializer):
    project = serializers.SerializerMethodField()
    project_id = serializers.PrimaryKeyRelatedField(
        queryset=Project.objects.all(),
        source="project",
        write_only=True,
        required=False,
    )

    class Meta:
        model = ProjectStage
        fields = "__all__"

    def get_project(self, obj):
        if obj.project:
            return {
                "id": obj.project.id,
                "title": obj.project.title,
            }
        return None

    def create(self, validated_data):
        return _save_model(ProjectStage, validated_data)

    def update(self, instance, validated_data):
        return _save_model(ProjectStage, validated_data, instance)


class ProjectSerializer(serializers.ModelSerializer):
    managers = serializers.SerializerMethodField()
    managers_ids = serializers.PrimaryKeyRelatedField(
        queryset=Employee.objects.all(),
        many=True,
        source="managers",
        write_only=True,
        required=False,
    )
    company_id = serializers.SerializerMethodField()
    company_id_write = serializers.PrimaryKeyRelatedField(
        queryset=Company.objects.all(),
        source="company_id",
        write_only=True,
        required=False,
        allow_null=True,
        default=None,
    )
    project_stages = ProjectStageSerializer(many=True, read_only=True)
    task_count = serializers.SerializerMethodField()

    class Meta:
        model = Project
        fields = "__all__"
        extra_kwargs = {
            "managers": {"read_only": True},
        }

    def get_managers(self, obj):
        if obj.managers.exists():
            return [
                {
                    "id": emp.id,
                    "employee_first_name": emp.employee_first_name,
                    "employee_last_name": emp.employee_last_name,
                    "get_full_name": emp.get_full_name(),
                }
                for emp in obj.managers.all()
            ]
        return []

    def get_company_id(self, obj):
        if obj.company_id:
            return {
                "id": obj.company_id.id,
                "company": obj.company_id.company,
            }
        return None

    def get_task_count(self, obj):
        annotated = getattr(obj, "task_count", None)
        if annotated is not None:
            return annotated
        return obj.task_set.count()

    def create(self, validated_data):
        return _save_model(Project, validated_data, m2m_names=("managers",))

    def update(self, instance, validated_data):
        return _save_model(Project, validated_data, instance, m2m_names=("managers",))


class TaskSerializer(serializers.ModelSerializer):
    project = serializers.SerializerMethodField()
    project_id = serializers.PrimaryKeyRelatedField(
        queryset=Project.objects.all(),
        source="project",
        write_only=True,
        required=False,
    )
    stage = serializers.SerializerMethodField()
    stage_id = serializers.PrimaryKeyRelatedField(
        queryset=ProjectStage.objects.all(),
        source="stage",
        write_only=True,
        required=False,
    )
    task_managers = serializers.SerializerMethodField()
    task_managers_ids = serializers.PrimaryKeyRelatedField(
        queryset=Employee.objects.all(),
        many=True,
        source="task_managers",
        write_only=True,
        required=False,
    )
    task_members = serializers.SerializerMethodField()
    task_members_ids = serializers.PrimaryKeyRelatedField(
        queryset=Employee.objects.all(),
        many=True,
        source="task_members",
        write_only=True,
        required=False,
    )
    allocated_seconds = serializers.IntegerField(read_only=True)
    timesheet_spent_seconds = serializers.IntegerField(read_only=True)

    class Meta:
        model = Task
        fields = "__all__"
        extra_kwargs = {
            "task_managers": {"read_only": True},
            "task_members": {"read_only": True},
        }

    def get_project(self, obj):
        if obj.project:
            return {
                "id": obj.project.id,
                "title": obj.project.title,
            }
        return None

    def get_stage(self, obj):
        if obj.stage:
            return {
                "id": obj.stage.id,
                "title": obj.stage.title,
            }
        return None

    def get_task_managers(self, obj):
        if obj.task_managers.exists():
            return [
                {
                    "id": emp.id,
                    "employee_first_name": emp.employee_first_name,
                    "employee_last_name": emp.employee_last_name,
                    "get_full_name": emp.get_full_name(),
                }
                for emp in obj.task_managers.all()
            ]
        return []

    def get_task_members(self, obj):
        if obj.task_members.exists():
            return [
                {
                    "id": emp.id,
                    "employee_first_name": emp.employee_first_name,
                    "employee_last_name": emp.employee_last_name,
                    "get_full_name": emp.get_full_name(),
                }
                for emp in obj.task_members.all()
            ]
        return []

    def validate(self, attrs):
        project = attrs.get("project", getattr(self.instance, "project", None))
        stage = attrs.get("stage", getattr(self.instance, "stage", None))
        if (
            stage is not None
            and project is not None
            and stage.project_id != project.id
        ):
            raise serializers.ValidationError(
                {"stage_id": [_("Stage does not belong to this project.")]}
            )
        if self.instance is not None and self.instance.end_date:
            if self.instance.end_date < date.today():
                status = attrs.get("status", self.instance.status)
                next_stage = attrs.get("stage", self.instance.stage)
                stage_changed = (
                    next_stage is not None
                    and next_stage.id != self.instance.stage_id
                )
                if status != self.instance.status or stage_changed:
                    raise serializers.ValidationError(
                        {
                            "status": [
                                _("Cannot update status. Task has already expired.")
                            ]
                        }
                    )
        return attrs

    def create(self, validated_data):
        return _save_model(
            Task,
            validated_data,
            m2m_names=("task_managers", "task_members"),
        )

    def update(self, instance, validated_data):
        return _save_model(
            Task,
            validated_data,
            instance,
            m2m_names=("task_managers", "task_members"),
        )


class TimeSheetSerializer(serializers.ModelSerializer):
    project_id = serializers.SerializerMethodField()
    project_id_write = serializers.PrimaryKeyRelatedField(
        queryset=Project.objects.all(),
        source="project_id",
        write_only=True,
        required=False,
    )
    task_id = serializers.SerializerMethodField()
    task_id_write = serializers.PrimaryKeyRelatedField(
        queryset=Task.objects.all(), source="task_id", write_only=True, required=False
    )
    employee_id = serializers.SerializerMethodField()
    employee_id_write = serializers.PrimaryKeyRelatedField(
        queryset=Employee.objects.all(),
        source="employee_id",
        write_only=True,
        required=False,
    )

    class Meta:
        model = TimeSheet
        fields = "__all__"

    def get_project_id(self, obj):
        if obj.project_id:
            return {
                "id": obj.project_id.id,
                "title": obj.project_id.title,
            }
        return None

    def get_task_id(self, obj):
        if obj.task_id:
            return {
                "id": obj.task_id.id,
                "title": obj.task_id.title,
            }
        return None

    def get_employee_id(self, obj):
        if obj.employee_id:
            return {
                "id": obj.employee_id.id,
                "employee_first_name": obj.employee_id.employee_first_name,
                "employee_last_name": obj.employee_id.employee_last_name,
                "get_full_name": obj.employee_id.get_full_name(),
            }
        return None

    def create(self, validated_data):
        return _save_model(TimeSheet, validated_data)

    def update(self, instance, validated_data):
        return _save_model(TimeSheet, validated_data, instance)
