"""
Audit trail API: who changed pay, who moved a payroll run, and who may see it.

These use real Bearer tokens rather than ``force_authenticate``. The bug they
pin is in the gap between middleware and DRF authentication: AuditlogMiddleware
reads ``request.user`` before the token is resolved, so a test that skips token
authentication would pass while every change from the app was still logged
with no actor.
"""

from datetime import date

from auditlog.models import LogEntry
from django.contrib.auth.models import Permission
from django.contrib.contenttypes.models import ContentType
from django.test import TestCase
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from horilla.horilla_middlewares import set_selected_company
from horilla.testkit import make_company, make_employee, make_user
from horilla_audit.registry import apply_audit_configuration
from payroll.models.models import Contract, PayrollBatch

ENTRIES = "/api/v1/audit/entries/"


def _bearer(client, user):
    client.credentials(
        HTTP_AUTHORIZATION=f"Bearer {RefreshToken.for_user(user).access_token}"
    )


def _grant(user, dotted):
    app_label, codename = dotted.split(".", 1)
    user.user_permissions.add(
        Permission.objects.get(content_type__app_label=app_label, codename=codename)
    )


class AuditTrailApiTests(TestCase):
    def setUp(self):
        set_selected_company(None)
        apply_audit_configuration()
        self.company = make_company("Audit Co")
        self.admin = make_user("audit_admin", password="secret123", is_superuser=True)
        self.admin_employee = make_employee(
            company=self.company,
            email="audit_admin@test.horilla",
            first_name="Amina",
            last_name="Okello",
            user=self.admin,
        )
        self.client = APIClient()
        _bearer(self.client, self.admin)

    def tearDown(self):
        set_selected_company(None)

    def _contract(self, employee=None):
        employee = employee or self.admin_employee
        return Contract.objects.filter(employee_id=employee).order_by("-id").first()

    def _change_wage(self, contract, wage, client=None):
        client = client or self.client
        current = client.get(f"/api/v1/payroll/contract/{contract.pk}")
        self.assertEqual(current.status_code, 200, current.content)
        data = {
            key: value
            for key, value in current.json().items()
            if value is not None and key != "contract_document"
        }
        data["wage"] = wage
        response = client.put(
            f"/api/v1/payroll/contract/{contract.pk}", data, format="json"
        )
        self.assertEqual(response.status_code, 200, response.content)

    def _batch(self):
        batch = PayrollBatch.objects.create(
            batch_name="November",
            period_start=date(2026, 11, 1),
            period_end=date(2026, 11, 30),
            company_id=self.company,
            created_by_user=self.admin,
        )
        return batch

    # -- the actor -------------------------------------------------------

    def test_a_wage_change_through_the_api_names_who_made_it(self):
        contract = self._contract()
        self._change_wage(contract, 2_500_000)

        entry = (
            LogEntry.objects.get_for_object(contract)
            .filter(action=LogEntry.Action.UPDATE)
            .latest("timestamp")
        )
        self.assertEqual(entry.actor_id, self.admin.pk)
        self.assertIn("wage", entry.changes)
        # The record's own version history (the profile History tab) agrees.
        self.assertEqual(contract.history.latest().history_user_id, self.admin.pk)

    # -- payroll runs ----------------------------------------------------

    def test_run_approval_is_recorded_with_the_approver(self):
        batch = self._batch()
        batch.progress_state = PayrollBatch.DONE
        batch.save(update_fields=["progress_state"])

        for status in ("review", "approved"):
            response = self.client.post(
                f"/api/v1/payroll/batches/{batch.pk}/status/",
                {"status": status},
                format="json",
            )
            self.assertEqual(response.status_code, 200, response.data)

        response = self.client.get(
            ENTRIES, {"model": "payroll.payrollbatch", "object_id": batch.pk}
        )
        self.assertEqual(response.status_code, 200, response.data)
        updates = [e for e in response.data["results"] if e["action"] == "update"]
        self.assertEqual(len(updates), 2)
        newest = updates[0]
        self.assertEqual(newest["actor"]["name"], "Amina Okello")
        self.assertEqual(newest["area"]["label"], "Payroll")
        status_change = next(c for c in newest["changes"] if c["field"] == "status")
        # Choice labels, not stored values.
        self.assertEqual(status_change["old"], "In Review")
        self.assertEqual(status_change["new"], "Approved")

    def test_generation_counters_do_not_flood_the_trail(self):
        batch = self._batch()
        before = LogEntry.objects.get_for_object(batch).count()
        for count in range(1, 4):
            batch.processed_count = count
            batch.total_net = count * 1000.0
            batch.save(update_fields=["processed_count", "total_net"])
        self.assertEqual(LogEntry.objects.get_for_object(batch).count(), before)

    # -- what the client receives ----------------------------------------

    def test_changes_are_readable_and_hide_bookkeeping(self):
        contract = self._contract()
        self._change_wage(contract, 1_800_000)

        response = self.client.get(
            ENTRIES,
            {"model": "payroll.contract", "object_id": contract.pk, "action": "update"},
        )
        self.assertEqual(response.status_code, 200, response.data)
        entry = response.data["results"][0]
        fields = {change["field"]: change for change in entry["changes"]}
        self.assertNotIn("modified_by", fields)
        self.assertEqual(fields["wage"]["kind"], "money")
        self.assertEqual(fields["wage"]["new"], 1_800_000.0)
        self.assertEqual(fields["wage"]["label"], "Basic salary")

    def test_filters_narrow_the_trail(self):
        contract = self._contract()
        self._change_wage(contract, 900_000)

        by_field = self.client.get(ENTRIES, {"field": "wage"})
        self.assertEqual(by_field.status_code, 200, by_field.data)
        self.assertTrue(by_field.data["results"])
        self.assertTrue(
            all(
                any(c["field"] == "wage" for c in e["changes"])
                for e in by_field.data["results"]
            )
        )

        nobody = self.client.get(ENTRIES, {"date_to": "2000-01-01"})
        self.assertEqual(nobody.data["count"], 0)

        bad = self.client.get(ENTRIES, {"action": "explode"})
        self.assertEqual(bad.status_code, 400)

        filters = self.client.get("/api/v1/audit/filters/")
        self.assertEqual(filters.status_code, 200, filters.data)
        self.assertIn(
            "payroll.contract", [item["value"] for item in filters.data["record_types"]]
        )
        self.assertIn(self.admin.pk, [p["id"] for p in filters.data["people"]])

    def test_routine_recalculations_can_be_left_out(self):
        work = self.admin_employee.employee_work_info
        content_type = ContentType.objects.get_for_model(work)

        def logged(changes, actor=None):
            return LogEntry.objects.create(
                content_type=content_type,
                object_pk=str(work.pk),
                object_id=work.pk,
                object_repr=str(work),
                action=LogEntry.Action.UPDATE,
                changes=changes,
                actor=actor,
            ).pk

        # The experience job: a system save that only moved experience.
        job = logged({"experience": ["4.249", "4.252"], "modified_at": ["a", "b"]})
        # A system save that also changed a real field still matters.
        mixed = logged({"experience": ["4.2", "4.3"], "shift_id": ["1", "2"]})
        # So does a person touching experience by hand.
        person = logged({"experience": ["1.0", "2.0"]}, actor=self.admin)

        query = {"model": "employee.employeeworkinformation", "object_id": work.pk}
        everything = self.client.get(ENTRIES, query)
        self.assertEqual(everything.status_code, 200, everything.data)
        shown = {entry["id"] for entry in everything.data["results"]}
        self.assertTrue({job, mixed, person} <= shown)

        hidden = self.client.get(ENTRIES, {**query, "routine": "hide"})
        self.assertEqual(hidden.status_code, 200, hidden.data)
        shown = {entry["id"] for entry in hidden.data["results"]}
        self.assertNotIn(job, shown)
        self.assertTrue({mixed, person} <= shown)

    # -- who may see it --------------------------------------------------

    def test_the_trail_needs_the_audit_permission(self):
        clerk = make_user("audit_clerk", password="secret123")
        make_employee(company=self.company, email="clerk@test.horilla", user=clerk)
        client = APIClient()
        _bearer(client, clerk)

        self.assertEqual(client.get(ENTRIES).status_code, 403)
        self.assertEqual(client.get("/api/v1/audit/filters/").status_code, 403)

        _grant(clerk, "auditlog.view_logentry")
        self.assertEqual(client.get(ENTRIES).status_code, 200)

    def test_a_record_history_needs_only_view_access_to_that_record(self):
        contract = self._contract()
        self._change_wage(contract, 700_000)
        officer = make_user("audit_officer", password="secret123")
        make_employee(company=self.company, email="officer@test.horilla", user=officer)
        client = APIClient()
        _bearer(client, officer)
        params = {"model": "payroll.contract", "object_id": contract.pk}

        self.assertEqual(client.get(ENTRIES, params).status_code, 403)
        _grant(officer, "payroll.view_contract")
        response = client.get(ENTRIES, params)
        self.assertEqual(response.status_code, 200, response.data)
        self.assertTrue(response.data["results"])
        # ...but not the whole trail.
        self.assertEqual(client.get(ENTRIES).status_code, 403)

    def test_a_run_history_opens_with_payslip_access(self):
        # Runs are opened with "view payslip", so their history is too.
        batch = self._batch()
        officer = make_user("run_officer", password="secret123")
        make_employee(company=self.company, email="run@test.horilla", user=officer)
        _grant(officer, "payroll.view_payslip")
        client = APIClient()
        _bearer(client, officer)
        response = client.get(
            ENTRIES, {"model": "payroll.payrollbatch", "object_id": batch.pk}
        )
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["results"][0]["action"], "create")

    def test_another_companys_changes_stay_out_of_view(self):
        contract = self._contract()
        self._change_wage(contract, 650_000)
        other = make_company("Other Co", hq=False)
        auditor = make_user("other_auditor", password="secret123")
        make_employee(company=other, email="auditor@other.horilla", user=auditor)
        _grant(auditor, "auditlog.view_logentry")
        client = APIClient()
        _bearer(client, auditor)

        response = client.get(ENTRIES, {"model": "payroll.contract"})
        self.assertEqual(response.status_code, 200, response.data)
        self.assertNotIn(
            contract.pk, [entry["object_id"] for entry in response.data["results"]]
        )

    def test_the_permission_is_grantable_and_advertised(self):
        capabilities = self.client.get("/api/v1/base/capabilities/")
        self.assertEqual(capabilities.status_code, 200)
        self.assertTrue(capabilities.data["permissions"]["view_audit_trail"])

        from horilla_api.api_views.base.roles import permission_catalog

        ids = [
            action["id"]
            for app in permission_catalog()
            for model in app["models"]
            for action in model["actions"]
        ]
        self.assertIn("auditlog.view_logentry", ids)

    def test_unknown_record_type_is_refused(self):
        response = self.client.get(ENTRIES, {"model": "payroll.nothing"})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            ContentType.objects.filter(app_label="payroll", model="nothing").count(), 0
        )
