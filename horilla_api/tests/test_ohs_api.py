"""OHS v1 API: workplaces, events, notifications, register, dashboard."""

from datetime import date, timedelta

from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from horilla.horilla_middlewares import set_selected_company
from horilla.testkit import make_company, make_employee, make_user
from ohs.models import OshCorrectiveAction, OshEvent, OshNotification, OshWorkplace


class OhsApiTests(TestCase):
    def setUp(self):
        set_selected_company(None)
        self.client = APIClient()
        self.company = make_company("OSH Co")
        self.user = make_user("ohs_api", password="secret123", is_superuser=True)
        self.employee = make_employee(
            company=self.company,
            email="ohs_api@test.horilla",
            first_name="Sam",
            user=self.user,
        )
        self.client.force_authenticate(user=self.user)
        self.workplace = OshWorkplace.objects.create(
            name="Kampala Plant",
            company_id=self.company,
            jurisdiction="UG",
            registration_number="OSH-UG-001",
            registered_on=date(2024, 1, 15),
            expires_on=date(2027, 1, 15),
            labour_officer_area="Kampala",
        )

    def tearDown(self):
        set_selected_company(None)

    def test_workplace_list(self):
        response = self.client.get("/api/v1/ohs/workplaces/")
        self.assertEqual(response.status_code, 200, response.content)
        self.assertGreaterEqual(response.data["count"], 1)

    def test_create_event_and_notification(self):
        occurred = timezone.now() - timedelta(hours=2)
        create = self.client.post(
            "/api/v1/ohs/events/",
            {
                "workplace": self.workplace.id,
                "event_type": "accident",
                "title": "Slip on wet floor",
                "description": "Worker slipped near loading bay.",
                "occurred_at": occurred.isoformat(),
                "employee": self.employee.id,
                "reported_by": self.employee.id,
                "severity": "medium",
                "injury_occurred": True,
                "compensable": True,
            },
            format="json",
        )
        self.assertEqual(create.status_code, 201, create.content)
        event_id = create.data["id"]

        notify = self.client.post(
            "/api/v1/ohs/notifications/",
            {
                "event": event_id,
                "channel": "phone",
                "notified_at": timezone.now().isoformat(),
                "written_report_at": timezone.now().isoformat(),
                "authority_name": "Labour Officer Kampala",
                "area": "Kampala",
                "reference": "LO-2026-1",
            },
            format="json",
        )
        self.assertEqual(notify.status_code, 201, notify.content)
        self.assertEqual(OshNotification.objects.filter(event_id=event_id).count(), 1)

        register = self.client.get(
            f"/api/v1/ohs/general-register/?workplace={self.workplace.id}"
        )
        self.assertEqual(register.status_code, 200, register.content)
        self.assertGreaterEqual(register.data["count"], 1)

    def test_capa_and_dashboard(self):
        event = OshEvent.objects.create(
            workplace=self.workplace,
            event_type="near_miss",
            title="Unsecured scaffolding",
            description="Near miss observed.",
            occurred_at=timezone.now(),
            compensable=False,
        )
        OshCorrectiveAction.objects.create(
            event=event,
            title="Secure scaffolding",
            owner=self.employee,
            due_on=date.today() - timedelta(days=1),
            status="open",
        )
        summary = self.client.get("/api/v1/ohs/dashboard/summary/")
        self.assertEqual(summary.status_code, 200, summary.content)
        self.assertGreaterEqual(summary.data["open_events"], 1)
        self.assertGreaterEqual(summary.data["overdue_corrective_actions"], 1)

    def test_permission_denied_without_access(self):
        outsider = make_user("ohs_outsider", password="secret123")
        make_employee(
            company=self.company,
            email="ohs_outsider@test.horilla",
            user=outsider,
        )
        self.client.force_authenticate(user=outsider)
        response = self.client.get("/api/v1/ohs/events/")
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.data.get("message"), "No permission")
