"""
The analytics home dashboard over JWT.

``base/dashboard.py`` already computes every KPI, chart and side panel the
web dashboard draws, but each function is a session-only Django view under
``/dashboard/api/``. These endpoints expose the same functions to API
clients: DRF authenticates the bearer token, sets ``request._request.user``
and the tenant scope, and the wrapped function then runs exactly as it does
for the web page, including its own permission checks and manager scoping.

One summary endpoint says which persona the caller is and which charts that
persona sees by default; one widget endpoint serves any chart or panel by
slug. Nothing is recomputed here -- this is a thin door, not a second
dashboard.
"""

from datetime import date

from django.http import Http404
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from asset import dashboard as asset_dashboard
from helpdesk import dashboard as helpdesk_dashboard
from leave import dashboard as leave_dashboard
from offboarding import dashboard as offboarding_dashboard
from payroll import dashboard as payroll_dashboard
from pms import dashboard as pms_dashboard
from recruitment import dashboard as recruitment_dashboard
from attendance import dashboard as attendance_dashboard
from base import dashboard as dashboard_module
from onboarding import dashboard as onboarding_dashboard
from base.dashboard_roles import resolve_home_role, role_default_prefs
from base import ess_dashboard
from project import dashboard as project_dashboard

WIDGETS = {
    "kpi": dashboard_module.dashboard_kpi_data,
    "attendance-trend": dashboard_module.dashboard_attendance_trend,
    "attendance-overview": dashboard_module.dashboard_attendance_overview,
    "department-overtime": dashboard_module.dashboard_department_overtime,
    "leave-coverage": dashboard_module.dashboard_leave_coverage,
    "recruitment-pipeline": dashboard_module.dashboard_recruitment_by_stage,
    "recruitment-funnel": dashboard_module.dashboard_recruitment_pipeline,
    "turnover": dashboard_module.dashboard_turnover,
    "payroll-summary": dashboard_module.dashboard_payroll_summary,
    "announcements": dashboard_module.dashboard_announcements,
    "todays-leave": dashboard_module.dashboard_todays_leave,
    "upcoming-holidays": dashboard_module.dashboard_upcoming_holidays,
    "birthdays-anniversaries": dashboard_module.dashboard_birthdays_anniversaries,
    "pending-approvals": dashboard_module.dashboard_pending_approvals,
    "department-headcount": dashboard_module.dashboard_department_headcount,
    "gender": dashboard_module.dashboard_gender_split,
    "leave-breakdown": dashboard_module.dashboard_leave_breakdown,
    "leave-trends": dashboard_module.dashboard_leave_trends,
    "leave-by-department": dashboard_module.dashboard_leave_by_department,
    "department-leave-days": dashboard_module.dashboard_department_leave_days,
    "hiring-timeline": dashboard_module.dashboard_hiring_timeline,
    "employee-status": dashboard_module.dashboard_employee_status,
}

# Chart ids the web template uses, keyed by the widget slug that feeds them.
CHART_WIDGETS = {
    "attendance_trend": "attendance-trend",
    "attendance_overview": "attendance-overview",
    "department_overtime": "department-overtime",
    "leave_coverage": "leave-coverage",
    "recruitment_pipeline": "recruitment-pipeline",
    "recruitment_funnel": "recruitment-funnel",
    "employee_turnover": "turnover",
    "payroll_summary": "payroll-summary",
    "department_headcount": "department-headcount",
    "gender_distribution": "gender",
    "leave_breakdown": "leave-breakdown",
    "leave_trends": "leave-trends",
    "leave_by_department": "leave-by-department",
    "department_leave_days": "department-leave-days",
    "hiring_timeline": "hiring-timeline",
    "employee_status": "employee-status",
}


class DashboardAPIView(APIView):
    """Persona, default chart set and company scope for the caller."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        django_request = request._request
        role = resolve_home_role(django_request)
        visible = [
            CHART_WIDGETS[pref["id"]]
            for pref in role_default_prefs(role, list(CHART_WIDGETS))
            if pref["visible"] and pref["id"] in CHART_WIDGETS
        ]
        scope = dashboard_module._company_scope_context(django_request)
        return Response(
            {
                "role": role,
                "visible_charts": visible,
                "date": date.today().isoformat(),
                "company_label": scope["dashboard_company_label"],
                "company_is_all": scope["dashboard_company_is_all"],
            },
            status=200,
        )


PROJECT_WIDGETS = {
    "kpi": project_dashboard.project_kpi_data,
    "pipeline": project_dashboard.project_status_pipeline,
    "tasks": project_dashboard.project_task_status,
    "trend": project_dashboard.project_monthly_trend,
    "top": project_dashboard.project_top_active,
    "contributors": project_dashboard.project_top_contributors,
    "deadlines": project_dashboard.project_task_deadlines,
}


def _widget_response(request, view):
    """Run a session dashboard view for the authenticated API caller.

    A module view that answers with HTML or a redirect is saying the caller
    is not allowed. Keep the API shape instead of forwarding that page.
    """
    response = view(request._request)
    content_type = response.get("Content-Type", "")
    if not content_type.startswith("application/json"):
        return Response({"no_permission": True}, status=403)
    return response


class DashboardWidgetAPIView(APIView):
    """One chart or side panel, by slug, as the web dashboard computes it."""

    permission_classes = [IsAuthenticated]

    def get(self, request, widget):
        view = WIDGETS.get(widget)
        if view is None:
            raise Http404
        return _widget_response(request, view)


ESS_WIDGETS = {
    "kpi": ess_dashboard.ess_kpi_data,
    "leave-balance": ess_dashboard.ess_leave_balance,
    "leave-requests": ess_dashboard.ess_leave_requests,
    "attendance-calendar": ess_dashboard.ess_attendance_calendar,
    "work-hours": ess_dashboard.ess_work_hours_month,
    "payslips": ess_dashboard.ess_payslips,
    "objectives": ess_dashboard.ess_objectives,
    "announcements": ess_dashboard.ess_announcements,
    "upcoming": ess_dashboard.ess_upcoming,
}


class EssDashboardWidgetAPIView(APIView):
    """One personal dashboard widget, computed by the ESS views."""

    permission_classes = [IsAuthenticated]

    def get(self, request, widget):
        view = ESS_WIDGETS.get(widget)
        if view is None:
            raise Http404
        return _widget_response(request, view)


class ProjectDashboardWidgetAPIView(APIView):
    """One project dashboard widget, computed by the reference views."""

    permission_classes = [IsAuthenticated]

    def get(self, request, widget):
        view = PROJECT_WIDGETS.get(widget)
        if view is None:
            raise Http404
        return _widget_response(request, view)


ATTENDANCE_WIDGETS = {
    "kpi": attendance_dashboard.attendance_kpi_data,
    "weekly": attendance_dashboard.attendance_weekly_trend,
    "departments": attendance_dashboard.attendance_department_breakdown,
    "late-early": attendance_dashboard.attendance_late_early_data,
    "overtime": attendance_dashboard.attendance_overtime_summary,
    "hours": attendance_dashboard.attendance_hours_distribution,
    "shifts": attendance_dashboard.attendance_shift_distribution,
    "absenteeism": attendance_dashboard.attendance_absenteeism_trend,
    "work-types": attendance_dashboard.attendance_work_type_distribution,
    "avg-hours": attendance_dashboard.attendance_avg_working_hours,
    "top-absentees": attendance_dashboard.attendance_top_absentees,
    "clockin": attendance_dashboard.attendance_clockin_distribution,
    "calendar": attendance_dashboard.attendance_calendar_heatmap,
    "overview": attendance_dashboard.attendance_overview,
}


class AttendanceDashboardWidgetAPIView(APIView):
    """One attendance dashboard widget, computed by the reference views."""

    permission_classes = [IsAuthenticated]

    def get(self, request, widget):
        view = ATTENDANCE_WIDGETS.get(widget)
        if view is None:
            raise Http404
        return _widget_response(request, view)


ONBOARDING_WIDGETS = {
    "kpi": onboarding_dashboard.onboarding_kpi_data,
    "stages": onboarding_dashboard.onboarding_stage_distribution,
    "tasks": onboarding_dashboard.onboarding_task_status,
    "recruitment": onboarding_dashboard.onboarding_by_recruitment,
    "position": onboarding_dashboard.onboarding_by_job_position,
    "candidates": onboarding_dashboard.onboarding_candidates_list,
    "my-tasks": onboarding_dashboard.onboarding_task_managers,
    "completion-trend": onboarding_dashboard.onboarding_completion_trend,
    "portal-status": onboarding_dashboard.onboarding_portal_status,
}


class OnboardingDashboardWidgetAPIView(APIView):
    """One onboarding dashboard widget, computed by the reference views."""

    permission_classes = [IsAuthenticated]

    def get(self, request, widget):
        view = ONBOARDING_WIDGETS.get(widget)
        if view is None:
            raise Http404
        return _widget_response(request, view)


ASSET_WIDGETS = {
    "kpi": asset_dashboard.asset_kpi_data,
    "status": asset_dashboard.asset_status_distribution,
    "category": asset_dashboard.asset_by_category,
    "requests": asset_dashboard.asset_request_status,
    "value": asset_dashboard.asset_value_by_category,
    "expiring": asset_dashboard.asset_expiring_soon,
    "allocations": asset_dashboard.asset_recent_allocations,
    "department": asset_dashboard.asset_department_distribution,
    "age": asset_dashboard.asset_age_distribution,
}


class AssetDashboardWidgetAPIView(APIView):
    """One asset dashboard widget, computed by the reference views."""

    permission_classes = [IsAuthenticated]

    def get(self, request, widget):
        view = ASSET_WIDGETS.get(widget)
        if view is None:
            raise Http404
        return _widget_response(request, view)


HELPDESK_WIDGETS = {
    "kpi": helpdesk_dashboard.helpdesk_kpi_data,
    "status": helpdesk_dashboard.helpdesk_status_distribution,
    "priority": helpdesk_dashboard.helpdesk_priority_distribution,
    "type": helpdesk_dashboard.helpdesk_type_distribution,
    "trend": helpdesk_dashboard.helpdesk_monthly_trend,
    "department": helpdesk_dashboard.helpdesk_department_breakdown,
    "overdue": helpdesk_dashboard.helpdesk_overdue_tickets,
    "recent": helpdesk_dashboard.helpdesk_recent_tickets,
    "sla": helpdesk_dashboard.helpdesk_sla_compliance,
    "workload": helpdesk_dashboard.helpdesk_assignee_workload,
}


class HelpdeskDashboardWidgetAPIView(APIView):
    """One tickets dashboard widget, computed by the reference views."""

    permission_classes = [IsAuthenticated]

    def get(self, request, widget):
        view = HELPDESK_WIDGETS.get(widget)
        if view is None:
            raise Http404
        return _widget_response(request, view)


OFFBOARDING_WIDGETS = {
    "kpi": offboarding_dashboard.offboarding_kpi_data,
    "pipeline": offboarding_dashboard.offboarding_pipeline,
    "resignation": offboarding_dashboard.offboarding_resignation_status,
    "tasks": offboarding_dashboard.offboarding_task_status,
    "department": offboarding_dashboard.offboarding_department_attrition,
    "exit-reasons": offboarding_dashboard.offboarding_exit_reasons,
    "notice": offboarding_dashboard.offboarding_notice_period_tracker,
    "assets": offboarding_dashboard.offboarding_unreturned_assets,
    "join-exit": offboarding_dashboard.offboarding_joining_vs_exiting,
    "avg-duration": offboarding_dashboard.offboarding_avg_duration,
}


class OffboardingDashboardWidgetAPIView(APIView):
    """One offboarding dashboard widget, computed by the reference views."""

    permission_classes = [IsAuthenticated]

    def get(self, request, widget):
        view = OFFBOARDING_WIDGETS.get(widget)
        if view is None:
            raise Http404
        return _widget_response(request, view)


PAYROLL_WIDGETS = {
    "kpi": payroll_dashboard.payroll_kpi_data,
    "trend": payroll_dashboard.payroll_monthly_trend,
    "department": payroll_dashboard.payroll_department_cost,
    "pipeline": payroll_dashboard.payroll_status_pipeline,
    "top-earners": payroll_dashboard.payroll_top_earners,
    "contracts": payroll_dashboard.payroll_contract_status,
    "loans": payroll_dashboard.payroll_loan_summary,
    "reimbursement": payroll_dashboard.payroll_reimbursement_summary,
    "salary-dist": payroll_dashboard.payroll_salary_distribution,
    "components": payroll_dashboard.payroll_component_breakdown,
}


class PayrollDashboardWidgetAPIView(APIView):
    """One payroll dashboard widget, computed by the reference views."""

    permission_classes = [IsAuthenticated]

    def get(self, request, widget):
        view = PAYROLL_WIDGETS.get(widget)
        if view is None:
            raise Http404
        return _widget_response(request, view)


PMS_WIDGETS = {
    "kpi": pms_dashboard.pms_kpi_data,
    "objective-status": pms_dashboard.pms_objective_status,
    "kr-status": pms_dashboard.pms_key_result_status,
    "feedback-status": pms_dashboard.pms_feedback_status,
    "department": pms_dashboard.pms_department_performance,
    "at-risk": pms_dashboard.pms_at_risk_objectives,
    "performers": pms_dashboard.pms_top_performers,
    "okr-overview": pms_dashboard.pms_kr_progress_overview,
    "meetings": pms_dashboard.pms_upcoming_meetings,
    "progress-trend": pms_dashboard.pms_progress_trend,
    "feedback-completion": pms_dashboard.pms_feedback_completion,
}


class PmsDashboardWidgetAPIView(APIView):
    """One performance dashboard widget, computed by the reference views."""

    permission_classes = [IsAuthenticated]

    def get(self, request, widget):
        view = PMS_WIDGETS.get(widget)
        if view is None:
            raise Http404
        return _widget_response(request, view)


LEAVE_WIDGETS = {
    "kpi": leave_dashboard.leave_kpi_data,
    "monthly-trend": leave_dashboard.leave_monthly_trend,
    "type-distribution": leave_dashboard.leave_type_distribution,
    "department": leave_dashboard.leave_department_breakdown,
    "utilization": leave_dashboard.leave_utilization_rate,
    "paid-unpaid": leave_dashboard.leave_paid_unpaid_split,
    "top-takers": leave_dashboard.leave_top_takers,
    "on-leave": leave_dashboard.leave_on_leave_today,
    "holidays": leave_dashboard.leave_upcoming_holidays,
    "weekly-pattern": leave_dashboard.leave_weekly_pattern,
    "upcoming": leave_dashboard.leave_upcoming,
}


class LeaveDashboardWidgetAPIView(APIView):
    """One leave manager dashboard widget, computed by the reference views."""

    permission_classes = [IsAuthenticated]

    def get(self, request, widget):
        view = LEAVE_WIDGETS.get(widget)
        if view is None:
            raise Http404
        return _widget_response(request, view)


RECRUITMENT_WIDGETS = {
    "kpi": recruitment_dashboard.recruitment_kpi_data,
    "offer-status": recruitment_dashboard.recruitment_offer_status,
    "stage-summary": recruitment_dashboard.recruitment_stage_summary,
    "pipeline": recruitment_dashboard.recruitment_pipeline_data,
    "source-quality": recruitment_dashboard.recruitment_source_quality,
    "time-to-hire": recruitment_dashboard.recruitment_time_to_hire,
    "managers": recruitment_dashboard.recruitment_managers_data,
    "source-of-hire": recruitment_dashboard.recruitment_source_of_hire,
    "upcoming-interviews": recruitment_dashboard.recruitment_upcoming_interviews,
    "open-by-dept": recruitment_dashboard.recruitment_open_by_department,
    "stage-conversion": recruitment_dashboard.recruitment_stage_conversion,
    "source-conversion": recruitment_dashboard.recruitment_source_conversion,
    "joinings": recruitment_dashboard.recruitment_joinings_monthly,
}


class RecruitmentDashboardWidgetAPIView(APIView):
    """One recruitment dashboard widget, computed by the reference views."""

    permission_classes = [IsAuthenticated]

    def get(self, request, widget):
        view = RECRUITMENT_WIDGETS.get(widget)
        if view is None:
            raise Http404
        return _widget_response(request, view)
