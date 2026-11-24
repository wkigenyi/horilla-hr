from django.urls import path

from horilla_api.api_views.dashboard.views import PayrollDashboardWidgetAPIView
from horilla_api.api_views.payroll.adjustments import (
    PayAdjustmentBulkStatusView,
    PayAdjustmentImportConfirmView,
    PayAdjustmentImportErrorsView,
    PayAdjustmentImportTemplateView,
    PayAdjustmentImportView,
    PayAdjustmentStatusView,
    PayAdjustmentView,
)
from horilla_api.api_views.payroll.periods import (
    PayPeriodActionView,
    PayPeriodsView,
)
from horilla_api.api_views.payroll.task_earnings import (
    TaskEarningsPostView,
    TaskEarningsPreviewView,
)
from horilla_api.api_views.payroll.accounting import (
    AccountingExportView,
    AccountingGLMappingView,
    AccountingSummaryView,
)
from horilla_api.api_views.payroll.statutory import (
    UgandaScheduleExportView,
    UgandaScheduleView,
)
from horilla_api.api_views.payroll.configure import (
    ComponentCodeView,
    ComponentFormulaPreviewView,
    ComponentLibraryView,
    ComponentLimitPreviewView,
    ContractComponentView,
    ContractStatusView,
    ContributionView,
    CurrencySettingsView,
    EncashmentSettingsView,
    FilingStatusPreviewView,
    FilingStatusView,
    LoanInstallmentView,
    ReimbursementCommentDeleteView,
    ReimbursementCommentView,
    SalaryStructureAssignableView,
    SalaryStructureComponentView,
    SalaryStructureDuplicateView,
    SalaryStructureEmployeesView,
    SalaryStructurePreviewView,
    SalaryStructureView,
    SystemComponentView,
    TaxPackView,
)
from horilla_api.api_views.payroll.payslip_lines import (
    PayslipBulkDeleteView,
    PayslipLineApplyView,
    PayslipLinePreviewView,
    PayslipLineRecalculateView,
    PayslipLinesView,
)
from horilla_api.api_views.payroll.run import (
    PayPeriodGenerateView,
    PayPeriodView,
    PayrollBatchGenerateView,
    PayrollBatchReopenView,
    PayrollBatchStatusView,
    PayrollBatchView,
    PayrollReviewView,
)
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
    path("pay-periods/", PayPeriodsView.as_view(), name="api-pay-periods"),
    path(
        "pay-periods/<int:pk>/close/",
        PayPeriodActionView.as_view(action="close"),
        name="api-pay-periods-close",
    ),
    path(
        "pay-periods/<int:pk>/reopen/",
        PayPeriodActionView.as_view(action="reopen"),
        name="api-pay-periods-reopen",
    ),
    path("pay-period/", PayPeriodView.as_view(), name="api-pay-period"),
    path("pay-period/<int:pk>/", PayPeriodView.as_view(), name="api-pay-period-detail"),
    path(
        "pay-period/<int:pk>/generate/",
        PayPeriodGenerateView.as_view(),
        name="api-pay-period-generate",
    ),
    path("batches/review/", PayrollReviewView.as_view(), name="api-payroll-review"),
    path("batches/", PayrollBatchView.as_view(), name="api-payroll-batch"),
    path("batches/<int:pk>/", PayrollBatchView.as_view(), name="api-payroll-batch-detail"),
    path(
        "batches/<int:pk>/generate/",
        PayrollBatchGenerateView.as_view(),
        name="api-payroll-batch-generate",
    ),
    path(
        "batches/<int:pk>/status/",
        PayrollBatchStatusView.as_view(),
        name="api-payroll-batch-status",
    ),
    path(
        "batches/<int:pk>/reopen/",
        PayrollBatchReopenView.as_view(),
        name="api-payroll-batch-reopen",
    ),
    path(
        "pay-adjustment/import/template/",
        PayAdjustmentImportTemplateView.as_view(),
        name="api-pay-adjustment-template",
    ),
    path(
        "pay-adjustment/import/confirm/",
        PayAdjustmentImportConfirmView.as_view(),
        name="api-pay-adjustment-confirm",
    ),
    path(
        "pay-adjustment/import/errors/",
        PayAdjustmentImportErrorsView.as_view(),
        name="api-pay-adjustment-errors",
    ),
    path(
        "pay-adjustment/import/",
        PayAdjustmentImportView.as_view(),
        name="api-pay-adjustment-import",
    ),
    path(
        "pay-adjustment/bulk-status/",
        PayAdjustmentBulkStatusView.as_view(),
        name="api-pay-adjustment-bulk-status",
    ),
    path("pay-adjustment/", PayAdjustmentView.as_view(), name="api-pay-adjustment"),
    path(
        "pay-adjustment/<int:pk>/",
        PayAdjustmentView.as_view(),
        name="api-pay-adjustment-detail",
    ),
    path(
        "pay-adjustment/<int:pk>/status/",
        PayAdjustmentStatusView.as_view(),
        name="api-pay-adjustment-status",
    ),
    path(
        "task-earnings/preview/",
        TaskEarningsPreviewView.as_view(),
        name="api-task-earnings-preview",
    ),
    path(
        "task-earnings/post/",
        TaskEarningsPostView.as_view(),
        name="api-task-earnings-post",
    ),
    path(
        "payslip/bulk-delete/",
        PayslipBulkDeleteView.as_view(),
        name="api-payslip-bulk-delete",
    ),
    path(
        "payslip/<int:payslip_id>/lines/",
        PayslipLinesView.as_view(),
        name="api-payslip-lines",
    ),
    path(
        "payslip/<int:payslip_id>/lines/preview/",
        PayslipLinePreviewView.as_view(),
        name="api-payslip-line-preview",
    ),
    path(
        "payslip/<int:payslip_id>/lines/apply/",
        PayslipLineApplyView.as_view(),
        name="api-payslip-line-apply",
    ),
    path(
        "payslip/<int:payslip_id>/lines/recalculate/",
        PayslipLineRecalculateView.as_view(),
        name="api-payslip-line-recalculate",
    ),
    path("salary-structure/", SalaryStructureView.as_view(), name="api-salary-structure"),
    path(
        "salary-structure/<int:pk>/",
        SalaryStructureView.as_view(),
        name="api-salary-structure-detail",
    ),
    path(
        "salary-structure/<int:pk>/assignable/",
        SalaryStructureAssignableView.as_view(),
        name="api-salary-structure-assignable",
    ),
    path(
        "salary-structure/<int:pk>/employees/",
        SalaryStructureEmployeesView.as_view(),
        name="api-salary-structure-employees",
    ),
    path(
        "salary-structure/<int:pk>/duplicate/",
        SalaryStructureDuplicateView.as_view(),
        name="api-salary-structure-duplicate",
    ),
    path(
        "salary-structure/<int:pk>/preview/",
        SalaryStructurePreviewView.as_view(),
        name="api-salary-structure-preview",
    ),
    path(
        "salary-structure/<int:pk>/<slug:kind>/",
        SalaryStructureComponentView.as_view(),
        name="api-salary-structure-component",
    ),
    path(
        "salary-structure/<int:pk>/<slug:kind>/<int:component_id>/",
        SalaryStructureComponentView.as_view(),
        name="api-salary-structure-component-remove",
    ),
    path("component/code/", ComponentCodeView.as_view(), name="api-component-code"),
    path(
        "component/formula/",
        ComponentFormulaPreviewView.as_view(),
        name="api-component-formula",
    ),
    path(
        "component/limit/",
        ComponentLimitPreviewView.as_view(),
        name="api-component-limit",
    ),
    path("component/library/", ComponentLibraryView.as_view(), name="api-component-library"),
    path("system-component/", SystemComponentView.as_view(), name="api-system-component"),
    path(
        "system-component/<slug:key>/",
        SystemComponentView.as_view(),
        name="api-system-component-detail",
    ),
    path("filing-status/", FilingStatusView.as_view(), name="api-filing-status"),
    path(
        "filing-status/<int:pk>/",
        FilingStatusView.as_view(),
        name="api-filing-status-detail",
    ),
    path(
        "filing-status/<int:pk>/preview/",
        FilingStatusPreviewView.as_view(),
        name="api-filing-status-preview",
    ),
    path("tax-pack/", TaxPackView.as_view(), name="api-tax-pack"),
    path("currency/", CurrencySettingsView.as_view(), name="api-payroll-currency"),
    path(
        "accounting/gl-mappings/",
        AccountingGLMappingView.as_view(),
        name="api-payroll-accounting-gl-mappings",
    ),
    path(
        "accounting/summary/",
        AccountingSummaryView.as_view(),
        name="api-payroll-accounting-summary",
    ),
    path(
        "accounting/export/",
        AccountingExportView.as_view(),
        name="api-payroll-accounting-export",
    ),
    path(
        "statutory/uganda/",
        UgandaScheduleView.as_view(),
        name="api-payroll-statutory-uganda",
    ),
    path(
        "statutory/uganda/export/",
        UgandaScheduleExportView.as_view(),
        name="api-payroll-statutory-uganda-export",
    ),
    path("contribution/", ContributionView.as_view(), name="api-contribution"),
    path(
        "contribution/<int:component_id>/",
        ContributionView.as_view(),
        name="api-contribution-detail",
    ),
    path(
        "contract/bulk-status/",
        ContractStatusView.as_view(),
        name="api-contract-bulk-status",
    ),
    path(
        "contract/<int:pk>/status/",
        ContractStatusView.as_view(),
        name="api-contract-status",
    ),
    path(
        "contract/<int:pk>/components/",
        ContractComponentView.as_view(),
        name="api-contract-components",
    ),
    path(
        "loan-account/<int:pk>/installments/",
        LoanInstallmentView.as_view(),
        name="api-loan-installments",
    ),
    path(
        "loan-account/<int:pk>/installments/<int:deduction_id>/",
        LoanInstallmentView.as_view(),
        name="api-loan-installment",
    ),
    path(
        "reimbusement/<int:pk>/comment/",
        ReimbursementCommentView.as_view(),
        name="api-reimbursement-comment",
    ),
    path(
        "reimbusement/comment/<int:pk>/",
        ReimbursementCommentDeleteView.as_view(),
        name="api-reimbursement-comment-delete",
    ),
    path(
        "encashment-settings/",
        EncashmentSettingsView.as_view(),
        name="api-encashment-settings",
    ),
]
