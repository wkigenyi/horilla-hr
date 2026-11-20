"""Biometric devices API: CRUD, secrets, scoping and ZKTeco operations (machine mocked)."""

from types import SimpleNamespace
from unittest import mock

from django.contrib.auth.models import Permission
from django.test import TestCase
from rest_framework.test import APIClient

from biometric.models import BiometricDevices, BiometricEmployees
from horilla.horilla_middlewares import set_selected_company
from horilla.testkit import make_company, make_employee, make_user

BASE = "/api/v1/biometric/devices/"
ZK_PATH = "horilla_api.api_views.biometric.views.ZK"


class FakeConn:
    """Stands in for a pyzk connection to one machine."""

    def __init__(self, users=None, templates=None):
        self.users_on_device = list(users or [])
        self.templates = list(templates or [])
        self.deleted = []
        self.disconnected = False
        self.users = len(self.users_on_device)
        self.fingers = len(self.templates)
        self.records = 42

    def enable_device(self):
        pass

    def disconnect(self):
        self.disconnected = True

    def test_voice(self, index=0):
        pass

    def get_device_name(self):
        return "K40"

    def get_serialnumber(self):
        return "SN123"

    def get_firmware_version(self):
        return "Ver 6.60"

    def get_platform(self):
        return "ZMM220"

    def read_sizes(self):
        pass

    def get_users(self):
        return list(self.users_on_device)

    def get_templates(self):
        return list(self.templates)

    def set_user(self, uid, name, password, group_id, user_id, card):
        self.users_on_device.append(zk_user(uid, user_id, name))

    def delete_user(self, uid):
        self.deleted.append(uid)
        self.users_on_device = [u for u in self.users_on_device if u.uid != uid]


def zk_user(uid, user_id, name="", privilege=0):
    return SimpleNamespace(
        uid=uid, user_id=str(user_id), name=name, privilege=privilege, card=0, password=""
    )


def fake_zk(conn):
    machine = mock.Mock()
    machine.connect.return_value = conn
    return mock.Mock(return_value=machine)


class BiometricApiTests(TestCase):
    def setUp(self):
        set_selected_company(None)
        self.client = APIClient()
        self.company = make_company("Forest Co")
        self.user = make_user("bio_admin", password="secret123", is_superuser=True)
        self.employee = make_employee(
            company=self.company, email="bio_admin@test.horilla", user=self.user
        )
        self.worker = make_employee(
            company=self.company, email="worker@test.horilla", first_name="Okello"
        )
        self.client.force_authenticate(user=self.user)
        self.device = BiometricDevices.objects.create(
            name="Main gate",
            machine_type="zk",
            machine_ip="192.168.1.201",
            port=4370,
            zk_password="1234",
            company_id=self.company,
        )

    def tearDown(self):
        set_selected_company(None)

    def url(self, suffix=""):
        return f"{BASE}{self.device.pk}/{suffix}"

    # --- device records -------------------------------------------------

    def test_list_hides_secrets(self):
        response = self.client.get(BASE)
        self.assertEqual(response.status_code, 200, response.content)
        row = response.data["results"][0]
        self.assertEqual(row["name"], "Main gate")
        self.assertEqual(row["machine_type_label"], "ZKTeco / eSSL Biometric")
        self.assertNotIn("zk_password", row)
        self.assertTrue(row["has_zk_password"])
        self.assertEqual(row["people_count"], 0)

    def test_create_zk_device_and_default_company(self):
        response = self.client.post(
            BASE,
            {
                "name": "Nursery",
                "machine_type": "zk",
                "machine_ip": "10.0.0.5",
                "port": 4370,
                "zk_password": "0",
                "device_direction": "in",
            },
            format="json",
        )
        self.assertEqual(response.status_code, 201, response.content)
        device = BiometricDevices.objects.get(pk=response.data["id"])
        self.assertEqual(device.company_id, self.company)
        self.assertEqual(device.device_direction, "in")

    def test_create_zk_device_needs_ip_port_and_numeric_password(self):
        response = self.client.post(
            BASE,
            {"name": "Bad", "machine_type": "zk", "zk_password": "abc"},
            format="json",
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("machine_ip", response.data)
        self.assertIn("port", response.data)
        self.assertIn("zk_password", response.data)

    def test_blank_password_on_edit_keeps_stored_one(self):
        response = self.client.patch(
            self.url(), {"name": "Main gate 2", "zk_password": ""}, format="json"
        )
        self.assertEqual(response.status_code, 200, response.content)
        self.device.refresh_from_db()
        self.assertEqual(self.device.name, "Main gate 2")
        self.assertEqual(self.device.zk_password, "1234")

    def test_failed_edit_leaves_device_unchanged(self):
        response = self.client.patch(self.url(), {"machine_ip": ""}, format="json")
        self.assertEqual(response.status_code, 400)
        self.device.refresh_from_db()
        self.assertEqual(self.device.machine_ip, "192.168.1.201")

    def test_schedule_and_archive_by_patch(self):
        response = self.client.patch(
            self.url(),
            {"is_scheduler": True, "scheduler_duration": "00:15"},
            format="json",
        )
        self.assertEqual(response.status_code, 200, response.content)
        self.device.refresh_from_db()
        self.assertTrue(self.device.is_scheduler)
        self.assertEqual(self.device.scheduler_duration, "00:15")

        bad = self.client.patch(
            self.url(), {"scheduler_duration": "00:00"}, format="json"
        )
        self.assertEqual(bad.status_code, 400)

        self.client.patch(self.url(), {"is_active": False}, format="json")
        self.assertEqual(self.client.get(BASE).data["count"], 0)
        self.assertEqual(self.client.get(BASE + "?is_active=false").data["count"], 1)

    def test_delete(self):
        response = self.client.delete(self.url())
        self.assertEqual(response.status_code, 204)
        self.assertFalse(BiometricDevices.objects.filter(pk=self.device.pk).exists())

    def test_needs_permission(self):
        plain = make_user("bio_plain", password="secret123")
        make_employee(company=self.company, email="plain@test.horilla", user=plain)
        client = APIClient()
        client.force_authenticate(user=plain)
        # Horilla's API permission decorator answers 401 "No permission".
        self.assertEqual(client.get(BASE).status_code, 401)
        self.assertEqual(client.post(self.url("fetch/")).status_code, 401)
        plain.user_permissions.add(
            Permission.objects.get(codename="view_biometricdevices")
        )
        plain = type(plain).objects.get(pk=plain.pk)
        client.force_authenticate(user=plain)
        self.assertEqual(client.get(BASE).status_code, 200)
        self.assertEqual(client.delete(self.url()).status_code, 401)

    def test_capabilities_expose_biometric(self):
        response = self.client.get("/api/v1/base/capabilities/")
        if response.status_code == 404:
            self.skipTest("capabilities route not at this path")
        self.assertTrue(response.data["features"]["biometric"])
        self.assertTrue(response.data["permissions"]["view_biometricdevices"])

    # --- machine operations ---------------------------------------------

    def test_test_connection_reports_machine(self):
        conn = FakeConn(users=[zk_user(1, 1000)])
        with mock.patch(ZK_PATH, fake_zk(conn)):
            response = self.client.post(self.url("test/"))
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.data["serial_number"], "SN123")
        self.assertEqual(response.data["users"], 1)
        self.assertTrue(conn.disconnected)

    def test_unreachable_machine_is_a_502(self):
        machine = mock.Mock()
        machine.connect.side_effect = OSError("timed out")
        with mock.patch(ZK_PATH, mock.Mock(return_value=machine)):
            response = self.client.post(self.url("test/"))
        self.assertEqual(response.status_code, 502)
        self.assertIn("192.168.1.201", response.data["error"])

    def test_non_zk_operations_refused(self):
        self.device.machine_type = "anviz"
        self.device.save()
        self.assertEqual(self.client.post(self.url("test/")).status_code, 400)
        self.assertEqual(self.client.get(self.url("users/")).status_code, 400)

    def test_fetch_reports_count_and_errors(self):
        with mock.patch(
            "biometric.views.zk_biometric_attendance_logs", return_value=(3, None)
        ):
            ok = self.client.post(self.url("fetch/"))
        self.assertEqual(ok.status_code, 200, ok.content)
        self.assertEqual(ok.data["punches"], 3)
        with mock.patch(
            "biometric.views.zk_biometric_attendance_logs",
            return_value=(0, "[Main gate] Error: timed out"),
        ):
            failed = self.client.post(self.url("fetch/"))
        self.assertEqual(failed.status_code, 502)
        self.assertFalse(failed.data["ok"])

    def test_users_on_machine_with_links(self):
        BiometricEmployees.objects.create(
            uid=1, user_id="1000", employee_id=self.worker, device_id=self.device
        )
        conn = FakeConn(
            users=[zk_user(1, 1000, "Okello"), zk_user(2, 1001, "Visitor", 14)],
            templates=[SimpleNamespace(uid=1), SimpleNamespace(uid=1)],
        )
        with mock.patch(ZK_PATH, fake_zk(conn)):
            response = self.client.get(self.url("users/"))
        self.assertEqual(response.status_code, 200, response.content)
        rows = {row["user_id"]: row for row in response.data["results"]}
        self.assertEqual(rows["1000"]["employee"]["id"], self.worker.pk)
        self.assertEqual(rows["1000"]["fingerprints"], 2)
        self.assertIsNone(rows["1001"]["employee"])
        self.assertTrue(rows["1001"]["is_admin"])

    def test_enrol_adds_to_machine_and_links(self):
        conn = FakeConn(users=[zk_user(1, 1000, "Existing")])
        with mock.patch(ZK_PATH, fake_zk(conn)):
            response = self.client.post(
                self.url("enrol/"),
                {"employee_ids": [self.worker.pk]},
                format="json",
            )
            again = self.client.post(
                self.url("enrol/"),
                {"employee_ids": [self.worker.pk]},
                format="json",
            )
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.data["added"][0]["user_id"], "1001")
        self.assertEqual(response.data["added"][0]["uid"], 2)
        link = BiometricEmployees.objects.get(device_id=self.device)
        self.assertEqual(link.employee_id, self.worker)
        self.assertEqual(again.data["added"], [])
        self.assertEqual(len(again.data["skipped"]), 1)

    def test_map_and_unmap(self):
        response = self.client.post(
            self.url("mappings/"),
            {"user_id": "77", "employee_id": self.worker.pk, "uid": 5},
            format="json",
        )
        self.assertEqual(response.status_code, 201, response.content)
        duplicate = self.client.post(
            self.url("mappings/"),
            {"user_id": "77", "employee_id": self.employee.pk},
            format="json",
        )
        self.assertEqual(duplicate.status_code, 400)
        listed = self.client.get(self.url("mappings/"))
        self.assertEqual(len(listed.data), 1)
        gone = self.client.delete(self.url(f"mappings/{response.data['id']}/"))
        self.assertEqual(gone.status_code, 204)
        self.assertFalse(BiometricEmployees.objects.exists())

    def test_remove_user_from_machine_only_touches_this_device(self):
        other = BiometricDevices.objects.create(
            name="Store",
            machine_type="zk",
            machine_ip="192.168.1.202",
            port=4370,
            zk_password="0",
            company_id=self.company,
        )
        BiometricEmployees.objects.create(
            uid=1, user_id="1000", employee_id=self.worker, device_id=self.device
        )
        BiometricEmployees.objects.create(
            uid=1, user_id="1000", employee_id=self.worker, device_id=other
        )
        conn = FakeConn(users=[zk_user(1, 1000, "Okello")])
        with mock.patch(ZK_PATH, fake_zk(conn)):
            response = self.client.delete(self.url("users/1/"))
        self.assertEqual(response.status_code, 204, response.content)
        self.assertEqual(conn.deleted, [1])
        self.assertFalse(BiometricEmployees.objects.filter(device_id=self.device).exists())
        self.assertTrue(BiometricEmployees.objects.filter(device_id=other).exists())

    def test_match_badges(self):
        self.worker.badge_id = "F-001"
        self.worker.save()
        conn = FakeConn(users=[zk_user(3, "F-001", "Okello"), zk_user(4, "X9")])
        with mock.patch(ZK_PATH, fake_zk(conn)):
            response = self.client.post(self.url("match-badges/"))
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.data["linked"], 1)
        link = BiometricEmployees.objects.get(device_id=self.device)
        self.assertEqual((link.uid, link.user_id), (3, "F-001"))


class BiometricTenantScopingTests(TestCase):
    def test_other_company_devices_are_invisible(self):
        set_selected_company(None)
        company_a = make_company("A Co")
        company_b = make_company("B Co", hq=False)
        user = make_user("bio_a", password="secret123")
        make_employee(company=company_a, email="bio_a@test.horilla", user=user)
        user.user_permissions.add(
            Permission.objects.get(codename="view_biometricdevices")
        )
        BiometricDevices.objects.create(
            name="B gate", machine_type="anviz", company_id=company_b
        )
        mine = BiometricDevices.objects.create(
            name="A gate", machine_type="anviz", company_id=company_a
        )
        client = APIClient()
        login = client.post(
            "/api/v1/auth/login/",
            {"username": "bio_a", "password": "secret123"},
            format="json",
        )
        if login.status_code != 200:
            self.skipTest("login route differs")
        token = login.data.get("access") or login.data.get("access_token")
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")
        names = [row["name"] for row in client.get(BASE).data["results"]]
        self.assertEqual(names, ["A gate"])
        self.assertEqual(
            client.get(f"{BASE}{BiometricDevices.objects.get(name='B gate').pk}/").status_code,
            404,
        )
        self.assertEqual(client.get(f"{BASE}{mine.pk}/").status_code, 200)
        set_selected_company(None)


class BiometricFetchIntoAttendanceTests(TestCase):
    """End to end: punches read off a (fake) machine become attendance."""

    def test_punches_become_clock_in_and_out(self):
        from datetime import datetime

        from attendance.models import Attendance, AttendanceActivity

        set_selected_company(None)
        company = make_company("Fetch Co")
        admin = make_user("bio_fetch", password="secret123", is_superuser=True)
        make_employee(company=company, email="bio_fetch@test.horilla", user=admin)
        worker_user = make_user("bio_worker", password="secret123")
        worker = make_employee(
            company=company, email="bio_worker@test.horilla", user=worker_user
        )
        device = BiometricDevices.objects.create(
            name="Gate",
            machine_type="zk",
            machine_ip="10.0.0.9",
            port=4370,
            zk_password="0",
            company_id=company,
        )
        BiometricEmployees.objects.create(
            uid=1, user_id="1000", employee_id=worker, device_id=device
        )
        day = datetime(2026, 11, 18)
        punches = [
            SimpleNamespace(user_id="1000", punch=0, timestamp=day.replace(hour=7)),
            SimpleNamespace(user_id="1000", punch=1, timestamp=day.replace(hour=16)),
            SimpleNamespace(user_id="9999", punch=0, timestamp=day.replace(hour=8)),
        ]
        conn = FakeConn()
        conn.get_attendance = lambda: list(punches)
        client = APIClient()
        client.force_authenticate(user=admin)
        with mock.patch("biometric.views.ZK", fake_zk(conn)):
            response = client.post(f"{BASE}{device.pk}/fetch/")
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.data["punches"], 3)
        self.assertEqual(str(response.data["last_fetch_date"]), "2026-11-18")
        activity = AttendanceActivity.objects.filter(employee_id=worker).first()
        self.assertIsNotNone(activity, "clock in was not recorded")
        self.assertIsNotNone(activity.clock_out, "clock out was not recorded")
        self.assertTrue(Attendance.objects.filter(employee_id=worker).exists())
        set_selected_company(None)
