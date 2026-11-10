from django.urls import path

from horilla_api.api_views.dashboard.views import PayrollDashboardWidgetAPIView
from ...api_views.payroll.views import *

urlpatterns = [
    path(
        "dashboard/<slug:widget>/",
        PayrollDashboardWidgetAPIView.as_view(),
        name="api-payroll-dashboard-widget",
    ),
    path(
        "contract/",
        ContractView.as_view(),
    ),
    path(
        "contract/<int:id>",
        ContractView.as_view(),
    ),
    path("payslip/", PayslipView.as_view(), name=""),
    path("payslip/bulk-status/", PayslipBulkStatusView.as_view(), name=""),
    path("payslip/generate/", PayslipGenerateView.as_view(), name=""),
    path("payslip/<int:id>", PayslipView.as_view(), name=""),
    path("payslip-download/<int:id>", PayslipPDFAPIView.as_view(), name=""),
    path("payslip-send-mail/", PayslipSendMailView.as_view(), name=""),
    path("loan-account/", LoanAccountView.as_view(), name=""),
    path("loan-account/<int:pk>", LoanAccountView.as_view(), name=""),
    path("reimbusement/", ReimbursementView.as_view(), name=""),
    path("reimbusement/<int:pk>", ReimbursementView.as_view(), name=""),
    path(
        "reimbusement-approve-reject/<int:pk>",
        ReimbusementApproveRejectView.as_view(),
        name="",
    ),
    path("tax-bracket/<int:pk>", TaxBracketView.as_view(), name=""),
    path("tax-bracket/", TaxBracketView.as_view(), name=""),
    path("allowance", AllowanceView.as_view(), name=""),
    path("allowance/<int:pk>", AllowanceView.as_view(), name=""),
    path("deduction", DeductionView.as_view(), name=""),
    path("deduction/<int:pk>", DeductionView.as_view(), name=""),
]
