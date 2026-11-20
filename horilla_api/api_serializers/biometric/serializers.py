"""Biometric devices for the Imara API.

Device credentials (machine passwords, API keys and secrets) are write-only:
the API accepts them but never sends them back. ``has_*`` flags tell a
client whether one is stored, so an edit form can say "leave blank to keep".
"""

import copy

from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import serializers

from biometric.models import BiometricDevices, BiometricEmployees

SECRET_FIELDS = ("zk_password", "bio_password", "api_key", "api_secret")


class BiometricDeviceSerializer(serializers.ModelSerializer):
    machine_type_label = serializers.CharField(
        source="get_machine_type_display", read_only=True
    )
    device_direction_label = serializers.CharField(
        source="get_device_direction_display", read_only=True
    )
    company_name = serializers.CharField(
        source="company_id.company", read_only=True, default=None
    )
    has_zk_password = serializers.SerializerMethodField()
    has_bio_password = serializers.SerializerMethodField()
    has_api_key = serializers.SerializerMethodField()
    has_api_secret = serializers.SerializerMethodField()
    people_count = serializers.SerializerMethodField()

    class Meta:
        model = BiometricDevices
        fields = (
            "id",
            "name",
            "machine_type",
            "machine_type_label",
            "machine_ip",
            "port",
            "zk_password",
            "has_zk_password",
            "bio_username",
            "bio_password",
            "has_bio_password",
            "anviz_request_id",
            "api_url",
            "api_key",
            "has_api_key",
            "api_secret",
            "has_api_secret",
            "device_direction",
            "device_direction_label",
            "is_live",
            "is_scheduler",
            "scheduler_duration",
            "last_fetch_date",
            "last_fetch_time",
            "company_id",
            "company_name",
            "is_active",
            "people_count",
        )
        read_only_fields = ("id", "is_live", "last_fetch_date", "last_fetch_time")
        extra_kwargs = {
            field: {"write_only": True, "required": False, "allow_blank": True}
            for field in SECRET_FIELDS
        }
        extra_kwargs["machine_type"] = {"required": True, "allow_null": False}

    def get_has_zk_password(self, obj):
        return bool(obj.zk_password)

    def get_has_bio_password(self, obj):
        return bool(obj.bio_password)

    def get_has_api_key(self, obj):
        return bool(obj.api_key)

    def get_has_api_secret(self, obj):
        return bool(obj.api_secret)

    def get_people_count(self, obj):
        annotated = getattr(obj, "people_total", None)
        if annotated is not None:
            return annotated
        return BiometricEmployees.objects.filter(device_id=obj).count()

    def validate(self, attrs):
        # A blank secret on an edit means "keep what is stored", so the client
        # never has to know (or resend) the current value.
        if self.instance is not None:
            for field in SECRET_FIELDS:
                if field in attrs and attrs[field] in ("", None):
                    attrs.pop(field)

        # The model's clean() holds the per-type rules (IP and port for ZKTeco,
        # a numeric ZKTeco password, API credentials for Anviz). Run it on a
        # copy so a failed edit leaves the stored instance untouched.
        candidate = (
            copy.copy(self.instance) if self.instance is not None else BiometricDevices()
        )
        for key, value in attrs.items():
            setattr(candidate, key, value)
        try:
            candidate.clean()
        except DjangoValidationError as error:
            if hasattr(error, "message_dict"):
                raise serializers.ValidationError(error.message_dict)
            raise serializers.ValidationError({"non_field_errors": error.messages})
        # Anviz's clean() exchanges the key for a token; keep it.
        for field in ("api_token", "api_expires"):
            value = getattr(candidate, field, None)
            if value and value != getattr(self.instance, field, None):
                attrs[field] = value
        return attrs


class BiometricMappingSerializer(serializers.ModelSerializer):
    """The link between a user on a device and an employee."""

    employee = serializers.SerializerMethodField()

    class Meta:
        model = BiometricEmployees
        fields = ("id", "uid", "user_id", "employee_id", "employee", "device_id")
        read_only_fields = ("id", "device_id")

    def get_employee(self, obj):
        return employee_brief(obj.employee_id)


def employee_brief(employee):
    if not employee:
        return None
    return {
        "id": employee.id,
        "full_name": employee.get_full_name(),
        "badge_id": employee.badge_id,
        "is_active": employee.is_active,
    }
