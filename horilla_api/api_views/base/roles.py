"""
Roles and direct employee permissions.

Roles are Django auth groups. Direct permissions are the user's own
``user_permissions``, separate from anything a role grants. A person's own
roles, and anyone who can view employees, can read the role names. Changing
roles or direct permissions stays superuser-only. The web settings page at
``/settings/user-group-view/`` is the same data.
"""

from django.conf import settings
from django.contrib.auth.models import Group, Permission
from django.db.models import Count, Q
from rest_framework.permissions import BasePermission, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from base.auth_backends import company_scoped_active
from base.models import CompanyGroupAssignment
from base.views import (
    _custom_permission_label,
    _permission_app_label,
    get_models_in_app,
)
from employee.models import Employee

ACTIONS = ("add", "view", "change", "delete")
ACTION_LABELS = {
    "add": "Create",
    "view": "View",
    "change": "Edit",
    "delete": "Delete",
}


class SuperuserOnly(BasePermission):
    def has_permission(self, request, view):
        user = request.user
        return bool(user and user.is_authenticated and user.is_superuser)


def _permission_id(app_label, codename):
    return f"{app_label}.{codename}"


def _permissions_from_ids(raw):
    if not isinstance(raw, list):
        return None
    found = []
    for item in raw:
        if not isinstance(item, str) or "." not in item:
            return None
        app_label, codename = item.split(".", 1)
        perm = Permission.objects.filter(
            content_type__app_label=app_label, codename=codename
        ).first()
        if perm is None:
            return None
        found.append(perm)
    return found


def permission_catalog():
    skipped = set(getattr(settings, "NO_PERMISSION_MODALS", []))
    apps_out = []
    for app_name in getattr(settings, "APPS", []):
        models_out = []
        for model in get_models_in_app(app_name):
            model_name = model._meta.model_name
            if model_name in skipped:
                continue
            content_type = model._meta.app_label
            existing = set(
                Permission.objects.filter(
                    content_type__app_label=content_type,
                    content_type__model=model_name,
                ).values_list("codename", flat=True)
            )
            actions = [
                {
                    "id": _permission_id(content_type, f"{action}_{model_name}"),
                    "action": action,
                    "label": ACTION_LABELS[action],
                }
                for action in ACTIONS
                if f"{action}_{model_name}" in existing
            ]
            custom = []
            for codename, name in model._meta.permissions or ():
                if codename not in existing:
                    continue
                custom.append(
                    {
                        "id": _permission_id(content_type, codename),
                        "label": _custom_permission_label(
                            name, model._meta.verbose_name
                        ),
                    }
                )
            if not actions and not custom:
                continue
            models_out.append(
                {
                    "name": str(model._meta.verbose_name).capitalize(),
                    "actions": actions,
                    "custom": custom,
                }
            )
        if models_out:
            apps_out.append(
                {"app": _permission_app_label(app_name), "models": models_out}
            )
    return apps_out


def _assigned_ids(queryset):
    return [
        _permission_id(perm.content_type.app_label, perm.codename)
        for perm in queryset.select_related("content_type")
    ]


def _role_summary(group, grants=None):
    summary = {
        "id": group.id,
        "name": group.name,
        "members": group.member_count,
        "permissions": group.perm_count,
    }
    if grants is not None:
        summary["grants"] = grants
    return summary


def _grant_ids(group):
    return [
        _permission_id(perm.content_type.app_label, perm.codename)
        for perm in group.permissions.all()
    ]


def _roles_queryset():
    return Group.objects.annotate(
        member_count=Count("user", distinct=True),
        perm_count=Count("permissions", distinct=True),
    ).order_by("name")


def _employee_for_user(user):
    return (
        Employee.objects.filter(employee_user_id=user)
        .only("id", "employee_first_name", "employee_last_name")
        .first()
    )


def _members(group):
    if company_scoped_active():
        rows = (
            CompanyGroupAssignment.objects.filter(group=group)
            .select_related("user", "company")
            .order_by("user_id", "company__company")
        )
        grouped = {}
        for row in rows:
            entry = grouped.setdefault(
                row.user_id,
                {"user": row.user, "companies": []},
            )
            entry["companies"].append(row.company.company)
        people = []
        for entry in grouped.values():
            employee = _employee_for_user(entry["user"])
            if employee is None:
                continue
            people.append(
                {
                    "id": employee.id,
                    "name": employee.get_full_name(),
                    "companies": entry["companies"],
                }
            )
        people.sort(key=lambda person: person["name"].lower())
        return people

    people = []
    for user in group.user_set.all().order_by("username"):
        employee = _employee_for_user(user)
        if employee is None:
            continue
        people.append(
            {"id": employee.id, "name": employee.get_full_name(), "companies": []}
        )
    people.sort(key=lambda person: person["name"].lower())
    return people


def _active_employee(employee_id):
    return (
        Employee.objects.filter(pk=employee_id, is_active=True)
        .select_related("employee_user_id", "employee_work_info", "employee_work_info__company_id")
        .first()
    )


def _may_view_employee_access(request, employee):
    """Role names are visible to the person, to anyone who can view employees,
    and to a superuser. Changing them stays superuser-only."""
    user = request.user
    if not user.is_authenticated:
        return False
    if user.is_superuser or user.has_perm("employee.view_employee"):
        return True
    return getattr(employee, "employee_user_id_id", None) == user.pk


def _employee_roles(user):
    return [
        {"id": group.id, "name": group.name}
        for group in user.groups.all().order_by("name")
    ]


class RoleListAPIView(APIView):
    permission_classes = [IsAuthenticated, SuperuserOnly]

    def get(self, request):
        groups = _roles_queryset().prefetch_related("permissions__content_type")
        return Response(
            {
                "roles": [
                    _role_summary(group, _grant_ids(group)) for group in groups
                ],
                "catalog": permission_catalog(),
            }
        )

    def post(self, request):
        name = str(request.data.get("name") or "").strip()
        if len(name) < 2 or len(name) > 150:
            return Response(
                {"name": "Enter a role name between 2 and 150 characters."},
                status=400,
            )
        if Group.objects.filter(name__iexact=name).exists():
            return Response({"name": "A role with this name already exists."}, status=400)
        group = Group.objects.create(name=name)
        group.member_count = 0
        group.perm_count = 0
        return Response(_role_summary(group, []), status=201)


class RoleDetailAPIView(APIView):
    permission_classes = [IsAuthenticated, SuperuserOnly]

    def get(self, request, pk):
        group = Group.objects.filter(pk=pk).first()
        if group is None:
            return Response({"detail": "Role not found."}, status=404)
        return Response(
            {
                "id": group.id,
                "name": group.name,
                "permissions": _assigned_ids(group.permissions.all()),
                "members": _members(group),
            }
        )

    def patch(self, request, pk):
        group = Group.objects.filter(pk=pk).first()
        if group is None:
            return Response({"detail": "Role not found."}, status=404)
        if "name" in request.data:
            name = str(request.data.get("name") or "").strip()
            if len(name) < 2 or len(name) > 150:
                return Response(
                    {"name": "Enter a role name between 2 and 150 characters."},
                    status=400,
                )
            if Group.objects.filter(name__iexact=name).exclude(pk=group.pk).exists():
                return Response(
                    {"name": "A role with this name already exists."}, status=400
                )
            group.name = name
            group.save(update_fields=["name"])
        if "permissions" in request.data:
            perms = _permissions_from_ids(request.data.get("permissions"))
            if perms is None:
                return Response(
                    {"permissions": "Choose permissions from the list."}, status=400
                )
            group.permissions.set(perms)
        return self.get(request, pk)

    def delete(self, request, pk):
        group = Group.objects.filter(pk=pk).first()
        if group is None:
            return Response({"detail": "Role not found."}, status=404)
        group.delete()
        return Response(status=204)


class RoleMemberAPIView(APIView):
    permission_classes = [IsAuthenticated, SuperuserOnly]

    def post(self, request, pk):
        group = Group.objects.filter(pk=pk).first()
        if group is None:
            return Response({"detail": "Role not found."}, status=404)
        employee = _active_employee(request.data.get("employee_id"))
        user = getattr(employee, "employee_user_id", None) if employee else None
        if employee is None or user is None:
            return Response(
                {"employee_id": "Choose an employee who can sign in."}, status=400
            )
        if company_scoped_active():
            company = getattr(
                getattr(employee, "employee_work_info", None), "company_id", None
            )
            if company is None:
                return Response(
                    {"employee_id": "This employee has no company."}, status=400
                )
            CompanyGroupAssignment.objects.get_or_create(
                user=user, group=group, company=company
            )
            CompanyGroupAssignment.sync_user_group_membership(user, group)
        else:
            user.groups.add(group)
        return RoleDetailAPIView().get(request, pk)

    def delete(self, request, pk, employee_id):
        group = Group.objects.filter(pk=pk).first()
        employee = _active_employee(employee_id)
        user = getattr(employee, "employee_user_id", None) if employee else None
        if group is None or user is None:
            return Response({"detail": "Role member not found."}, status=404)
        if company_scoped_active():
            CompanyGroupAssignment.objects.filter(user=user, group=group).delete()
            CompanyGroupAssignment.sync_user_group_membership(user, group)
        else:
            user.groups.remove(group)
        return RoleDetailAPIView().get(request, pk)


class RolePeopleAPIView(APIView):
    permission_classes = [IsAuthenticated, SuperuserOnly]

    def get(self, request):
        query = str(request.GET.get("q") or "").strip()
        people = Employee.objects.filter(is_active=True, employee_user_id__isnull=False)
        if query:
            people = people.filter(
                Q(employee_first_name__icontains=query)
                | Q(employee_last_name__icontains=query)
                | Q(badge_id__icontains=query)
            )
        people = people.only(
            "id", "employee_first_name", "employee_last_name", "badge_id"
        ).order_by("employee_first_name", "employee_last_name")[:20]
        return Response(
            {
                "people": [
                    {"id": person.id, "name": person.get_full_name()}
                    for person in people
                ]
            }
        )


class EmployeePermissionsAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, employee_id):
        employee = _active_employee(employee_id)
        user = getattr(employee, "employee_user_id", None) if employee else None
        if user is None:
            return Response({"detail": "Employee not found."}, status=404)
        if not _may_view_employee_access(request, employee):
            return Response(
                {"detail": "You do not have permission to view this."}, status=403
            )
        return Response(
            {
                "id": employee.id,
                "name": employee.get_full_name(),
                "roles": _employee_roles(user),
                "permissions": (
                    _assigned_ids(user.user_permissions.all())
                    if request.user.is_superuser
                    else []
                ),
            }
        )

    def put(self, request, employee_id):
        if not request.user.is_superuser:
            return Response(
                {"detail": "You do not have permission to change this."}, status=403
            )
        employee = _active_employee(employee_id)
        user = getattr(employee, "employee_user_id", None) if employee else None
        if user is None:
            return Response({"detail": "Employee not found."}, status=404)
        perms = _permissions_from_ids(request.data.get("permissions"))
        if perms is None:
            return Response(
                {"permissions": "Choose permissions from the list."}, status=400
            )
        user.user_permissions.set(perms)
        return self.get(request, employee_id)
