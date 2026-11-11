"""Serializers for WhatsApp Business credentials."""

from rest_framework import serializers

from base.models import Company, IntegrationApps
from whatsapp.models import WhatsappCredientials


def whatsapp_integration_enabled(company=None):
    qs = IntegrationApps.objects.filter(app_label="whatsapp", is_enabled=True)
    if company is not None:
        return qs.filter(company=company).exists() or qs.filter(company=None).exists()
    return qs.exists()


class WhatsappCredentialSerializer(serializers.ModelSerializer):
    company_ids = serializers.PrimaryKeyRelatedField(
        many=True,
        queryset=Company.objects.all(),
        source="company_id",
        required=False,
    )
    companies = serializers.SerializerMethodField(read_only=True)
    meta_token_configured = serializers.SerializerMethodField(read_only=True)
    meta_app_secret_configured = serializers.SerializerMethodField(read_only=True)
    meta_webhook_token_configured = serializers.SerializerMethodField(read_only=True)

    class Meta:
        model = WhatsappCredientials
        fields = [
            "id",
            "meta_token",
            "meta_business_id",
            "meta_phone_number_id",
            "meta_phone_number",
            "meta_webhook_token",
            "meta_app_secret",
            "created_templates",
            "is_primary",
            "company_ids",
            "companies",
            "meta_token_configured",
            "meta_app_secret_configured",
            "meta_webhook_token_configured",
        ]
        read_only_fields = ["created_templates"]
        extra_kwargs = {
            # Never echo secrets back — same idea as LinkedIn api_token.
            "meta_token": {"write_only": True, "required": False},
            "meta_app_secret": {"write_only": True, "required": False},
            "meta_webhook_token": {"write_only": True, "required": False},
        }

    def get_companies(self, obj):
        return [
            {"id": company.id, "company": company.company}
            for company in obj.company_id.all()
        ]

    def get_meta_token_configured(self, obj):
        return bool((obj.meta_token or "").strip())

    def get_meta_app_secret_configured(self, obj):
        return bool((obj.meta_app_secret or "").strip())

    def get_meta_webhook_token_configured(self, obj):
        return bool((obj.meta_webhook_token or "").strip())

    def validate(self, attrs):
        companies = attrs.get("company_id")
        if companies is None and self.instance is not None:
            companies = list(self.instance.company_id.all())
        is_primary = attrs.get(
            "is_primary",
            self.instance.is_primary if self.instance is not None else False,
        )
        if companies:
            for company in companies:
                existing = WhatsappCredientials.objects.filter(
                    company_id=company, is_primary=True
                )
                if self.instance is not None:
                    existing = existing.exclude(pk=self.instance.pk)
                if is_primary and existing.exists():
                    raise serializers.ValidationError(
                        {
                            "is_primary": (
                                f"Company '{company.company}' already has a "
                                "primary credential."
                            )
                        }
                    )
                if not is_primary and not existing.exists():
                    attrs["is_primary"] = True
        return attrs

    def create(self, validated_data):
        if not (validated_data.get("meta_token") or "").strip():
            raise serializers.ValidationError(
                {"meta_token": "This field is required."}
            )
        if not (validated_data.get("meta_webhook_token") or "").strip():
            raise serializers.ValidationError(
                {"meta_webhook_token": "This field is required."}
            )
        companies = validated_data.pop("company_id", [])
        instance = WhatsappCredientials.objects.create(**validated_data)
        if companies:
            instance.company_id.set(companies)
        return instance

    def update(self, instance, validated_data):
        companies = validated_data.pop("company_id", None)
        for secret in ("meta_token", "meta_app_secret", "meta_webhook_token"):
            if secret in validated_data and not (
                validated_data.get(secret) or ""
            ).strip():
                validated_data.pop(secret)
        for key, value in validated_data.items():
            setattr(instance, key, value)
        instance.save()
        if companies is not None:
            instance.company_id.set(companies)
        return instance
