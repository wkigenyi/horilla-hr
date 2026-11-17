from rest_framework import serializers

from employee.models import Employee
from ohs.models import (
    OshCommitteeMeeting,
    OshCorrectiveAction,
    OshEvent,
    OshInvestigation,
    OshMedicalRecord,
    OshNotification,
    OshPolicy,
    OshPolicyAcknowledgement,
    OshPpeAssignment,
    OshSafetyCommittee,
    OshTrainingRecord,
    OshWorkplace,
)


def _employee_brief(employee):
    if not employee:
        return None
    return {
        "id": employee.id,
        "employee_first_name": employee.employee_first_name,
        "employee_last_name": employee.employee_last_name,
        "get_full_name": employee.get_full_name(),
    }


class OshWorkplaceSerializer(serializers.ModelSerializer):
    class Meta:
        model = OshWorkplace
        fields = "__all__"


class OshEventSerializer(serializers.ModelSerializer):
    employee_detail = serializers.SerializerMethodField(read_only=True)
    reported_by_detail = serializers.SerializerMethodField(read_only=True)
    workplace_name = serializers.CharField(source="workplace.name", read_only=True)
    event_type_display = serializers.CharField(
        source="get_event_type_display", read_only=True
    )
    status_display = serializers.CharField(source="get_status_display", read_only=True)

    class Meta:
        model = OshEvent
        fields = "__all__"

    def get_employee_detail(self, obj):
        return _employee_brief(obj.employee)

    def get_reported_by_detail(self, obj):
        return _employee_brief(obj.reported_by)


class OshNotificationSerializer(serializers.ModelSerializer):
    class Meta:
        model = OshNotification
        fields = "__all__"


class OshInvestigationSerializer(serializers.ModelSerializer):
    lead_detail = serializers.SerializerMethodField(read_only=True)

    class Meta:
        model = OshInvestigation
        fields = "__all__"

    def get_lead_detail(self, obj):
        return _employee_brief(obj.lead)


class OshCorrectiveActionSerializer(serializers.ModelSerializer):
    owner_detail = serializers.SerializerMethodField(read_only=True)

    class Meta:
        model = OshCorrectiveAction
        fields = "__all__"

    def get_owner_detail(self, obj):
        return _employee_brief(obj.owner)


class OshPolicySerializer(serializers.ModelSerializer):
    class Meta:
        model = OshPolicy
        fields = "__all__"


class OshPolicyAcknowledgementSerializer(serializers.ModelSerializer):
    employee_detail = serializers.SerializerMethodField(read_only=True)

    class Meta:
        model = OshPolicyAcknowledgement
        fields = "__all__"

    def get_employee_detail(self, obj):
        return _employee_brief(obj.employee)


class OshSafetyCommitteeSerializer(serializers.ModelSerializer):
    member_ids = serializers.PrimaryKeyRelatedField(
        many=True,
        queryset=Employee.objects.all(),
        source="members",
        required=False,
    )

    class Meta:
        model = OshSafetyCommittee
        fields = "__all__"


class OshCommitteeMeetingSerializer(serializers.ModelSerializer):
    class Meta:
        model = OshCommitteeMeeting
        fields = "__all__"


class OshMedicalRecordSerializer(serializers.ModelSerializer):
    employee_detail = serializers.SerializerMethodField(read_only=True)

    class Meta:
        model = OshMedicalRecord
        fields = "__all__"

    def get_employee_detail(self, obj):
        return _employee_brief(obj.employee)


class OshPpeAssignmentSerializer(serializers.ModelSerializer):
    employee_detail = serializers.SerializerMethodField(read_only=True)

    class Meta:
        model = OshPpeAssignment
        fields = "__all__"

    def get_employee_detail(self, obj):
        return _employee_brief(obj.employee)


class OshTrainingRecordSerializer(serializers.ModelSerializer):
    employee_detail = serializers.SerializerMethodField(read_only=True)

    class Meta:
        model = OshTrainingRecord
        fields = "__all__"

    def get_employee_detail(self, obj):
        return _employee_brief(obj.employee)
