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
    "biometric",
    "facedetection",
    "geofencing",
    "helpdesk",
    "leave",
    "offboarding",
    "ohs",
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
    # The audit trail screen (who changed what and when).
    ("view_audit_trail", "auditlog.view_logentry"),
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
    # Pay period schedule/automation. PayPeriodView still checks these
    # PayslipAutoGenerate codenames (model rename is out of scope).
    ("view_payslipautogenerate", "payroll.view_payslipautogenerate"),
    ("change_payslipautogenerate", "payroll.change_payslipautogenerate"),
    ("delete_payslipautogenerate", "payroll.delete_payslipautogenerate"),
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
    # Leave
    ("view_leaverequest", "leave.view_leaverequest"),
    ("add_leaverequest", "leave.add_leaverequest"),
    ("change_leaverequest", "leave.change_leaverequest"),
    ("delete_leaverequest", "leave.delete_leaverequest"),
    ("view_leaveallocationrequest", "leave.view_leaveallocationrequest"),
    ("change_leaveallocationrequest", "leave.change_leaveallocationrequest"),
    ("view_leavetype", "leave.view_leavetype"),
    ("add_leavetype", "leave.add_leavetype"),
    ("change_leavetype", "leave.change_leavetype"),
    ("delete_leavetype", "leave.delete_leavetype"),
    ("view_availableleave", "leave.view_availableleave"),
    ("change_availableleave", "leave.change_availableleave"),
    ("view_holidays", "base.view_holidays"),
    ("add_holidays", "base.add_holidays"),
    ("change_holidays", "base.change_holidays"),
    ("delete_holidays", "base.delete_holidays"),
    # CompanyLeaves lives in base; key stays add_companyleave (singular) as the UI contract.
    # The leave API decorator leave.add_companyleave is not a real Permission row.
    ("view_companyleaves", "base.view_companyleaves"),
    ("add_companyleave", "base.add_companyleaves"),
    ("change_companyleaves", "base.change_companyleaves"),
    ("delete_companyleaves", "base.delete_companyleaves"),
    # Attendance
    ("view_attendance", "attendance.view_attendance"),
    ("add_attendance", "attendance.add_attendance"),
    ("change_attendance", "attendance.change_attendance"),
    ("delete_attendance", "attendance.delete_attendance"),
    ("view_attendanceovertime", "attendance.view_attendanceovertime"),
    ("change_attendanceovertime", "attendance.change_attendanceovertime"),
    ("view_attendancelatecomeearlyout", "attendance.view_attendancelatecomeearlyout"),
    # Biometric machines
    ("view_biometricdevices", "biometric.view_biometricdevices"),
    ("add_biometricdevices", "biometric.add_biometricdevices"),
    ("change_biometricdevices", "biometric.change_biometricdevices"),
    ("delete_biometricdevices", "biometric.delete_biometricdevices"),
    ("view_biometricemployees", "biometric.view_biometricemployees"),
    ("add_biometricemployees", "biometric.add_biometricemployees"),
    ("delete_biometricemployees", "biometric.delete_biometricemployees"),
    # Recruitment
    ("view_recruitment", "recruitment.view_recruitment"),
    ("add_recruitment", "recruitment.add_recruitment"),
    ("change_recruitment", "recruitment.change_recruitment"),
    ("delete_recruitment", "recruitment.delete_recruitment"),
    ("view_candidate", "recruitment.view_candidate"),
    ("add_candidate", "recruitment.add_candidate"),
    ("change_candidate", "recruitment.change_candidate"),
    ("delete_candidate", "recruitment.delete_candidate"),
    ("view_stage", "recruitment.view_stage"),
    ("change_stage", "recruitment.change_stage"),
    ("view_interviewschedule", "recruitment.view_interviewschedule"),
    ("change_interviewschedule", "recruitment.change_interviewschedule"),
    # Onboarding
    ("view_onboardingstage", "onboarding.view_onboardingstage"),
    ("change_onboardingstage", "onboarding.change_onboardingstage"),
    ("view_onboardingtask", "onboarding.view_onboardingtask"),
    ("change_onboardingtask", "onboarding.change_onboardingtask"),
    ("view_candidatestage", "onboarding.view_candidatestage"),
    ("change_candidatestage", "onboarding.change_candidatestage"),
    ("view_candidatetask", "onboarding.view_candidatetask"),
    ("change_candidatetask", "onboarding.change_candidatetask"),
    # Asset
    ("view_asset", "asset.view_asset"),
    ("add_asset", "asset.add_asset"),
    ("change_asset", "asset.change_asset"),
    ("delete_asset", "asset.delete_asset"),
    ("view_assetcategory", "asset.view_assetcategory"),
    ("change_assetcategory", "asset.change_assetcategory"),
    ("view_assetlot", "asset.view_assetlot"),
    ("change_assetlot", "asset.change_assetlot"),
    ("view_assetrequest", "asset.view_assetrequest"),
    ("add_assetrequest", "asset.add_assetrequest"),
    ("change_assetrequest", "asset.change_assetrequest"),
    # Helpdesk
    ("view_ticket", "helpdesk.view_ticket"),
    ("add_ticket", "helpdesk.add_ticket"),
    ("change_ticket", "helpdesk.change_ticket"),
    ("delete_ticket", "helpdesk.delete_ticket"),
    ("view_tickettype", "helpdesk.view_tickettype"),
    ("add_tickettype", "helpdesk.add_tickettype"),
    ("change_tickettype", "helpdesk.change_tickettype"),
    ("delete_tickettype", "helpdesk.delete_tickettype"),
    ("view_faq", "helpdesk.view_faq"),
    ("add_faq", "helpdesk.add_faq"),
    ("change_faq", "helpdesk.change_faq"),
    ("view_faqcategory", "helpdesk.view_faqcategory"),
    ("change_faqcategory", "helpdesk.change_faqcategory"),
    ("view_comment", "helpdesk.view_comment"),
    ("add_comment", "helpdesk.add_comment"),
    ("change_comment", "helpdesk.change_comment"),
    ("delete_comment", "helpdesk.delete_comment"),
    ("view_attachment", "helpdesk.view_attachment"),
    ("add_attachment", "helpdesk.add_attachment"),
    ("delete_attachment", "helpdesk.delete_attachment"),
    ("view_claimrequest", "helpdesk.view_claimrequest"),
    ("add_claimrequest", "helpdesk.add_claimrequest"),
    ("change_claimrequest", "helpdesk.change_claimrequest"),
    ("view_departmentmanager", "helpdesk.view_departmentmanager"),
    ("add_departmentmanager", "helpdesk.add_departmentmanager"),
    ("change_departmentmanager", "helpdesk.change_departmentmanager"),
    ("delete_departmentmanager", "helpdesk.delete_departmentmanager"),
    # OHS
    ("view_oshworkplace", "ohs.view_oshworkplace"),
    ("add_oshworkplace", "ohs.add_oshworkplace"),
    ("change_oshworkplace", "ohs.change_oshworkplace"),
    ("delete_oshworkplace", "ohs.delete_oshworkplace"),
    ("view_oshevent", "ohs.view_oshevent"),
    ("add_oshevent", "ohs.add_oshevent"),
    ("change_oshevent", "ohs.change_oshevent"),
    ("delete_oshevent", "ohs.delete_oshevent"),
    ("view_oshnotification", "ohs.view_oshnotification"),
    ("add_oshnotification", "ohs.add_oshnotification"),
    ("change_oshnotification", "ohs.change_oshnotification"),
    ("view_oshinvestigation", "ohs.view_oshinvestigation"),
    ("add_oshinvestigation", "ohs.add_oshinvestigation"),
    ("change_oshinvestigation", "ohs.change_oshinvestigation"),
    ("view_oshcorrectiveaction", "ohs.view_oshcorrectiveaction"),
    ("add_oshcorrectiveaction", "ohs.add_oshcorrectiveaction"),
    ("change_oshcorrectiveaction", "ohs.change_oshcorrectiveaction"),
    ("view_oshpolicy", "ohs.view_oshpolicy"),
    ("add_oshpolicy", "ohs.add_oshpolicy"),
    ("change_oshpolicy", "ohs.change_oshpolicy"),
    ("view_oshsafetycommittee", "ohs.view_oshsafetycommittee"),
    ("change_oshsafetycommittee", "ohs.change_oshsafetycommittee"),
    ("view_oshmedicalrecord", "ohs.view_oshmedicalrecord"),
    ("add_oshmedicalrecord", "ohs.add_oshmedicalrecord"),
    ("change_oshmedicalrecord", "ohs.change_oshmedicalrecord"),
    ("view_oshppeassignment", "ohs.view_oshppeassignment"),
    ("add_oshppeassignment", "ohs.add_oshppeassignment"),
    ("change_oshppeassignment", "ohs.change_oshppeassignment"),
    ("view_oshtrainingrecord", "ohs.view_oshtrainingrecord"),
    ("add_oshtrainingrecord", "ohs.add_oshtrainingrecord"),
    ("change_oshtrainingrecord", "ohs.change_oshtrainingrecord"),
    # Offboarding
    ("view_offboarding", "offboarding.view_offboarding"),
    ("change_offboarding", "offboarding.change_offboarding"),
    ("view_resignationletter", "offboarding.view_resignationletter"),
    ("add_resignationletter", "offboarding.add_resignationletter"),
    ("change_resignationletter", "offboarding.change_resignationletter"),
    ("view_offboardingstage", "offboarding.view_offboardingstage"),
    ("change_offboardingstage", "offboarding.change_offboardingstage"),
    ("view_offboardingtask", "offboarding.view_offboardingtask"),
    ("change_offboardingtask", "offboarding.change_offboardingtask"),
    # Performance (pms)
    ("view_objective", "pms.view_objective"),
    ("add_objective", "pms.add_objective"),
    ("change_objective", "pms.change_objective"),
    ("delete_objective", "pms.delete_objective"),
    ("view_employeeobjective", "pms.view_employeeobjective"),
    ("change_employeeobjective", "pms.change_employeeobjective"),
    ("view_keyresult", "pms.view_keyresult"),
    ("change_keyresult", "pms.change_keyresult"),
    ("view_feedback", "pms.view_feedback"),
    ("change_feedback", "pms.change_feedback"),
    ("view_meetings", "pms.view_meetings"),
    ("change_meetings", "pms.change_meetings"),
    ("view_employeebonuspoint", "pms.view_employeebonuspoint"),
    ("change_employeebonuspoint", "pms.change_employeebonuspoint"),
    # Settings (minimal for nav) + Employee Configuration org-structure (wave 3)
    ("view_company", "base.view_company"),
    ("add_company", "base.add_company"),
    ("change_company", "base.change_company"),
    ("delete_company", "base.delete_company"),
    ("view_department", "base.view_department"),
    ("add_department", "base.add_department"),
    ("change_department", "base.change_department"),
    ("delete_department", "base.delete_department"),
    ("view_jobposition", "base.view_jobposition"),
    ("add_jobposition", "base.add_jobposition"),
    ("change_jobposition", "base.change_jobposition"),
    ("delete_jobposition", "base.delete_jobposition"),
    ("view_jobrole", "base.view_jobrole"),
    ("add_jobrole", "base.add_jobrole"),
    ("change_jobrole", "base.change_jobrole"),
    ("delete_jobrole", "base.delete_jobrole"),
    ("view_worktype", "base.view_worktype"),
    ("add_worktype", "base.add_worktype"),
    ("change_worktype", "base.change_worktype"),
    ("delete_worktype", "base.delete_worktype"),
    ("view_employeeshift", "base.view_employeeshift"),
    ("add_employeeshift", "base.add_employeeshift"),
    ("change_employeeshift", "base.change_employeeshift"),
    ("delete_employeeshift", "base.delete_employeeshift"),
    ("view_employeeshiftschedule", "base.view_employeeshiftschedule"),
    ("add_employeeshiftschedule", "base.add_employeeshiftschedule"),
    ("change_employeeshiftschedule", "base.change_employeeshiftschedule"),
    ("delete_employeeshiftschedule", "base.delete_employeeshiftschedule"),
    ("view_rotatingshift", "base.view_rotatingshift"),
    ("add_rotatingshift", "base.add_rotatingshift"),
    ("change_rotatingshift", "base.change_rotatingshift"),
    ("delete_rotatingshift", "base.delete_rotatingshift"),
    ("view_rotatingworktype", "base.view_rotatingworktype"),
    ("add_rotatingworktype", "base.add_rotatingworktype"),
    ("change_rotatingworktype", "base.change_rotatingworktype"),
    ("delete_rotatingworktype", "base.delete_rotatingworktype"),
    # Policies & Discipline (wave 4). Actiontype is the Django model spelling.
    # Disciplinary PUT/DELETE still check add_disciplinaryaction in the API view;
    # expose change_/delete_ for has_perm honesty, but UI should gate edit/delete
    # on add_disciplinaryaction until that quirk is fixed separately.
    ("view_policy", "employee.view_policy"),
    ("add_policy", "employee.add_policy"),
    ("change_policy", "employee.change_policy"),
    ("delete_policy", "employee.delete_policy"),
    ("view_disciplinaryaction", "employee.view_disciplinaryaction"),
    ("add_disciplinaryaction", "employee.add_disciplinaryaction"),
    ("change_disciplinaryaction", "employee.change_disciplinaryaction"),
    ("delete_disciplinaryaction", "employee.delete_disciplinaryaction"),
    ("view_actiontype", "employee.view_actiontype"),
    ("add_actiontype", "employee.add_actiontype"),
    ("change_actiontype", "employee.change_actiontype"),
    ("delete_actiontype", "employee.delete_actiontype"),
    ("view_horillacolortheme", "horilla_theme.view_horillacolortheme"),
    ("change_horillacolortheme", "horilla_theme.change_horillacolortheme"),
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
    # Roles admin: any auth.*_group grant (superuser included via has_perm).
    permissions["manage_roles"] = any(
        user.has_perm(codename)
        for codename in (
            "auth.view_group",
            "auth.add_group",
            "auth.change_group",
            "auth.delete_group",
        )
    )
    permissions["can_switch_company"] = user.is_superuser

    return {
        "version": __version__,
        "role": _resolve_role(user),
        "permissions": permissions,
        "features": {label: apps.is_installed(label) for label in OPTIONAL_APPS},
    }
