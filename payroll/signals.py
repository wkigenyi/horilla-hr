from django.apps import apps
from django.db.models import Q
from django.db.models.signals import m2m_changed, post_delete, post_save, pre_save
from django.dispatch import receiver

from employee.models import Employee, EmployeeWorkInformation
from payroll.methods.contract_start import create_draft_contract, follow_joining_date
from payroll.methods.deductions import create_deductions
from payroll.models.models import (
    Allowance,
    Deduction,
    EncashmentGeneralSettings,
    LoanAccount,
    Payslip,
)
from payroll.models.tax_models import PayrollSettings


@receiver(m2m_changed, sender=EncashmentGeneralSettings.employees.through)
@receiver(m2m_changed, sender=EncashmentGeneralSettings.department.through)
@receiver(m2m_changed, sender=EncashmentGeneralSettings.job_position.through)
def encashment_settings_filtered_employees(sender, instance, action, **kwargs):
    """
    Recompute EncashmentGeneralSettings.filtered_employees whenever the
    employees/department/job_position eligibility selection changes --
    mirrors Policy's targeting in base/signals.py.
    """
    if action not in ["post_add", "post_remove", "post_clear"]:
        return
    employee_ids = list(instance.employees.values_list("id", flat=True))
    department_ids = list(instance.department.values_list("id", flat=True))
    job_position_ids = list(instance.job_position.values_list("id", flat=True))

    employees = Employee.objects.filter(
        Q(id__in=employee_ids)
        | Q(employee_work_info__department_id__in=department_ids)
        | Q(employee_work_info__job_position_id__in=job_position_ids)
    )

    instance.filtered_employees.set(employees)


@receiver(pre_save, sender=EmployeeWorkInformation)
def employeeworkinformation_pre_save(sender, instance, **kwargs):
    """Remember the joining date before the save, so a draft contract can follow it."""
    instance._joining_before = (
        EmployeeWorkInformation.objects.filter(pk=instance.pk)
        .values_list("date_joining", flat=True)
        .first()
        if instance.pk and not kwargs.get("raw")
        else None
    )


@receiver(post_save, sender=EmployeeWorkInformation)
def employeeworkinformation_post_save(sender, instance, **_kwargs):
    """
    Give an active employee a draft contract once they have a joining date.

    The contract starts on the joining date and stays a draft, so its pay is
    confirmed before payroll uses it. It used to be made on the first save,
    before the joining date or salary were filled in: active, dated the day the
    employee was added, at a wage of 0. A draft that started on the old joining
    date moves with it when the joining date changes.

    Set ``skip_draft_contract`` on the work information to save it without
    making a contract, when whoever added the employee chose not to.
    """
    # Skip during fixture load — demo contracts come from payroll_data.json
    if _kwargs.get("raw"):
        return

    employee = instance.employee_id
    if employee is None or not employee.is_active or instance.date_joining is None:
        return
    follow_joining_date(
        employee, getattr(instance, "_joining_before", None), instance.date_joining
    )
    if getattr(instance, "skip_draft_contract", False):
        return
    create_draft_contract(employee, instance)


@receiver(post_save, sender=Allowance)
@receiver(post_save, sender=Deduction)
def standard_component_saved(sender, instance, **kwargs):
    """
    Editing a standard component (Loan, Fine, Reimbursement ...) reaches the rows it generated that
    no payslip carries yet, so its Taxable / Pre-Tax setting applies to them and not only to new ones.
    """
    if kwargs.get("raw") or not (instance.is_system and instance.system_key):
        return
    from payroll.methods.system_sync import align

    align(keys={instance.system_key})


@receiver(post_save, sender=LoanAccount)
def create_installments(sender, instance, created, **kwargs):
    """
    Post save method for loan account
    """
    # Demo fixtures carry pre-built allowance and installment relationships.
    # Rebuilding them while loaddata is running duplicates the allowance and
    # replaces the curated schedule with signal-generated records.
    if kwargs.get("raw"):
        return

    installments = []
    asset = True
    if apps.is_installed("asset"):
        asset = True if instance.asset_id is None else False

    if created and asset and instance.type != "fine":
        from payroll.methods.deductions import LOAN_PAYOUT_KEYS
        from payroll.system_components import policy_fields

        loan = Allowance()
        loan.title = instance.title
        loan.amount = instance.loan_amount
        loan.include_active_employees = False
        loan.only_show_under_employee = True
        loan.is_fixed = True
        loan.one_time_date = instance.provided_date
        loan.is_loan = True

        # Whether the payout is taxed, and whether it prorates, comes from the
        # standard component for this kind. The defaults it used to inherit
        # made a loan taxable income and prorated it by calendar days -- so a
        # mid-month joiner received a fraction of the loan they were granted.
        for field, value in policy_fields(
            LOAN_PAYOUT_KEYS.get(instance.type, "loan_payout"),
            employee=instance.employee_id,
        ).items():
            setattr(loan, field, value)

        loan.save()
        loan.specific_employees.add(instance.employee_id)
        instance.allowance_id = loan
        super(LoanAccount, instance).save()
    else:
        deductions = instance.deduction_ids.values_list("id", flat=True)
        payslips_with_deductions = Payslip.objects.filter(
            installment_ids__in=deductions
        )
        balance_deduction = [
            deduction_id
            for deduction_id in deductions
            if not payslips_with_deductions.filter(
                installment_ids=deduction_id
            ).exists()
        ]
        installment_dict = instance.get_installments()

        if not payslips_with_deductions and not instance.settled:
            # Nothing is paid yet, so the whole loan is still editable -
            # keep the one-time payout allowance in sync with the (possibly
            # changed) employee/amount/date/title before regenerating the
            # installment deductions below, which already follow
            # instance.employee_id via create_deductions().
            if instance.allowance_id:
                allowance = instance.allowance_id
                allowance.title = instance.title
                allowance.amount = instance.loan_amount
                allowance.one_time_date = instance.provided_date
                allowance.save()
                allowance.specific_employees.set([instance.employee_id])
            Deduction.objects.filter(id__in=deductions).delete()
            for (
                installment_date,
                installment_amount,
            ) in installment_dict.items():
                installment = create_deductions(
                    instance, installment_amount, installment_date
                )

                installments.append(installment)

            instance.deduction_ids.add(*installments)
            return

        if instance.settled:
            Deduction.objects.filter(id__in=balance_deduction).delete()

        else:
            if not balance_deduction:
                for (
                    installment_date,
                    installment_amount,
                ) in installment_dict.items():
                    if not Deduction.objects.filter(
                        one_time_date=installment_date,
                        specific_employees=instance.employee_id,
                        is_installment=True,
                        title=instance.title,
                    ).exists():
                        installment = create_deductions(
                            instance, installment_amount, installment_date
                        )

                        installments.append(installment)

                instance.deduction_ids.add(*installments)


@receiver(post_save, sender=PayrollSettings)
@receiver(post_delete, sender=PayrollSettings)
def forget_remembered_payroll_settings(sender, **kwargs):
    """A currency change shows at once, even later in the same request."""
    PayrollSettings.forget_remembered()


@receiver(post_delete, sender=Payslip)
@receiver(post_save, sender=Payslip)
def keep_batch_summary_current(sender, instance, created=False, **kwargs):
    """A batch follows the payslips inside it: edits and deletes change its summary, and it goes with its last payslip."""
    if kwargs.get("raw") or created or not instance.payroll_batch_id:
        return
    from payroll.methods.batch_run import defer_batch_totals
    from payroll.models.payroll_batch import PayrollBatch

    if defer_batch_totals.get():
        # A slice is being written: it refreshes the batch once, after it commits.
        return

    batch = PayrollBatch._base_manager.filter(pk=instance.payroll_batch_id).first()
    if batch is None:
        return
    if kwargs.get("signal") is post_delete and not batch.payslips.exists():
        # Its last payslip is gone, so there is nothing left for the batch to describe.
        batch.delete()
        return
    batch.refresh_totals()
