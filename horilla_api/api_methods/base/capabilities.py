"""
One payload describing what a client may show the signed-in user.

Two problems this solves, both from building a mobile client against this API.

**Role and permissions.** The app's navigation is role-adaptive -- which tabs
exist, which band shows on the home screen -- and the only tool for that was
``GET /base/check-user-level?perm=<one perm>``, which answers for a single
permission at a time. Deciding a five-tab bar meant a dozen round trips before
the first screen painted. This returns the whole set once.

**Feature detection.** A client cannot discover whether an optional feature is
available by probing its endpoint: DRF answers 404 both for "no such route"
and "no such object", and 403 for "not allowed", so the three cases are
indistinguishable, and probing costs speculative requests on every cold start.
``features`` states it explicitly instead.

These are **UI hints, not authorization**. Every endpoint still enforces its
own permissions; a client that lies to itself about ``role`` gets 403s, not
access. Nothing here may be used as the basis for a security decision.

``permissions`` is a fixed allow-list: every key is always present as a
boolean. Clients that require ``true`` must not treat a missing key as
allowed.
"""

from django.apps import apps

from base.methods import is_reportingmanager
from horilla.__version__ import __version__

# Optional apps the mobile client hides features for when absent. Each maps to
# the app label; ``apps.is_installed`` is the whole check. Note that geofencing
# and facedetection are installed from horilla_api/__init__.py rather than
# settings, so a settings grep will wrongly suggest they are missing.
OPTIONAL_APPS = (
    "asset",
    "attendance",
    "facedetection",
    "geofencing",
    "helpdesk",
    "leave",
    "offboarding",
    "payroll",
    "pms",
    "project",
    "recruitment",
)

# Short key (no app_label) → Django permission. Superusers receive True from
# has_perm. edit_own_profile is a feature flag and is not in this map.
_PERMISSIONS = (
    ("approve_leave", "leave.change_leaverequest"),
    ("approve_attendance", "attendance.change_attendance"),
    ("approve_shift_request", "base.change_shiftrequest"),
    ("view_employee", "employee.view_employee"),
    ("edit_employee", "employee.change_employee"),
    ("view_payslip", "payroll.view_payslip"),
    ("change_payslip", "payroll.change_payslip"),
    ("add_payslip", "payroll.add_payslip"),
    ("delete_payslip", "payroll.delete_payslip"),
    ("view_contract", "payroll.view_contract"),
    ("add_contract", "payroll.add_contract"),
    ("change_contract", "payroll.change_contract"),
    ("view_loanaccount", "payroll.view_loanaccount"),
    ("change_loanaccount", "payroll.change_loanaccount"),
    ("add_loanaccount", "payroll.add_loanaccount"),
    ("view_payadjustment", "payroll.view_payadjustment"),
    ("add_payadjustment", "payroll.add_payadjustment"),
    ("change_payadjustment", "payroll.change_payadjustment"),
    ("delete_payadjustment", "payroll.delete_payadjustment"),
    ("view_reimbursement", "payroll.view_reimbursement"),
    ("add_reimbursement", "payroll.add_reimbursement"),
    ("change_reimbursement", "payroll.change_reimbursement"),
    ("view_filingstatus", "payroll.view_filingstatus"),
    ("add_filingstatus", "payroll.add_filingstatus"),
    ("change_filingstatus", "payroll.change_filingstatus"),
    ("delete_filingstatus", "payroll.delete_filingstatus"),
    ("view_taxbracket", "payroll.view_taxbracket"),
    ("add_taxbracket", "payroll.add_taxbracket"),
    ("change_taxbracket", "payroll.change_taxbracket"),
    ("delete_taxbracket", "payroll.delete_taxbracket"),
    ("view_salarystructure", "payroll.view_salarystructure"),
    ("add_salarystructure", "payroll.add_salarystructure"),
    ("change_salarystructure", "payroll.change_salarystructure"),
    ("delete_salarystructure", "payroll.delete_salarystructure"),
    ("view_allowance", "payroll.view_allowance"),
    ("add_allowance", "payroll.add_allowance"),
    ("change_allowance", "payroll.change_allowance"),
    ("delete_allowance", "payroll.delete_allowance"),
    ("view_deduction", "payroll.view_deduction"),
    ("add_deduction", "payroll.add_deduction"),
    ("change_deduction", "payroll.change_deduction"),
    ("delete_deduction", "payroll.delete_deduction"),
    ("view_payrollsettings", "payroll.view_payrollsettings"),
    ("change_payrollsettings", "payroll.change_payrollsettings"),
    ("change_encashmentgeneralsettings", "payroll.change_encashmentgeneralsettings"),
    ("view_project", "project.view_project"),
    ("add_project", "project.add_project"),
    ("change_project", "project.change_project"),
    ("delete_project", "project.delete_project"),
    ("view_task", "project.view_task"),
    ("add_task", "project.add_task"),
    ("change_task", "project.change_task"),
    ("delete_task", "project.delete_task"),
    ("view_timesheet", "project.view_timesheet"),
    ("add_timesheet", "project.add_timesheet"),
    ("change_timesheet", "project.change_timesheet"),
    ("delete_timesheet", "project.delete_timesheet"),
    ("add_projectstage", "project.add_projectstage"),
)


def _resolve_role(user):
    """
    Collapse permissions into the single role the design's layouts key off.

    Deliberately coarse and ordered most-privileged first, because the design
    shows one band per user, not a union. A client rendering the HR-executive
    band has no business also rendering the manager band.

    ``newhire`` is absent on purpose: the design's onboarding screen wants a
    task checklist for an *Employee*, and the onboarding app is entirely
    Candidate-scoped, so there is nothing to resolve it from yet. Adding it
    later is additive and needs no client change to the other roles.
    """
    if user.is_superuser or user.has_perm("employee.change_employee"):
        return "hrexec"
    if is_reportingmanager(_FakeRequest(user)):
        return "manager"
    return "employee"


class _FakeRequest:
    """``is_reportingmanager`` takes a request; this carries the one attribute
    it reads, so the check stays shared with the web path rather than forked."""

    def __init__(self, user):
        self.user = user


def build_capabilities(user):
    """Return the capability payload for ``user``."""
    profile_edit = apps.get_model("employee", "ProfileEditFeature")
    edit_own_profile = profile_edit.objects.filter(is_enabled=True).exists()
    permissions = {key: user.has_perm(perm) for key, perm in _PERMISSIONS}
    permissions["view_team"] = is_reportingmanager(_FakeRequest(user))
    permissions["edit_own_profile"] = edit_own_profile
    permissions["manage_roles"] = user.is_superuser
    permissions["can_switch_company"] = user.is_superuser

    return {
        "version": __version__,
        "role": _resolve_role(user),
        "permissions": permissions,
        "features": {label: apps.is_installed(label) for label in OPTIONAL_APPS},
    }
