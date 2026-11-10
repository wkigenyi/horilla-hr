"""
System Preferences and color themes over JWT.

The web page groups these rows under one header. The API has to keep the
same company scope and the same permission gates, and a caller who cannot
see a control must not be able to write it.
"""

from django.contrib.auth.models import Permission
from django.test import TestCase
from rest_framework.test import APIClient

from base.models import AnnouncementExpire, Company, DynamicPagination
from employee.models import EmployeeGeneralSetting
from horilla.horilla_middlewares import set_selected_company
from horilla.testkit import make_company, make_employee, make_user
from horilla_theme.models import THEMES_DATA, CompanyTheme, HorillaColorTheme

PREFERENCES_URL = "/api/v1/base/system-preferences/"
THEMES_URL = "/api/v1/base/color-themes/"
ACTIVATE_URL = "/api/v1/base/color-themes/activate/"
DEFAULT_URL = "/api/v1/base/color-themes/default/"


def grant(user, codename):
    user.user_permissions.add(Permission.objects.get(codename=codename))


class SystemPreferencesTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        set_selected_company(None)
        self.company = make_company("Prefs Co")
        self.other = make_company("Other Co")
        self.admin = make_user("prefs_admin", is_superuser=True)
        make_employee(
            company=self.company, email="prefs_admin@test.horilla", user=self.admin
        )
        self.reader = make_user("prefs_reader")
        make_employee(
            company=self.company, email="prefs_reader@test.horilla", user=self.reader
        )
        grant(self.reader, "change_announcementexpire")
        grant(self.reader, "view_dynamicpagination")
        grant(self.reader, "view_company")

    def test_requires_authentication(self):
        self.assertEqual(APIClient().get(PREFERENCES_URL).status_code, 401)
        self.assertEqual(APIClient().patch(PREFERENCES_URL, {}, format="json").status_code, 401)

    def test_superuser_reads_the_grouped_settings(self):
        self.client.force_authenticate(user=self.admin)
        response = self.client.get(PREFERENCES_URL)
        self.assertEqual(response.status_code, 200, response.content)
        self.assertTrue(response.data["company_is_all"])
        self.assertIn("expire_days", response.data["general"])
        self.assertIn("records_per_page", response.data["general"])
        self.assertIn("badge_prefix", response.data["formatting"])
        self.assertIn("currency", response.data["formatting"])
        self.assertIn("date_format", response.data["formatting"])
        self.assertIn("restrict_login", response.data["access"])
        self.assertIn("work_info_tracking", response.data["access"])
        self.assertIn("enabled", response.data["languages"])
        self.assertIn("version", response.data)

    def test_reader_only_sees_the_sections_they_can_open(self):
        self.client.force_authenticate(user=self.reader)
        response = self.client.get(PREFERENCES_URL)
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.data["company_id"], self.company.id)
        self.assertIn("expire_days", response.data["general"])
        self.assertIn("date_format", response.data["formatting"])
        self.assertNotIn("badge_prefix", response.data["formatting"])
        self.assertNotIn("currency", response.data.get("formatting", {}))
        self.assertNotIn("access", response.data)
        self.assertNotIn("languages", response.data)

    def test_reader_cannot_write_a_hidden_setting(self):
        self.client.force_authenticate(user=self.reader)
        response = self.client.patch(
            PREFERENCES_URL,
            {"formatting": {"badge_prefix": "NOPE"}},
            format="json",
        )
        self.assertEqual(response.status_code, 400, response.content)
        self.assertFalse(
            EmployeeGeneralSetting.objects.filter(badge_id_prefix="NOPE").exists()
        )

    def test_expire_days_and_page_size_save_for_the_callers_company(self):
        self.client.force_authenticate(user=self.reader)
        response = self.client.patch(
            PREFERENCES_URL,
            {"general": {"expire_days": 14, "records_per_page": 25}},
            format="json",
        )
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.data["general"]["expire_days"]["value"], 14)
        self.assertEqual(response.data["general"]["records_per_page"]["value"], 25)
        self.assertEqual(
            AnnouncementExpire.objects.get(company_id=self.company).days, 14
        )
        self.assertEqual(
            DynamicPagination.objects.get(
                user_id=self.reader, company_id=self.company
            ).pagination,
            25,
        )
        self.assertFalse(
            AnnouncementExpire.objects.filter(company_id=self.other, days=14).exists()
        )

    def test_invalid_date_format_is_rejected(self):
        self.client.force_authenticate(user=self.admin)
        response = self.client.patch(
            PREFERENCES_URL,
            {"formatting": {"date_format": "not-a-format"}},
            format="json",
        )
        self.assertEqual(response.status_code, 400, response.content)

    def test_all_companies_date_format_writes_every_company(self):
        self.client.force_authenticate(user=self.admin)
        response = self.client.patch(
            PREFERENCES_URL,
            {"formatting": {"date_format": "YYYY-MM-DD", "time_format": "HH:mm"}},
            format="json",
        )
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(
            set(Company.objects.values_list("date_format", flat=True)),
            {"YYYY-MM-DD"},
        )
        self.assertEqual(
            set(Company.objects.values_list("time_format", flat=True)),
            {"HH:mm"},
        )


class ColorThemeTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        set_selected_company(None)
        self.company = make_company("Theme Co")
        self.admin = make_user("theme_admin", is_superuser=True)
        make_employee(
            company=self.company, email="theme_admin@test.horilla", user=self.admin
        )
        self.member = make_user("theme_member")
        make_employee(
            company=self.company, email="theme_member@test.horilla", user=self.member
        )
        grant(self.member, "view_horillacolortheme")
        grant(self.member, "change_horillacolortheme")
        if not HorillaColorTheme.objects.exists():
            for row in THEMES_DATA:
                HorillaColorTheme.objects.create(**row)
        self.theme = HorillaColorTheme.objects.exclude(
            name="Coral Red Theme (Default)"
        ).first()

    def test_requires_authentication(self):
        self.assertEqual(APIClient().get(THEMES_URL).status_code, 401)

    def test_list_includes_preview_stops_and_the_active_mark(self):
        self.client.force_authenticate(user=self.member)
        response = self.client.get(THEMES_URL)
        self.assertEqual(response.status_code, 200, response.content)
        self.assertFalse(response.data["company_is_all"])
        first = response.data["themes"][0]
        self.assertEqual(len(first["preview"]), 5)
        self.assertTrue(any(theme["is_active"] for theme in response.data["themes"]))

    def test_member_activates_a_theme_for_their_company(self):
        self.client.force_authenticate(user=self.member)
        response = self.client.post(
            ACTIVATE_URL, {"theme_id": self.theme.id}, format="json"
        )
        self.assertEqual(response.status_code, 200, response.content)
        self.assertTrue(response.data["is_active"])
        stored = CompanyTheme.objects.get(company=self.company)
        self.assertEqual(stored.theme_id, self.theme.id)

    def test_all_companies_cannot_activate_a_theme(self):
        self.client.force_authenticate(user=self.admin)
        response = self.client.post(
            ACTIVATE_URL, {"theme_id": self.theme.id}, format="json"
        )
        self.assertEqual(response.status_code, 400, response.content)
        self.assertFalse(CompanyTheme.objects.filter(company=self.company, theme=self.theme).exists())

    def test_all_companies_can_toggle_the_login_default(self):
        self.client.force_authenticate(user=self.admin)
        response = self.client.post(
            DEFAULT_URL, {"theme_id": self.theme.id}, format="json"
        )
        self.assertEqual(response.status_code, 200, response.content)
        self.theme.refresh_from_db()
        self.assertTrue(self.theme.is_default)
        self.assertEqual(
            HorillaColorTheme.objects.filter(is_default=True).count(), 1
        )

    def test_a_company_user_cannot_change_the_login_default(self):
        self.client.force_authenticate(user=self.member)
        grant(self.member, "add_horillacolortheme")
        response = self.client.post(
            DEFAULT_URL, {"theme_id": self.theme.id}, format="json"
        )
        self.assertEqual(response.status_code, 400, response.content)
