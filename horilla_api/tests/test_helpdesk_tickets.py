"""Helpdesk ticket JWT API: CRUD, status, archive, comments, attachments, claims."""

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from rest_framework.test import APIClient

from base.models import Department, Tags
from helpdesk.models import ClaimRequest, Comment, Ticket, TicketType
from horilla.horilla_middlewares import set_selected_company
from horilla.testkit import make_company, make_employee, make_user

ROOT = "/api/v1/helpdesk/"


class HelpdeskTicketApiTests(TestCase):
    def setUp(self):
        set_selected_company(None)
        self.client = APIClient()
        self.company = make_company("Ticket API Co")
        self.user = make_user("ticket_api", password="secret123", is_superuser=True)
        self.employee = make_employee(
            company=self.company,
            email="ticket_api@test.horilla",
            first_name="Terry",
            user=self.user,
        )
        self.claimant_user = make_user("ticket_claimant", password="secret123")
        self.claimant = make_employee(
            company=self.company,
            email="ticket_claimant@test.horilla",
            first_name="Casey",
            user=self.claimant_user,
        )
        self.department = Department.objects.create(department="Support")
        self.department.company_id.add(self.company)
        self.ticket_type = TicketType.objects.create(
            title="IT Support",
            type="service_request",
            prefix="ITS",
            company_id=self.company,
        )
        self.client.force_authenticate(user=self.user)

    def tearDown(self):
        set_selected_company(None)

    def _create_ticket(self, **overrides):
        payload = {
            "title": "Laptop will not boot",
            "description": "Dead on power-on.",
            "ticket_type_id": self.ticket_type.id,
            "priority": "medium",
            "assigning_type": "department",
            "raised_on": str(self.department.id),
            "employee_id_write": self.employee.id,
        }
        payload.update(overrides)
        response = self.client.post(f"{ROOT}ticket/", payload, format="json")
        self.assertEqual(response.status_code, 201, response.content)
        return response

    def test_requires_authentication(self):
        self.assertEqual(APIClient().get(f"{ROOT}ticket/").status_code, 401)

    def test_list_create_detail_update(self):
        created = self._create_ticket()
        ticket_id = created.data["id"]
        self.assertEqual(created.data["status"], "new")
        self.assertEqual(created.data["title"], "Laptop will not boot")

        tag = Tags.objects.create(title="Urgent", color="#ef4444", company_id=self.company)
        ticket = Ticket.objects.get(pk=ticket_id)
        ticket.tags.add(tag)

        listing = self.client.get(f"{ROOT}ticket/?page=1&page_size=100")
        self.assertEqual(listing.status_code, 200, listing.content)
        self.assertGreaterEqual(listing.data["count"], 1)
        listed = next(row for row in listing.data["results"] if row["id"] == ticket_id)
        self.assertEqual(
            listed["tags"],
            [{"id": tag.id, "title": "Urgent", "color": "#ef4444"}],
        )

        detail = self.client.get(f"{ROOT}ticket/{ticket_id}/")
        self.assertEqual(detail.status_code, 200, detail.content)
        self.assertEqual(detail.data["id"], ticket_id)
        self.assertIn("comments", detail.data)
        self.assertIn("attachments", detail.data)
        self.assertEqual(
            detail.data["tags"],
            [{"id": tag.id, "title": "Urgent", "color": "#ef4444"}],
        )

        update = self.client.put(
            f"{ROOT}ticket/{ticket_id}/",
            {"title": "Laptop still will not boot", "priority": "high"},
            format="json",
        )
        self.assertEqual(update.status_code, 200, update.content)
        self.assertEqual(update.data["title"], "Laptop still will not boot")
        self.assertEqual(update.data["priority"], "high")
        # Status stays read-only on the ticket body.
        self.assertEqual(update.data["status"], "new")

    def test_change_status_and_archive(self):
        ticket_id = self._create_ticket().data["id"]

        status_resp = self.client.put(
            f"{ROOT}ticket/{ticket_id}/status/",
            {"status": "in_progress"},
            format="json",
        )
        self.assertEqual(status_resp.status_code, 200, status_resp.content)
        self.assertEqual(status_resp.data["status"], "in_progress")

        resolved = self.client.put(
            f"{ROOT}ticket/{ticket_id}/status/",
            {"status": "resolved"},
            format="json",
        )
        self.assertEqual(resolved.status_code, 200, resolved.content)
        self.assertEqual(resolved.data["status"], "resolved")
        self.assertIsNotNone(resolved.data["resolved_date"])

        archive = self.client.put(f"{ROOT}ticket/{ticket_id}/archive/", {}, format="json")
        self.assertEqual(archive.status_code, 200, archive.content)
        self.assertFalse(archive.data["is_active"])
        self.assertFalse(Ticket.objects.get(pk=ticket_id).is_active)

    def test_comment_on_ticket(self):
        ticket_id = self._create_ticket().data["id"]

        create = self.client.post(
            f"{ROOT}ticket/{ticket_id}/comment/",
            {"comment": "Tried a hard reset."},
            format="json",
        )
        self.assertEqual(create.status_code, 201, create.content)
        comment_id = create.data["id"]
        self.assertEqual(create.data["comment"], "Tried a hard reset.")
        self.assertEqual(Comment.objects.filter(ticket_id=ticket_id).count(), 1)

        listing = self.client.get(f"{ROOT}ticket/{ticket_id}/comment/")
        self.assertEqual(listing.status_code, 200, listing.content)
        self.assertGreaterEqual(listing.data["count"], 1)

        detail = self.client.get(f"{ROOT}ticket/{ticket_id}/")
        self.assertEqual(detail.status_code, 200, detail.content)
        self.assertEqual(len(detail.data["comments"]), 1)

        update = self.client.put(
            f"{ROOT}comment/{comment_id}/",
            {"comment": "Hard reset failed."},
            format="json",
        )
        self.assertEqual(update.status_code, 200, update.content)
        self.assertEqual(update.data["comment"], "Hard reset failed.")

    def test_attachment_binds_ticket_from_url(self):
        ticket_id = self._create_ticket().data["id"]
        upload = SimpleUploadedFile(
            "note.txt", b"power LED stays dark", content_type="text/plain"
        )

        create = self.client.post(
            f"{ROOT}ticket/{ticket_id}/attachment/",
            {"file": upload, "description": "Boot note"},
            format="multipart",
        )
        self.assertEqual(create.status_code, 201, create.content)
        attachment_id = create.data["id"]
        self.assertEqual(create.data["description"], "Boot note")

        listing = self.client.get(f"{ROOT}ticket/{ticket_id}/attachment/")
        self.assertEqual(listing.status_code, 200, listing.content)
        self.assertGreaterEqual(listing.data["count"], 1)

        detail = self.client.get(f"{ROOT}ticket/{ticket_id}/")
        self.assertEqual(detail.status_code, 200, detail.content)
        self.assertEqual(len(detail.data["attachments"]), 1)

        delete = self.client.delete(f"{ROOT}attachment/{attachment_id}/")
        self.assertEqual(delete.status_code, 204, delete.content)

    def test_claim_request_approve_and_reject(self):
        ticket_id = self._create_ticket().data["id"]

        # Claimant creates via the ticket-scoped URL (ticket_id from path).
        claim_client = APIClient()
        claim_client.force_authenticate(user=self.claimant_user)
        create = claim_client.post(
            f"{ROOT}ticket/{ticket_id}/claim-request/",
            {},
            format="json",
        )
        self.assertEqual(create.status_code, 201, create.content)
        claim_id = create.data["id"]
        self.assertFalse(create.data["is_approved"])
        self.assertFalse(create.data["is_rejected"])

        approve = self.client.put(
            f"{ROOT}claim-request/{claim_id}/approve/", {}, format="json"
        )
        self.assertEqual(approve.status_code, 200, approve.content)
        self.assertTrue(approve.data["is_approved"])
        ticket = Ticket.objects.get(pk=ticket_id)
        self.assertIn(self.claimant, ticket.assigned_to.all())

        # Second claim by another path: create then reject.
        other_user = make_user("ticket_claimant2", password="secret123")
        other = make_employee(
            company=self.company,
            email="ticket_claimant2@test.horilla",
            first_name="Riley",
            user=other_user,
        )
        other_claim = ClaimRequest.objects.create(ticket_id=ticket, employee_id=other)
        reject = self.client.put(
            f"{ROOT}claim-request/{other_claim.id}/reject/", {}, format="json"
        )
        self.assertEqual(reject.status_code, 200, reject.content)
        self.assertTrue(reject.data["is_rejected"])
        self.assertFalse(reject.data["is_approved"])
        self.assertNotIn(other, ticket.assigned_to.all())
