"""First-run setup JSON endpoints.

The HTML wizard stays the session implementation. These routes are the same
gate for an API client: no user is created until DB_INIT_PASSWORD has been
checked, and nothing about that password is returned by the status probe.
"""

from django.core.signing import TimestampSigner
from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from base.models import Company, Department, JobPosition
from employee.models import EmployeeWorkInformation
from horilla.testkit import make_employee
from horilla_api.api_views.setup.views import SETUP_SALT, issue_setup_token
from horilla_auth.models import HorillaUser

STATUS_URL = "/api/v1/setup/status/"
VERIFY_URL = "/api/v1/setup/verify/"
USER_URL = "/api/v1/setup/user/"

USER_BODY = {
    "username": "ada",
    "password": "a-real-password",
    "confirm_password": "a-real-password",
    "firstname": "Ada",
    "lastname": "Lovelace",
    "badge_id": "A1",
    "email": "ada@test.horilla",
    "phone": "5551234567",
}


class SetupApiTests(TestCase):
    def setUp(self):
        self.client = APIClient()

    def _verified_token(self):
        from django.conf import settings

        response = self.client.post(
            VERIFY_URL,
            {"password": settings.DB_INIT_PASSWORD},
            format="json",
        )
        self.assertEqual(response.status_code, 200, response.data)
        return response.data["setup_token"]

    def test_fresh_database_needs_init(self):
        response = self.client.get(STATUS_URL)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data, {"needs_init": True})

    def test_status_does_not_reveal_the_init_password(self):
        from django.conf import settings

        body = self.client.get(STATUS_URL).content.decode()

        self.assertNotIn(settings.DB_INIT_PASSWORD, body)

    def test_wrong_password_is_rejected(self):
        response = self.client.post(
            VERIFY_URL, {"password": "not-the-password"}, format="json"
        )

        self.assertEqual(response.status_code, 401)
        self.assertNotIn("setup_token", response.data)

    def test_user_step_rejects_a_missing_token(self):
        response = self.client.post(USER_URL, USER_BODY, format="json")

        self.assertEqual(response.status_code, 403)
        self.assertFalse(HorillaUser.objects.filter(username="ada").exists())

    def test_user_step_rejects_a_forged_token(self):
        body = {**USER_BODY, "setup_token": "init:forged"}

        response = self.client.post(USER_URL, body, format="json")

        self.assertEqual(response.status_code, 403)
        self.assertFalse(HorillaUser.objects.filter(username="ada").exists())

    def test_user_step_rejects_an_expired_token(self):
        from unittest.mock import patch

        signer = TimestampSigner(salt=SETUP_SALT)
        issued = timezone.now().timestamp() - (11 * 60)
        # TimestampSigner.sign reads time.time. Freeze that clock so the
        # signature is already older than the 10-minute setup token.
        with patch("django.core.signing.time.time", return_value=issued):
            token = signer.sign("init")

        response = self.client.post(
            USER_URL, {**USER_BODY, "setup_token": token}, format="json"
        )

        self.assertEqual(response.status_code, 403)
        self.assertFalse(HorillaUser.objects.filter(username="ada").exists())

    def test_password_mismatch_does_not_create_a_user(self):
        token = self._verified_token()
        response = self.client.post(
            USER_URL,
            {**USER_BODY, "setup_token": token, "confirm_password": "different"},
            format="json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertFalse(HorillaUser.objects.exists())

    @override_settings(DEBUG=False)
    def test_verified_user_step_creates_a_superuser_and_logs_in(self):
        token = self._verified_token()
        response = self.client.post(
            USER_URL, {**USER_BODY, "setup_token": token}, format="json"
        )

        self.assertEqual(response.status_code, 201, response.data)
        user = HorillaUser.objects.get(username="ada")
        self.assertTrue(user.is_superuser)
        self.assertEqual(user.employee_get.email, "ada@test.horilla")
        self.assertTrue(
            EmployeeWorkInformation.objects.filter(
                employee_id=user.employee_get
            ).exists()
        )
        self.assertIn("access", response.data)
        self.assertIn("refresh", response.data)
        self.assertEqual(response.data["employee"]["id"], user.employee_get.pk)
        self.assertFalse(self.client.get(STATUS_URL).data["needs_init"])

    def test_views_share_the_login_throttle_scope(self):
        from horilla_api.api_views.setup.views import (
            SetupUserAPIView,
            SetupVerifyAPIView,
        )

        self.assertEqual(SetupVerifyAPIView.throttle_scope, "login")
        self.assertEqual(SetupUserAPIView.throttle_scope, "login")

    def test_orphan_superuser_with_the_same_username_is_replaced(self):
        HorillaUser.objects.create_superuser(
            username="ada", email="old@test.horilla", password="old-password"
        )
        self.assertTrue(self.client.get(STATUS_URL).data["needs_init"])

        token = self._verified_token()
        response = self.client.post(
            USER_URL, {**USER_BODY, "setup_token": token}, format="json"
        )

        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(HorillaUser.objects.filter(username="ada").count(), 1)
        self.assertTrue(HorillaUser.objects.get(username="ada").check_password(
            "a-real-password"
        ))

    def test_initialized_database_refuses_verify_and_user(self):
        company = Company.objects.create(
            company="Acme",
            hq=True,
            address="1 Test St",
            country="US",
            state="CA",
            city="LA",
            zip="90001",
        )
        user = HorillaUser.objects.create_superuser(
            username="root", email="root@test.horilla", password="pw-not-real"
        )
        make_employee(company=company, email="root@test.horilla", user=user)
        token = issue_setup_token()

        verify = self.client.post(VERIFY_URL, {"password": "anything"}, format="json")
        create = self.client.post(
            USER_URL, {**USER_BODY, "setup_token": token}, format="json"
        )

        self.assertEqual(verify.status_code, 403)
        self.assertEqual(create.status_code, 403)
        self.assertFalse(HorillaUser.objects.filter(username="ada").exists())
        self.assertFalse(self.client.get(STATUS_URL).data["needs_init"])

    def test_login_payload_can_create_company_department_and_job(self):
        """The steps the UI runs after the first user exists."""
        token = self._verified_token()
        created = self.client.post(
            USER_URL, {**USER_BODY, "setup_token": token}, format="json"
        )
        access = created.data["access"]
        employee_id = created.data["employee"]["id"]
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {access}")

        company = self.client.post(
            "/api/v1/base/companies/",
            {
                "company": "Acme",
                "hq": True,
                "address": "1 Test St",
                "country": "US",
                "state": "CA",
                "city": "LA",
                "zip": "90001",
            },
            format="json",
        )
        self.assertEqual(company.status_code, 201, company.data)
        company_id = company.data["id"]

        work = self.client.get(
            "/api/v1/employee/employee-work-information/?page_size=100"
        )
        self.assertEqual(work.status_code, 200, work.data)
        match = next(
            row for row in work.data["results"] if row["employee_id"] == employee_id
        )
        linked = self.client.put(
            f"/api/v1/employee/employee-work-information/{match['id']}/",
            {"company_id": company_id},
            format="json",
        )
        self.assertEqual(linked.status_code, 200, linked.data)
        self.assertEqual(linked.data["company_id"], company_id)

        department = self.client.post(
            "/api/v1/base/departments/",
            {"department": "Engineering", "company_id": [company_id]},
            format="json",
        )
        self.assertEqual(department.status_code, 201, department.data)

        position = self.client.post(
            "/api/v1/base/job-positions/",
            {
                "job_position": "Engineer",
                "department_id": department.data["id"],
                "company_id": [company_id],
            },
            format="json",
        )
        self.assertEqual(position.status_code, 201, position.data)

        renamed = self.client.put(
            f"/api/v1/base/departments/{department.data['id']}/",
            {"department": "Product", "company_id": [company_id]},
            format="json",
        )
        self.assertEqual(renamed.status_code, 200, renamed.data)

        moved = self.client.put(
            f"/api/v1/base/job-positions/{position.data['id']}/",
            {
                "job_position": "Designer",
                "department_id": department.data["id"],
                "company_id": [company_id],
            },
            format="json",
        )
        self.assertEqual(moved.status_code, 200, moved.data)

        removed = self.client.delete(
            f"/api/v1/base/job-positions/{position.data['id']}/"
        )
        self.assertEqual(removed.status_code, 200)
        self.assertTrue(Department.objects.filter(department="Product").exists())
        self.assertFalse(JobPosition.objects.filter(job_position="Engineer").exists())
