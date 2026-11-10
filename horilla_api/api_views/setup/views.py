"""JSON first-run setup.

The HTML wizard in ``base.views`` is a Django session plus HTMX fragments.
These three routes reuse its guards — ``initialize_database_condition`` and
``DB_INIT_PASSWORD`` — and return JSON so another client can create the first
superuser. Company, department, and job position stay on the authenticated
API after that login payload is issued.
"""

import hmac

from django.conf import settings
from django.core.exceptions import ValidationError as DjangoValidationError
from django.core.signing import BadSignature, SignatureExpired, TimestampSigner
from django.db import IntegrityError, transaction
from django.utils.translation import gettext_lazy as _
from drf_yasg import openapi
from rest_framework import serializers
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from employee.models import Employee, phone_validator
from horilla_api.api_views.auth.views import build_login_payload
from horilla_api.docs import document_api
from horilla_auth.models import HorillaUser

SETUP_SALT = "horilla.database-setup"
SETUP_TOKEN_MAX_AGE = 10 * 60


def issue_setup_token():
    return TimestampSigner(salt=SETUP_SALT).sign("init")


def setup_token_error(token):
    """None when ``token`` is a fresh password-check proof. Otherwise a message."""
    if not isinstance(token, str) or not token:
        return _("Verify the database initialization password to continue.")
    try:
        value = TimestampSigner(salt=SETUP_SALT).unsign(
            token, max_age=SETUP_TOKEN_MAX_AGE
        )
    except SignatureExpired:
        return _("The setup verification expired. Enter the password again.")
    except BadSignature:
        return _("Verify the database initialization password to continue.")
    if value != "init":
        return _("Verify the database initialization password to continue.")
    return None


def _flat_error(detail):
    if isinstance(detail, dict):
        for value in detail.values():
            text = _flat_error(value)
            if text:
                return text
        return _("Invalid data.")
    if isinstance(detail, (list, tuple)):
        return _flat_error(detail[0]) if detail else _("Invalid data.")
    text = str(detail).strip()
    return text or _("Invalid data.")


def _needs_init():
    # Imported lazily: base.views pulls in the whole HTML app.
    from base.views import initialize_database_condition

    return initialize_database_condition()


class SetupVerifySerializer(serializers.Serializer):
    password = serializers.CharField()


class SetupUserSerializer(serializers.Serializer):
    setup_token = serializers.CharField()
    username = serializers.CharField()
    password = serializers.CharField()
    confirm_password = serializers.CharField()
    firstname = serializers.CharField()
    lastname = serializers.CharField(required=False, allow_blank=True, default="")
    badge_id = serializers.CharField(required=False, allow_blank=True, default="")
    email = serializers.EmailField()
    phone = serializers.CharField()

    def validate_username(self, value):
        value = value.strip()
        if not value:
            raise serializers.ValidationError(_("Enter a username."))
        return value

    def validate_firstname(self, value):
        value = value.strip()
        if not value:
            raise serializers.ValidationError(_("Enter a first name."))
        return value

    def validate_lastname(self, value):
        return value.strip()

    def validate_badge_id(self, value):
        return value.strip()

    def validate_email(self, value):
        return value.strip()

    def validate_phone(self, value):
        value = value.strip()
        try:
            phone_validator(value)
        except DjangoValidationError as exc:
            raise serializers.ValidationError(list(exc.messages))
        return value

    def validate(self, data):
        if data["password"] != data["confirm_password"]:
            raise serializers.ValidationError(
                {"confirm_password": _("Passwords do not match.")}
            )
        return data


class SetupStatusAPIView(APIView):
    """Whether the login screen should offer database initialization."""

    permission_classes = [AllowAny]

    @document_api(
        operation_description=(
            "Report whether the database still needs its first superuser. "
            "Returns no other data."
        ),
        responses={
            200: openapi.Schema(
                type=openapi.TYPE_OBJECT,
                properties={
                    "needs_init": openapi.Schema(type=openapi.TYPE_BOOLEAN),
                },
            )
        },
        tags=["setup"],
    )
    def get(self, request):
        return Response({"needs_init": _needs_init()})


class SetupVerifyAPIView(APIView):
    """Check ``DB_INIT_PASSWORD`` and return a short-lived setup token."""

    permission_classes = [AllowAny]
    # Same bucket as login: this is an unauthenticated secret check.
    throttle_scope = "login"

    @document_api(
        operation_description=(
            "Verify the server's database initialization password. "
            "On success, returns a setup token that expires in 10 minutes."
        ),
        request_body=SetupVerifySerializer,
        responses={
            200: openapi.Schema(
                type=openapi.TYPE_OBJECT,
                properties={
                    "setup_token": openapi.Schema(type=openapi.TYPE_STRING),
                },
            )
        },
        tags=["setup"],
    )
    def post(self, request):
        if not _needs_init():
            return Response(
                {"error": _("The database is already initialized.")},
                status=403,
            )
        serializer = SetupVerifySerializer(data=request.data)
        if not serializer.is_valid():
            return Response({"error": _flat_error(serializer.errors)}, status=400)
        supplied = serializer.validated_data["password"]
        expected = settings.DB_INIT_PASSWORD or ""
        if (
            not isinstance(supplied, str)
            or not expected
            or not hmac.compare_digest(supplied, expected)
        ):
            return Response(
                {
                    "error": _(
                        "The password you entered is incorrect. Please try again."
                    )
                },
                status=401,
            )
        return Response({"setup_token": issue_setup_token()})


class SetupUserAPIView(APIView):
    """Create the first superuser and employee, then return a normal login."""

    permission_classes = [AllowAny]
    throttle_scope = "login"

    @document_api(
        operation_description=(
            "Create the first superuser and employee after the initialization "
            "password has been verified. Returns the same payload as /auth/login/."
        ),
        request_body=SetupUserSerializer,
        tags=["setup"],
    )
    def post(self, request):
        if not _needs_init():
            return Response(
                {"error": _("The database is already initialized.")},
                status=403,
            )
        serializer = SetupUserSerializer(data=request.data)
        if not serializer.is_valid():
            return Response({"error": _flat_error(serializer.errors)}, status=400)
        data = serializer.validated_data
        token_error = setup_token_error(data["setup_token"])
        if token_error:
            return Response({"error": token_error}, status=403)

        try:
            user = _create_initial_user(data)
        except DjangoValidationError as exc:
            detail = exc.message_dict if hasattr(exc, "message_dict") else exc.messages
            return Response({"error": _flat_error(detail)}, status=400)
        except IntegrityError:
            return Response(
                {"error": _("That username or email is already in use.")},
                status=400,
            )
        if user is None:
            return Response(
                {"error": _("The database is already initialized.")},
                status=403,
            )
        return Response(build_login_payload(user), status=201)


def _create_initial_user(data):
    """Match ``initialize_database_user``: superuser, then employee.

    An orphan superuser with the same username and no employee is replaced,
    which is what the HTML step does. Returns None when setup finished
    between the view's check and this write.
    """
    with transaction.atomic():
        if not _needs_init():
            return None
        existing = HorillaUser.objects.filter(username=data["username"]).first()
        if existing is not None:
            if hasattr(existing, "employee_get"):
                raise IntegrityError("username")
            existing.delete()
        user = HorillaUser.objects.create_superuser(
            username=data["username"],
            email=data["email"],
            password=data["password"],
        )
        employee = Employee(
            employee_user_id=user,
            badge_id=data["badge_id"] or None,
            employee_first_name=data["firstname"],
            employee_last_name=data["lastname"],
            email=data["email"],
            phone=data["phone"],
        )
        employee.save()
        return user
