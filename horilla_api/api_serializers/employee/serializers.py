from rest_framework import serializers

from base.models import Department, EmployeeType, JobPosition
from employee.models import (
    Actiontype,
    DisciplinaryAction,
    Employee,
    EmployeeBankDetails,
    EmployeeWorkInformation,
    Policy,
)
from horilla_documents.models import Document, DocumentRequest

from ...api_methods.employee.methods import get_next_badge_id


class ActiontypeSerializer(serializers.ModelSerializer):
    class Meta:
        model = Actiontype
        fields = ["id", "title", "action_type"]


class EmployeeListSerializer(serializers.ModelSerializer):
    """
    Directory row. Matches the columns on the web employee table.

    Personal email stays, as it already did. Phone is included only for a
    caller who holds ``employee.view_employee``, the same gate the web table
    uses for the phone column. Salary, address and bank details stay off this
    payload; the work-info and bank ids are pointers, not the records.
    """

    job_position_name = serializers.CharField(
        source="employee_work_info.job_position_id.job_position", read_only=True
    )
    department_name = serializers.CharField(
        source="employee_work_info.department_id.department", read_only=True
    )
    shift_name = serializers.CharField(
        source="employee_work_info.shift_id.employee_shift", read_only=True
    )
    work_type_name = serializers.CharField(
        source="employee_work_info.work_type_id.work_type", read_only=True
    )
    job_role_name = serializers.CharField(
        source="employee_work_info.job_role_id.job_role", read_only=True
    )
    reporting_manager = serializers.CharField(
        source="employee_work_info.reporting_manager_id", read_only=True
    )
    company_name = serializers.CharField(
        source="employee_work_info.company_id.company", read_only=True
    )
    work_email = serializers.CharField(
        source="employee_work_info.email", read_only=True
    )
    date_joining = serializers.DateField(
        source="employee_work_info.date_joining", read_only=True
    )
    employee_work_info_id = serializers.CharField(
        source="employee_work_info.id", read_only=True
    )
    employee_bank_details_id = serializers.CharField(
        source="employee_bank_details.id", read_only=True
    )

    class Meta:
        model = Employee
        fields = [
            "id",
            "employee_first_name",
            "employee_last_name",
            "email",
            "phone",
            "badge_id",
            "employee_profile",
            "job_position_name",
            "department_name",
            "shift_name",
            "work_type_name",
            "job_role_name",
            "reporting_manager",
            "company_name",
            "work_email",
            "date_joining",
            "employee_work_info_id",
            "employee_bank_details_id",
        ]

    def to_representation(self, instance):
        data = super().to_representation(instance)
        request = self.context.get("request")
        user = getattr(request, "user", None)
        if not user or not user.has_perm("employee.view_employee"):
            data.pop("phone", None)
        return data


class EmployeeSerializer(serializers.ModelSerializer):
    department_name = serializers.CharField(
        source="employee_work_info.department_id.department", read_only=True
    )
    department_id = serializers.CharField(
        source="employee_work_info.department_id.id", read_only=True
    )
    job_position_name = serializers.CharField(
        source="employee_work_info.job_position_id.job_position", read_only=True
    )
    job_position_id = serializers.CharField(
        source="employee_work_info.job_position_id.id", read_only=True
    )
    employee_work_info_id = serializers.CharField(
        source="employee_work_info.id", read_only=True
    )
    employee_bank_details_id = serializers.CharField(
        source="employee_bank_details.id", read_only=True
    )

    class Meta:
        model = Employee
        fields = "__all__"
        read_only_fields = ("employee_user_id",)

    def create(self, validated_data):
        validated_data["badge_id"] = get_next_badge_id()
        return super().create(validated_data)


class EmployeeSelfSerializer(serializers.ModelSerializer):
    """
    The fields a person may change on their own record.

    ``EmployeeSerializer`` is ``fields = "__all__"``, which is right for an HR
    user editing anyone and wrong for everyone else: routed through it, an
    employee updating their own profile could also set ``is_active``,
    ``badge_id`` or ``additional_info``, and rename themselves.

    This is an allowlist rather than an exclude list on purpose -- a field
    added to Employee later is then non-editable by default, which is the
    direction an accident should fail in.

    Deliberately absent, and HR-owned: ``email`` (unique, and what
    notifications key off), ``employee_first_name``/``employee_last_name``
    (identity), ``badge_id``, ``is_active``, ``additional_info``, and the
    onboarding provenance flags.
    """

    class Meta:
        model = Employee
        fields = (
            "employee_profile",
            "phone",
            "address",
            "country",
            "state",
            "city",
            "zip",
            "dob",
            "gender",
            "qualification",
            "experience",
            "marital_status",
            "children",
            "emergency_contact",
            "emergency_contact_name",
            "emergency_contact_relation",
        )


class EmployeeWorkInformationSerializer(serializers.ModelSerializer):
    job_position_name = serializers.CharField(
        source="job_position_id.job_position", read_only=True
    )
    department_name = serializers.CharField(
        source="department_id.department", read_only=True
    )
    shift_name = serializers.CharField(source="shift_id.employee_shift", read_only=True)
    employee_type_name = serializers.CharField(
        source="employee_type_id.employee_type", read_only=True
    )
    reporting_manager_first_name = serializers.CharField(
        source="reporting_manager_id.employee_first_name", read_only=True
    )
    reporting_manager_last_name = serializers.CharField(
        source="reporting_manager_id.employee_last_name", read_only=True
    )
    work_type_name = serializers.CharField(
        source="work_type_id.work_type", read_only=True
    )
    company_name = serializers.CharField(source="company_id.company", read_only=True)
    tags = serializers.SerializerMethodField()

    def get_tags(self, obj):
        return [
            {"id": tag.id, "title": tag.title, "color": tag.color}
            for tag in obj.tags.all()
        ]

    class Meta:
        model = EmployeeWorkInformation
        fields = "__all__"


class EmployeeBankDetailsSerializer(serializers.ModelSerializer):
    class Meta:
        model = EmployeeBankDetails
        fields = "__all__"


class EmployeeTypeSerializer(serializers.ModelSerializer):
    class Meta:
        model = EmployeeType
        fields = "__all__"


class EmployeeBulkUpdateSerializer(serializers.ModelSerializer):
    class Meta:
        model = Employee
        # fields = [
        #     'employee_last_name',
        #     'address',
        #     'country',
        #     'state',
        #     'city',
        #     'zip',
        #     'dob',
        #     'gender',
        #     'qualification',
        #     'experience',
        #     'marital_status',
        #     'children',
        # ]
        fields = [
            "employee_last_name",
        ]


class DisciplinaryActionSerializer(serializers.ModelSerializer):
    class Meta:
        model = DisciplinaryAction
        fields = "__all__"


class PolicySerializer(serializers.ModelSerializer):
    class Meta:
        model = Policy
        fields = "__all__"


class DocumentRequestSerializer(serializers.ModelSerializer):
    class Meta:
        model = DocumentRequest
        fields = "__all__"


class DocumentSerializer(serializers.ModelSerializer):
    class Meta:
        model = Document
        fields = "__all__"


class EmployeeSelectorSerializer(serializers.ModelSerializer):
    class Meta:
        model = Employee
        fields = [
            "id",
            "employee_first_name",
            "employee_last_name",
            "badge_id",
            "employee_profile",
        ]
