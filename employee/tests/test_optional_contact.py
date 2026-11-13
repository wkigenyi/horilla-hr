"""Employees can be registered with no email and no phone."""

from django.test import RequestFactory, TestCase

from base.models import EmailLog
from employee.forms import EmployeeForm
from employee.models import Employee
from horilla.testkit import make_company
from leave.threading import LeaveMailSendThread


class OptionalContactTests(TestCase):
    def test_two_employees_with_no_email_or_phone_both_save(self):
        make_company("Acme")
        saved = []
        for badge in ("B-1", "B-2"):
            employee = Employee(
                employee_first_name="John",
                employee_last_name="Doe",
                email=None,
                phone=None,
                badge_id=badge,
            )
            employee.save()
            saved.append(employee)

        self.assertEqual(Employee.objects.filter(email__isnull=True).count(), 2)
        self.assertEqual(
            [employee.employee_user_id.username for employee in saved],
            ["B-1", "B-2"],
        )
        self.assertEqual(saved[0].employee_user_id.email, "")
        self.assertIsNone(saved[0].get_mail())
        self.assertIsNone(saved[0].get_last_sent_mail())

    def test_blank_contact_is_stored_as_null_and_work_email_is_used(self):
        employee = Employee(
            employee_first_name="Amina",
            email="  ",
            phone="  ",
            badge_id="B-3",
        )
        employee.save()
        employee.refresh_from_db()
        self.assertIsNone(employee.email)
        self.assertIsNone(employee.phone)

        employee.employee_work_info.email = "work@test.horilla"
        employee.employee_work_info.save()
        self.assertEqual(employee.get_mail(), "work@test.horilla")

    def test_a_blank_form_saves_and_a_duplicate_email_is_rejected(self):
        form = EmployeeForm(
            data={
                "employee_first_name": "Amina",
                "employee_last_name": "Okello",
                "email": "",
                "phone": "",
                "badge_id": "B-4",
                "gender": "female",
            }
        )
        self.assertTrue(form.is_valid(), form.errors)
        employee = form.save()
        self.assertIsNone(employee.email)
        self.assertIsNone(employee.phone)
        self.assertEqual(employee.employee_user_id.username, "B-4")

        duplicate = EmployeeForm(
            data={
                "employee_first_name": "Other",
                "email": "amina@test.horilla",
                "phone": "5551234567",
                "badge_id": "B-5",
                "gender": "female",
            }
        )
        employee.email = "amina@test.horilla"
        employee.save()
        self.assertFalse(duplicate.is_valid())
        self.assertIn("email", duplicate.errors)

    def test_leave_mail_and_mail_log_skip_a_missing_address(self):
        employee = Employee(
            employee_first_name="No",
            employee_last_name="Mail",
            badge_id="B-7",
        )
        employee.save()
        EmailLog.objects.create(
            subject="Hello",
            body="Body",
            from_email="hr@test.horilla",
            to="someone@test.horilla",
            status="sent",
        )
        self.assertIsNone(employee.get_last_sent_mail())

        request = RequestFactory().get("/")
        LeaveMailSendThread(request, None, "request").send_email(
            "Subject", "Content", [employee]
        )
