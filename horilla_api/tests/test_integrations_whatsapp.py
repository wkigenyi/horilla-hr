"""
React maintenance APIs for IntegrationApps toggles and WhatsApp credentials.
"""

from django.contrib.auth.models import Permission
from django.test import TestCase
from rest_framework.test import APIClient

from base.models import IntegrationApps
from horilla.horilla_middlewares import set_selected_company
from horilla.testkit import make_company, make_employee, make_user
from whatsapp.models import WhatsappCredientials

PASSWORD = "secret123"
INTEGRATIONS_URL = "/api/v1/base/integrations/"
WHATSAPP_URL = "/api/v1/whatsapp/credentials/"


class IntegrationsWhatsappAPITests(TestCase):
    def setUp(self):
        self.client = APIClient()
        set_selected_company(None)
        self.company = make_company("Integrations Co")
        self.user = make_user("int_admin", password=PASSWORD)
        make_employee(
            company=self.company,
            email="int-admin@test.horilla",
            first_name="Ivy",
            user=self.user,
        )
        for codename in (
            "view_whatsappcredientials",
            "add_whatsappcredientials",
            "change_whatsappcredientials",
            "delete_whatsappcredientials",
        ):
            self.user.user_permissions.add(
                Permission.objects.get(codename=codename)
            )
        self.user = type(self.user).objects.get(pk=self.user.pk)
        self.client.force_authenticate(user=self.user)

    def test_list_integrations_includes_whatsapp_disabled_by_default(self):
        response = self.client.get(INTEGRATIONS_URL)
        self.assertEqual(response.status_code, 200, response.content)
        labels = {row["app_label"]: row for row in response.data["results"]}
        self.assertIn("whatsapp", labels)
        self.assertTrue(labels["whatsapp"]["installed"])
        self.assertFalse(labels["whatsapp"]["is_enabled"])

    def test_enable_whatsapp_then_create_credential(self):
        enabled = self.client.patch(
            f"{INTEGRATIONS_URL}whatsapp/",
            {"is_enabled": True},
            format="json",
        )
        self.assertEqual(enabled.status_code, 200, enabled.content)
        self.assertTrue(enabled.data["is_enabled"])
        self.assertTrue(
            IntegrationApps.objects.filter(
                app_label="whatsapp", is_enabled=True
            ).exists()
        )

        created = self.client.post(
            WHATSAPP_URL,
            {
                "meta_token": "tok-secret",
                "meta_business_id": "biz-1",
                "meta_phone_number_id": "phone-1",
                "meta_phone_number": "+15551212",
                "meta_webhook_token": "hook-secret",
                "meta_app_secret": "app-secret",
                "is_primary": True,
                "company_ids": [self.company.id],
            },
            format="json",
        )
        self.assertEqual(created.status_code, 201, created.content)
        self.assertNotIn("meta_token", created.data)
        self.assertTrue(created.data["meta_token_configured"])
        self.assertTrue(created.data["meta_app_secret_configured"])
        self.assertEqual(created.data["meta_business_id"], "biz-1")
        self.assertEqual(created.data["companies"][0]["id"], self.company.id)

        listed = self.client.get(WHATSAPP_URL)
        self.assertEqual(listed.status_code, 200, listed.content)
        self.assertEqual(listed.data["count"], 1)

    def test_credentials_forbidden_while_disabled(self):
        response = self.client.get(WHATSAPP_URL)
        self.assertEqual(response.status_code, 403, response.content)

    def test_update_and_delete_credential(self):
        IntegrationApps.objects.create(app_label="whatsapp", is_enabled=True)
        cred = WhatsappCredientials.objects.create(
            meta_token="tok",
            meta_business_id="biz",
            meta_phone_number_id="pid",
            meta_phone_number="+100",
            meta_webhook_token="hook",
            meta_app_secret="sec",
            is_primary=True,
        )
        patched = self.client.patch(
            f"{WHATSAPP_URL}{cred.id}/",
            {"meta_phone_number": "+1999"},
            format="json",
        )
        self.assertEqual(patched.status_code, 200, patched.content)
        self.assertEqual(patched.data["meta_phone_number"], "+1999")

        deleted = self.client.delete(f"{WHATSAPP_URL}{cred.id}/")
        self.assertEqual(deleted.status_code, 204, deleted.content)
        self.assertFalse(WhatsappCredientials.objects.filter(pk=cred.id).exists())

    def test_stranger_cannot_toggle_whatsapp(self):
        stranger = make_user("int_stranger", password=PASSWORD)
        make_employee(
            company=self.company,
            email="int-stranger@test.horilla",
            first_name="Sam",
            user=stranger,
        )
        client = APIClient()
        client.force_authenticate(user=stranger)
        response = client.patch(
            f"{INTEGRATIONS_URL}whatsapp/",
            {"is_enabled": True},
            format="json",
        )
        self.assertEqual(response.status_code, 403, response.content)
