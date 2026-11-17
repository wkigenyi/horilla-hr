"""
The capability payload a client paints its navigation from.

Two things it must get right: the role has to reflect what the user actually
is, and ``features`` has to state app availability explicitly -- a client
cannot infer it by probing, because DRF returns 404 both for a missing route
and a missing object.

These are UI hints. The tests assert the payload's shape and derivation, not
that it grants anything; authorization stays with the endpoints.
"""

from django.contrib.auth.models import Permission
from django.test import TestCase
from rest_framework.test import APIClient

from employee.models import ProfileEditFeature
from horilla.horilla_middlewares import set_selected_company
from horilla.testkit import make_company, make_employee, make_user
from horilla_api.api_methods.base.capabilities import build_capabilities

LOGIN_URL = "/api/v1/auth/login/"
CAPABILITIES_URL = "/api/v1/base/capabilities/"
PASSWORD = "secret123"

# Allow-list keys from has_perm (excludes view_team / edit_own_profile / manage_roles /
# can_switch_company, which are derived separately). Every key must be present.
FIRST_WAVE_KEYS = (
    "view_employee",
    "edit_employee",
    "approve_shift_request",
    "view_payslip",
    "change_payslip",
    "add_payslip",
    "delete_payslip",
    "view_contract",
    "add_contract",
    "change_contract",
    "view_loanaccount",
    "change_loanaccount",
    "add_loanaccount",
    "view_payadjustment",
    "add_payadjustment",
    "change_payadjustment",
    "delete_payadjustment",
    "view_reimbursement",
    "add_reimbursement",
    "change_reimbursement",
    "view_filingstatus",
    "add_filingstatus",
    "change_filingstatus",
    "delete_filingstatus",
    "view_taxbracket",
    "add_taxbracket",
    "change_taxbracket",
    "delete_taxbracket",
    "view_salarystructure",
    "add_salarystructure",
    "change_salarystructure",
    "delete_salarystructure",
    "view_allowance",
    "add_allowance",
    "change_allowance",
    "delete_allowance",
    "view_deduction",
    "add_deduction",
    "change_deduction",
    "delete_deduction",
    "view_payrollsettings",
    "change_payrollsettings",
    "change_encashmentgeneralsettings",
    "view_project",
    "add_project",
    "change_project",
    "delete_project",
    "view_task",
    "add_task",
    "change_task",
    "delete_task",
    "view_timesheet",
    "add_timesheet",
    "change_timesheet",
    "delete_timesheet",
    "add_projectstage",
)

WAVE_TWO_KEYS = (
    "approve_leave",
    "approve_attendance",
    "view_leaverequest",
    "add_leaverequest",
    "change_leaverequest",
    "delete_leaverequest",
    "view_leaveallocationrequest",
    "change_leaveallocationrequest",
    "view_leavetype",
    "add_leavetype",
    "change_leavetype",
    "delete_leavetype",
    "view_availableleave",
    "change_availableleave",
    "view_holidays",
    "add_holidays",
    "change_holidays",
    "delete_holidays",
    "view_companyleaves",
    "add_companyleave",
    "change_companyleaves",
    "delete_companyleaves",
    "view_attendance",
    "add_attendance",
    "change_attendance",
    "delete_attendance",
    "view_attendanceovertime",
    "change_attendanceovertime",
    "view_attendancelatecomeearlyout",
    "view_recruitment",
    "add_recruitment",
    "change_recruitment",
    "delete_recruitment",
    "view_candidate",
    "add_candidate",
    "change_candidate",
    "delete_candidate",
    "view_stage",
    "change_stage",
    "view_interviewschedule",
    "change_interviewschedule",
    "view_onboardingstage",
    "change_onboardingstage",
    "view_onboardingtask",
    "change_onboardingtask",
    "view_candidatestage",
    "change_candidatestage",
    "view_candidatetask",
    "change_candidatetask",
    "view_asset",
    "add_asset",
    "change_asset",
    "delete_asset",
    "view_assetcategory",
    "change_assetcategory",
    "view_assetlot",
    "change_assetlot",
    "view_assetrequest",
    "add_assetrequest",
    "change_assetrequest",
    "view_ticket",
    "add_ticket",
    "change_ticket",
    "delete_ticket",
    "view_tickettype",
    "change_tickettype",
    "view_faq",
    "change_faq",
    "view_offboarding",
    "change_offboarding",
    "view_resignationletter",
    "add_resignationletter",
    "change_resignationletter",
    "view_offboardingstage",
    "change_offboardingstage",
    "view_offboardingtask",
    "change_offboardingtask",
    "view_objective",
    "add_objective",
    "change_objective",
    "delete_objective",
    "view_employeeobjective",
    "change_employeeobjective",
    "view_keyresult",
    "change_keyresult",
    "view_feedback",
    "change_feedback",
    "view_meetings",
    "change_meetings",
    "view_employeebonuspoint",
    "change_employeebonuspoint",
    "view_company",
    "change_company",
    "view_horillacolortheme",
    "change_horillacolortheme",
)

ALLOW_LIST_KEYS = FIRST_WAVE_KEYS + WAVE_TWO_KEYS

HR_VIEW_KEYS = (
    "view_employee",
    "view_payslip",
    "view_contract",
    "view_loanaccount",
    "view_payadjustment",
    "view_reimbursement",
    "view_filingstatus",
    "view_taxbracket",
    "view_salarystructure",
    "view_allowance",
    "view_deduction",
    "view_payrollsettings",
    "view_project",
    "view_task",
    "view_timesheet",
)

WAVE_TWO_VIEW_KEYS = (
    "view_leaverequest",
    "view_attendance",
    "view_recruitment",
    "view_asset",
    "view_ticket",
    "view_offboarding",
    "view_objective",
)


class CapabilitiesTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        set_selected_company(None)
        self.company = make_company("Caps Co")

        self.user = make_user("caps_user", password=PASSWORD)
        self.employee = make_employee(
            company=self.company,
            email="caps@test.horilla",
            first_name="Cara",
            user=self.user,
        )

    def _grant(self, user, app_label, codename):
        user.user_permissions.add(
            Permission.objects.get(
                content_type__app_label=app_label, codename=codename
            )
        )
        # has_perm caches on the instance; reload so the new grant is visible.
        return type(user).objects.get(pk=user.pk)

    def _assert_keys_present(self, permissions):
        missing = [key for key in ALLOW_LIST_KEYS if key not in permissions]
        self.assertEqual(missing, [])
        for key in ALLOW_LIST_KEYS:
            self.assertIsInstance(permissions[key], bool)

    def _login(self):
        response = self.client.post(
            LOGIN_URL,
            {"username": "caps_user", "password": PASSWORD},
            format="json",
        )
        self.assertEqual(response.status_code, 200, response.content)
        return response.data

    def test_login_carries_capabilities(self):
        """The point of the change: no probe round trips before first paint."""
        caps = self._login()["capabilities"]
        self.assertIn("role", caps)
        self.assertIn("permissions", caps)
        self.assertIn("features", caps)
        self.assertIn("version", caps)

    def test_endpoint_returns_the_same_payload(self):
        """A long-lived client refreshes here rather than re-logging in."""
        from_login = self._login()["capabilities"]

        client = APIClient()
        client.force_authenticate(user=self.user)
        response = client.get(CAPABILITIES_URL)
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.data, from_login)

    def test_endpoint_requires_authentication(self):
        self.assertEqual(APIClient().get(CAPABILITIES_URL).status_code, 401)

    def test_plain_employee_is_employee(self):
        self.assertEqual(build_capabilities(self.user)["role"], "employee")
        self.assertFalse(build_capabilities(self.user)["permissions"]["view_team"])
        self.assertFalse(build_capabilities(self.user)["permissions"]["manage_roles"])
        self.assertFalse(
            build_capabilities(self.user)["permissions"]["can_switch_company"]
        )

    def test_reporting_manager_is_manager(self):
        report = make_employee(
            company=self.company,
            email="report@test.horilla",
            first_name="Ravi",
        )
        report.employee_work_info.reporting_manager_id = self.employee
        report.employee_work_info.save()

        caps = build_capabilities(self.user)
        self.assertEqual(caps["role"], "manager")
        self.assertTrue(caps["permissions"]["view_team"])
        self.assertFalse(caps["permissions"]["can_switch_company"])

    def test_superuser_is_hrexec(self):
        admin = make_user("caps_admin", password=PASSWORD, is_superuser=True)
        permissions = build_capabilities(admin)["permissions"]
        self.assertEqual(build_capabilities(admin)["role"], "hrexec")
        self.assertTrue(permissions["manage_roles"])
        self.assertTrue(permissions["can_switch_company"])
        self._assert_keys_present(permissions)
        for key in ALLOW_LIST_KEYS:
            self.assertTrue(permissions[key], key)
        # edit_own_profile stays the profile-edit feature flag, even for a superuser.
        self.assertEqual(
            permissions["edit_own_profile"],
            ProfileEditFeature.objects.filter(is_enabled=True).exists(),
        )

    def test_first_wave_keys_are_false_without_hr_perms(self):
        permissions = build_capabilities(self.user)["permissions"]
        self._assert_keys_present(permissions)
        for key in HR_VIEW_KEYS:
            self.assertFalse(permissions[key], key)

    def test_wave_two_view_keys_are_false_for_plain_employee(self):
        permissions = build_capabilities(self.user)["permissions"]
        self._assert_keys_present(permissions)
        for key in WAVE_TWO_VIEW_KEYS:
            self.assertFalse(permissions[key], key)

    def test_granted_leave_view_leaverequest_is_true(self):
        leave_user = make_user("caps_leave", password=PASSWORD)
        make_employee(
            company=self.company,
            email="leave@test.horilla",
            first_name="Lea",
            user=leave_user,
        )
        leave_user = self._grant(leave_user, "leave", "view_leaverequest")
        permissions = build_capabilities(leave_user)["permissions"]
        self._assert_keys_present(permissions)
        self.assertTrue(permissions["view_leaverequest"])
        self.assertFalse(permissions["view_attendance"])
        self.assertFalse(permissions["view_recruitment"])

    def test_granted_payslip_and_project_view_are_true(self):
        payroll_user = make_user("caps_payroll", password=PASSWORD)
        make_employee(
            company=self.company,
            email="payroll@test.horilla",
            first_name="Pia",
            user=payroll_user,
        )
        payroll_user = self._grant(payroll_user, "payroll", "view_payslip")
        payroll_perms = build_capabilities(payroll_user)["permissions"]
        self._assert_keys_present(payroll_perms)
        self.assertTrue(payroll_perms["view_payslip"])
        self.assertFalse(payroll_perms["view_project"])
        self.assertFalse(payroll_perms["view_contract"])

        project_user = make_user("caps_project", password=PASSWORD)
        make_employee(
            company=self.company,
            email="project@test.horilla",
            first_name="Theo",
            user=project_user,
        )
        project_user = self._grant(project_user, "project", "view_project")
        project_perms = build_capabilities(project_user)["permissions"]
        self._assert_keys_present(project_perms)
        self.assertTrue(project_perms["view_project"])
        self.assertFalse(project_perms["view_payslip"])
        self.assertFalse(project_perms["view_task"])

    def test_features_report_installed_apps_explicitly(self):
        features = build_capabilities(self.user)["features"]
        # geofencing/facedetection are installed from horilla_api/__init__.py,
        # not settings -- the manifest must still report them as present.
        self.assertTrue(features["geofencing"])
        self.assertTrue(features["facedetection"])
        self.assertTrue(features["leave"])
        self.assertTrue(all(isinstance(v, bool) for v in features.values()))
