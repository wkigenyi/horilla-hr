"""
Admin one-time password reveal for React.

Mirrors employee.views.employee_reset_password_admin: generate a random
password, set it, flag is_new_employee, return it once. Never emails or
logs the password. The HTML view stays the HTMX reference UI.
"""

from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from employee.models import Employee
from horilla_auth.methods import generate_random_password


class AdminResetPasswordAPIView(APIView):
    permission_classes = [IsAuthenticated]
    http_method_names = ["post", "head", "options"]

    def post(self, request, employee_id):
        if not request.user.has_perm("employee.change_employee"):
            return Response(
                {"detail": "You do not have permission to perform this action."},
                status=403,
            )

        employee = (
            Employee.objects.select_related("employee_user_id")
            .filter(pk=employee_id)
            .first()
        )
        if employee is None:
            return Response({"detail": "Employee not found."}, status=404)

        user = employee.employee_user_id
        if user is None:
            return Response({"detail": "Employee not found."}, status=404)

        if user.pk == request.user.pk:
            return Response(
                {
                    "detail": (
                        "You can't reset your own password here — "
                        "use Change Password from your profile menu instead."
                    )
                },
                status=403,
            )

        new_password = generate_random_password()
        user.set_password(new_password)
        user.is_new_employee = True
        user.save()
        return Response({"password": new_password}, status=200)
