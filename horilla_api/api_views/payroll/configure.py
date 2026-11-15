"""Payroll configuration the classic settings screens expose, as JSON."""

import json
from datetime import date

from django.core.exceptions import ValidationError
from django.db.models import Sum
from django.utils.translation import gettext as _
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from base.methods import get_next_month_same_date, get_nth_month_same_date
from horilla_api.api_methods.base.pagination import HorillaPageNumberPagination
from payroll.component_library import library_rows, load_components
from payroll.methods.component_formula import ComponentFormulaError, run_component_formula
from payroll.methods.contributions import breakdown, summarise
from payroll.methods.deductions import create_deductions
from payroll.methods.safe_tax_code import (
    PYTHON_FORMULAS_OFF_MESSAGE,
    TaxCodeValidationError,
    python_formulas_enabled,
    same_formula,
    validate_tax_code,
)
from payroll.methods.tax_calc import TaxComputationError, preview_yearly_tax
from payroll.models.models import (
    Allowance,
    Contract,
    Deduction,
    EncashmentGeneralSettings,
    FilingStatus,
    LoanAccount,
    PayPeriodSettings,
    Payslip,
    Reimbursement,
    ReimbursementrequestComment,
    SalaryStructure,
    SystemComponentTaxOverride,
)
from payroll.models.tax_models import PayrollSettings
from payroll.system_components import (
    SYSTEM_COMPONENTS,
    editable_fields,
    policy,
    tax_field,
)
from payroll.tax_packs import load_tax_packs, pack_rows
from payroll.views.component_formula_views import (
    available_codes,
    limit_note_rows,
    sample_context,
)
from payroll.views.contract_components import _rows_for
from payroll.views.salary_structure_preview import preview_salary_structure

from .common import (
    as_id_list,
    company_for,
    employee_brief,
    parse_date,
    require_perm,
    validation_response,
)


def _plain_row(row):
    component = row["component"]
    return {
        "kind": row["kind"],
        "id": component.pk,
        "sequence": component.sequence,
        "code": component.code,
        "title": component.title,
        "type_label": str(row.get("type_label") or ""),
        "calculation": str(row.get("calculation") or ""),
        "prorates": str(row.get("prorates") or ""),
        "in_ctc": str(row.get("in_ctc") or ""),
        "ceiling": str(row.get("ceiling") or ""),
        "applies": str(row.get("applies") or ""),
        "taxable": str(row.get("taxable") or ""),
    }


def _structure_payload(structure, detail=False):
    data = {
        "id": structure.pk,
        "title": structure.title,
        "structure_mode": structure.structure_mode,
        "allowance_ids": list(structure.allowances.values_list("pk", flat=True)),
        "deduction_ids": list(structure.deductions.values_list("pk", flat=True)),
        "employee_ids": [
            contract.employee_id_id for contract in structure._active_contracts()
        ],
    }
    if detail:
        data["component_rows"] = [_plain_row(row) for row in structure.component_rows]
        data["sample_inputs"] = {
            key: {"used": value["used"], "why": str(value["why"])}
            for key, value in structure.sample_inputs.items()
        }
    return data


class SalaryStructureView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, pk=None):
        blocked = require_perm(request, "payroll.view_salarystructure")
        if blocked:
            return blocked
        if pk:
            structure = SalaryStructure.objects.filter(pk=pk).first()
            if structure is None:
                return Response({"detail": _("Salary structure not found.")}, status=404)
            return Response(_structure_payload(structure, detail=True), status=200)
        pagination = HorillaPageNumberPagination()
        page = pagination.paginate_queryset(
            SalaryStructure.objects.all().order_by("title", "pk"), request
        )
        return pagination.get_paginated_response(
            [_structure_payload(structure) for structure in page]
        )

    def post(self, request):
        blocked = require_perm(request, "payroll.add_salarystructure")
        if blocked:
            return blocked
        structure = SalaryStructure(
            title=(request.data.get("title") or "").strip(),
            structure_mode=request.data.get("structure_mode") or "gross_up",
            company_id=company_for(request),
        )
        try:
            structure.full_clean()
            structure.save()
        except ValidationError as exc:
            return validation_response(exc)
        return Response(_structure_payload(structure, detail=True), status=201)

    def put(self, request, pk):
        blocked = require_perm(request, "payroll.change_salarystructure")
        if blocked:
            return blocked
        structure = SalaryStructure.objects.filter(pk=pk).first()
        if structure is None:
            return Response({"detail": _("Salary structure not found.")}, status=404)
        if "title" in request.data:
            structure.title = (request.data.get("title") or "").strip()
        if "structure_mode" in request.data:
            structure.structure_mode = request.data.get("structure_mode") or "gross_up"
        try:
            structure.full_clean()
            structure.save()
        except ValidationError as exc:
            return validation_response(exc)
        return Response(_structure_payload(structure, detail=True), status=200)

    def delete(self, request, pk):
        blocked = require_perm(request, "payroll.delete_salarystructure")
        if blocked:
            return blocked
        structure = SalaryStructure.objects.filter(pk=pk).first()
        if structure is None:
            return Response({"detail": _("Salary structure not found.")}, status=404)
        structure.delete()
        return Response({"status": "deleted"}, status=200)


def _configurable(model, pk):
    return (
        model.objects.exclude(is_system=True)
        .exclude(only_show_under_employee=True)
        .filter(pk=pk)
        .first()
    )


class SalaryStructureComponentView(APIView):
    """Attach or detach one allowance or deduction. Membership stays in sync."""

    permission_classes = [IsAuthenticated]

    def post(self, request, pk, kind):
        blocked = require_perm(request, "payroll.change_salarystructure")
        if blocked:
            return blocked
        structure = SalaryStructure.objects.filter(pk=pk).first()
        if structure is None:
            return Response({"detail": _("Salary structure not found.")}, status=404)
        model = Allowance if kind == "allowance" else Deduction
        component = _configurable(model, request.data.get("id"))
        if component is None:
            return Response({"detail": _("Component not found.")}, status=404)
        if kind == "allowance":
            structure.add_allowance(component)
        else:
            structure.add_deduction(component)
        return Response(_structure_payload(structure, detail=True), status=200)

    def delete(self, request, pk, kind, component_id):
        blocked = require_perm(request, "payroll.change_salarystructure")
        if blocked:
            return blocked
        structure = SalaryStructure.objects.filter(pk=pk).first()
        if structure is None:
            return Response({"detail": _("Salary structure not found.")}, status=404)
        model = Allowance if kind == "allowance" else Deduction
        component = model.objects.filter(pk=component_id).first()
        if component is None:
            return Response({"detail": _("Component not found.")}, status=404)
        if kind == "allowance":
            structure.remove_allowance(component)
        else:
            structure.remove_deduction(component)
        return Response(_structure_payload(structure, detail=True), status=200)


class SalaryStructureDuplicateView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        blocked = require_perm(request, "payroll.add_salarystructure")
        if blocked:
            return blocked
        original = SalaryStructure.objects.filter(pk=pk).first()
        if original is None:
            return Response({"detail": _("Salary structure not found.")}, status=404)
        title = (request.data.get("title") or "").strip() or _("%(title)s (copy)") % {
            "title": original.title
        }
        copy = SalaryStructure(
            title=title,
            structure_mode=original.structure_mode,
            company_id=original.company_id,
        )
        try:
            copy.full_clean()
            copy.save()
        except ValidationError as exc:
            return validation_response(exc)
        for allowance in original.allowances.all():
            copy.allowances.add(allowance)
        for deduction in original.deductions.all():
            copy.deductions.add(deduction)
        return Response(_structure_payload(copy, detail=True), status=201)


class _Post:
    def __init__(self, data):
        self._data = {key: "" if value is None else str(value) for key, value in data.items()}

    def get(self, name, default=None):
        return self._data.get(name, default)


class SalaryStructurePreviewView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        blocked = require_perm(request, "payroll.view_salarystructure")
        if blocked:
            return blocked

        class _Request:
            POST = _Post(request.data)

        response = preview_salary_structure(_Request(), pk)
        return Response(json.loads(response.content), status=response.status_code)


class ComponentCodeView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        blocked = require_perm(request, "payroll.view_allowance")
        if blocked:
            return blocked
        from payroll.models.models import component_code_taken, component_code_validator

        code = (request.GET.get("code") or "").strip().upper()
        model = Deduction if request.GET.get("kind") == "deduction" else Allowance
        try:
            pk = int(request.GET.get("pk") or 0) or None
        except ValueError:
            pk = None
        if not code:
            return Response({"ok": True, "message": ""}, status=200)
        try:
            component_code_validator(code)
        except Exception as exc:
            message = getattr(exc, "messages", [str(exc)])[0]
            return Response({"ok": False, "message": str(message)}, status=200)
        if component_code_taken(code, model, pk):
            return Response(
                {
                    "ok": False,
                    "message": _("The code %(code)s is already used.") % {"code": code},
                },
                status=200,
            )
        return Response({"ok": True, "message": _("Available")}, status=200)


class ComponentFormulaPreviewView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        blocked = require_perm(request, "payroll.view_allowance")
        if blocked:
            return blocked
        return Response({"codes": available_codes()}, status=200)

    def post(self, request):
        blocked = require_perm(request, "payroll.view_allowance")
        if blocked:
            return blocked
        expression = request.data.get("formula") or ""
        try:
            sample_basic = float(request.data.get("sample_basic") or 0)
        except (TypeError, ValueError):
            return Response(
                {"ok": False, "error": _("Sample basic pay must be a number.")},
                status=400,
            )
        context = sample_context(sample_basic)
        try:
            result = run_component_formula(expression, context)
        except ComponentFormulaError as exc:
            return Response({"ok": False, "error": str(exc)}, status=400)
        used = sorted(
            {code for code in context if code in expression.upper()},
            key=lambda code: -len(code),
        )
        return Response(
            {
                "ok": True,
                "result": round(result, 2),
                "used": [
                    {"code": code, "value": round(float(context[code]), 2)} for code in used
                ],
            },
            status=200,
        )


class ComponentLimitPreviewView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        blocked = require_perm(request, "payroll.view_allowance")
        if blocked:
            return blocked
        try:
            ceiling = float(request.data.get("maximum_amount") or request.data.get("ceiling") or 0)
        except (TypeError, ValueError):
            return Response({"detail": _("The ceiling must be a number.")}, status=400)
        basis = request.data.get("maximum_unit") or request.data.get("basis") or ""
        return Response(limit_note_rows(ceiling, basis), status=200)


class ComponentLibraryView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        blocked = require_perm(request, "payroll.view_allowance")
        if blocked:
            return blocked
        titles = set(Allowance.objects.values_list("title", flat=True)) | set(
            Deduction.objects.values_list("title", flat=True)
        )
        rows = []
        for row in library_rows(titles):
            rows.append({key: str(value) if key != "already_loaded" else value for key, value in row.items()})
        return Response(rows, status=200)

    def post(self, request):
        blocked = require_perm(request, "payroll.add_allowance")
        if blocked:
            return blocked
        created = load_components(request.data.get("keys"))
        return Response(
            [
                {
                    "id": component.pk,
                    "title": component.title,
                    "kind": "deduction" if isinstance(component, Deduction) else "allowance",
                }
                for component in created
            ],
            status=201,
        )


def _system_payload(entry):
    row = policy(entry["key"])
    exceptions = []
    if row is not None:
        exceptions = [
            {"employee_id": item.employee_id_id, "value": item.value}
            for item in SystemComponentTaxOverride.objects.filter(system_key=entry["key"])
        ]
    return {
        "key": entry["key"],
        "kind": entry["kind"],
        "title": entry["title"],
        "summary": str(entry.get("summary") or ""),
        "note": str(entry.get("note") or ""),
        "id": row.pk if row else None,
        "editable_fields": list(editable_fields(entry["key"])),
        "is_taxable": getattr(row, "is_taxable", None) if row else None,
        "is_pretax": getattr(row, "is_pretax", None) if row else None,
        "maximum_unit": getattr(row, "maximum_unit", None) if row else None,
        "exceptions": exceptions,
    }


class SystemComponentView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        blocked = require_perm(request, "payroll.view_allowance")
        if blocked:
            return blocked
        return Response([_system_payload(entry) for entry in SYSTEM_COMPONENTS], status=200)

    def put(self, request, key):
        entry = next((item for item in SYSTEM_COMPONENTS if item["key"] == key), None)
        if entry is None:
            return Response({"detail": _("Not found.")}, status=404)
        perm = (
            "payroll.change_allowance"
            if entry["kind"] == "allowance"
            else "payroll.change_deduction"
        )
        blocked = require_perm(request, perm)
        if blocked:
            return blocked
        row = policy(key)
        if row is None:
            return Response({"detail": _("Not found.")}, status=404)
        allowed = set(editable_fields(key)) | {"exception_employee_ids"}
        unknown = set(request.data.keys()) - allowed
        if unknown:
            return Response(
                {"detail": _("Only %(fields)s can be changed.") % {"fields": ", ".join(sorted(allowed))}},
                status=400,
            )
        for field in editable_fields(key):
            if field in request.data:
                setattr(row, field, request.data[field])
        row.save()
        if "exception_employee_ids" in request.data:
            field = tax_field(key)
            default = bool(getattr(row, field)) if field else True
            SystemComponentTaxOverride.objects.filter(system_key=key).delete()
            employees = Employee.objects.filter(
                pk__in=as_id_list(request.data.get("exception_employee_ids"))
            )
            SystemComponentTaxOverride.objects.bulk_create(
                [
                    SystemComponentTaxOverride(
                        system_key=key, employee_id=employee, value=not default
                    )
                    for employee in employees
                ]
            )
        return Response(_system_payload(entry), status=200)


def _filing_payload(filing):
    return {
        "id": filing.pk,
        "filing_status": filing.filing_status,
        "based_on": filing.based_on,
        "use_py": filing.use_py,
        "python_code": filing.python_code,
        "standard_deduction": filing.standard_deduction,
        "rebate_income_limit": filing.rebate_income_limit,
        "rebate_max_amount": filing.rebate_max_amount,
        "cess_percent": filing.cess_percent,
        "description": filing.description,
        "company_id": filing.company_id_id,
        "steps": [str(step) for step in filing.computation_steps],
    }


class FilingStatusView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, pk=None):
        blocked = require_perm(request, "payroll.view_filingstatus")
        if blocked:
            return blocked
        if pk:
            filing = FilingStatus.objects.filter(pk=pk).first()
            if filing is None:
                return Response({"detail": _("Filing status not found.")}, status=404)
            return Response(_filing_payload(filing), status=200)
        pagination = HorillaPageNumberPagination()
        page = pagination.paginate_queryset(FilingStatus.objects.all(), request)
        return pagination.get_paginated_response([_filing_payload(item) for item in page])

    def post(self, request):
        blocked = require_perm(request, "payroll.add_filingstatus")
        if blocked:
            return blocked
        filing = FilingStatus(company_id=company_for(request))
        return _save_filing(filing, request.data, created=True)

    def put(self, request, pk):
        blocked = require_perm(request, "payroll.change_filingstatus")
        if blocked:
            return blocked
        filing = FilingStatus.objects.filter(pk=pk).first()
        if filing is None:
            return Response({"detail": _("Filing status not found.")}, status=404)
        return _save_filing(filing, request.data, created=False)

    def delete(self, request, pk):
        blocked = require_perm(request, "payroll.delete_filingstatus")
        if blocked:
            return blocked
        filing = FilingStatus.objects.filter(pk=pk).first()
        if filing is None:
            return Response({"detail": _("Filing status not found.")}, status=404)
        filing.delete()
        return Response({"status": "deleted"}, status=200)


def _save_filing(filing, data, created):
    for field in (
        "filing_status",
        "based_on",
        "use_py",
        "description",
        "standard_deduction",
        "rebate_income_limit",
        "rebate_max_amount",
        "cess_percent",
    ):
        if field in data:
            setattr(filing, field, data[field])
    if "python_code" in data:
        code = data.get("python_code") or ""
        if not python_formulas_enabled() and not same_formula(filing.python_code, code):
            return Response({"python_code": [str(PYTHON_FORMULAS_OFF_MESSAGE)]}, status=403)
        if code.strip():
            try:
                validate_tax_code(code)
            except TaxCodeValidationError as exc:
                return Response({"python_code": [str(exc)]}, status=400)
        filing.python_code = code
    try:
        filing.full_clean()
        filing.save()
    except ValidationError as exc:
        return validation_response(exc)
    return Response(_filing_payload(filing), status=201 if created else 200)


class FilingStatusPreviewView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        blocked = require_perm(request, "payroll.view_filingstatus")
        if blocked:
            return blocked
        filing = FilingStatus.objects.filter(pk=pk).first()
        if filing is None:
            return Response({"detail": _("Filing status not found.")}, status=404)
        try:
            yearly_income = float(request.data.get("yearly_income") or 0)
        except (TypeError, ValueError):
            return Response(
                {"detail": _("Enter a number for the yearly income.")}, status=400
            )
        try:
            breakdown_data = preview_yearly_tax(filing, yearly_income)
        except TaxComputationError as exc:
            return Response({"detail": str(exc)}, status=400)
        return Response({"ok": True, **breakdown_data}, status=200)


class TaxPackView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        blocked = require_perm(request, "payroll.view_filingstatus")
        if blocked:
            return blocked
        loaded = set(FilingStatus.objects.values_list("filing_status", flat=True))
        return Response(pack_rows(loaded), status=200)

    def post(self, request):
        blocked = require_perm(request, "payroll.add_filingstatus")
        if blocked:
            return blocked
        created = load_tax_packs(request.data.get("keys"))
        return Response({"created": created}, status=201)


class CurrencySettingsView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        blocked = require_perm(request, "payroll.view_payrollsettings")
        if blocked:
            return blocked
        company = company_for(request)
        row, _created = PayrollSettings.objects.get_or_create(company_id=company)
        return Response(
            {
                "id": row.pk,
                "currency_symbol": row.currency_symbol,
                "position": row.position,
                "company_id": row.company_id_id,
            },
            status=200,
        )

    def put(self, request):
        blocked = require_perm(request, "payroll.change_payrollsettings")
        if blocked:
            return blocked
        company = company_for(request)
        row, _created = PayrollSettings.objects.get_or_create(company_id=company)
        if "currency_symbol" in request.data:
            row.currency_symbol = request.data.get("currency_symbol") or "$"
        if "position" in request.data:
            row.position = request.data.get("position") or "postfix"
        row.save()
        PayrollSettings.forget_remembered()
        return Response(
            {
                "id": row.pk,
                "currency_symbol": row.currency_symbol,
                "position": row.position,
                "company_id": row.company_id_id,
            },
            status=200,
        )


def _contribution_payslips(request, start, end):
    queryset = Payslip.objects.filter(start_date__gte=start, end_date__lte=end)
    status = request.GET.get("status") or ""
    if status:
        queryset = queryset.filter(status=status)
    return queryset


class ContributionView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, component_id=None):
        blocked = require_perm(request, "payroll.view_payslip")
        if blocked:
            return blocked
        settings = PayPeriodSettings.for_company(company_for(request))
        default_start, default_end = settings.period_for(date.today())
        start = parse_date(request.GET.get("start_date")) or default_start
        end = parse_date(request.GET.get("end_date")) or default_end
        payslips = _contribution_payslips(request, start, end)
        if component_id:
            component = Deduction.objects.entire().filter(pk=component_id).first()
            if component is None:
                return Response({"detail": _("Deduction not found.")}, status=404)
            lines = []
            for line in breakdown(payslips, component_id):
                lines.append(
                    {
                        "payslip_id": line["payslip"].pk,
                        "employee": employee_brief(line["employee"]),
                        "start_date": line["start_date"],
                        "end_date": line["end_date"],
                        "status": line["status"],
                        "basis": line["basis"],
                        "employee_amount": line["employee_amount"],
                        "employer_amount": line["employer_amount"],
                        "total": line["total"],
                    }
                )
            return Response(
                {
                    "id": component.pk,
                    "title": component.title,
                    "period_start": start,
                    "period_end": end,
                    "lines": lines,
                },
                status=200,
            )
        rows, totals = summarise(payslips)
        return Response(
            {
                "period_start": start,
                "period_end": end,
                "totals": totals,
                "rows": [
                    {
                        "id": row["id"],
                        "title": row["title"],
                        "basis": str(row["basis"] or ""),
                        "employee_rate": row["employee_rate"],
                        "employer_rate": row["employer_rate"],
                        "by_formula": row["by_formula"],
                        "employee_amount": row["employee_amount"],
                        "employer_amount": row["employer_amount"],
                        "total": row["total"],
                        "employees": row["employees"],
                        "dormant": row["dormant"],
                    }
                    for row in rows
                ],
            },
            status=200,
        )


class ContractStatusView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, pk=None):
        blocked = require_perm(request, "payroll.change_contract")
        if blocked:
            return blocked
        status = request.data.get("status")
        choices = dict(Contract.CONTRACT_STATUS_CHOICES)
        if status not in choices:
            return Response({"status": [_("Invalid status.")]}, status=400)
        if pk:
            contracts = Contract.objects.filter(pk=pk)
        else:
            contracts = Contract.objects.filter(pk__in=as_id_list(request.data.get("ids")))
        updated, skipped = [], []
        for contract in contracts:
            clash = (
                status in ("active", "draft")
                and Contract.objects.filter(
                    contract_status=status, employee_id=contract.employee_id
                )
                .exclude(pk=contract.pk)
                .exists()
            )
            if clash:
                skipped.append(contract.pk)
                continue
            contract.contract_status = status
            contract.save()
            updated.append(contract.pk)
        return Response({"updated": updated, "skipped": skipped, "status": status}, status=200)


class ContractComponentView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, pk):
        blocked = require_perm(request, "payroll.view_contract")
        if blocked:
            return blocked
        contract = Contract.objects.filter(pk=pk).first()
        if contract is None:
            return Response({"detail": _("Contract not found.")}, status=404)
        rows = []
        for row in _rows_for(contract):
            component = row["component"]
            rows.append(
                {
                    "kind": row["kind"],
                    "id": row["pk"],
                    "title": component.title,
                    "code": component.code,
                    "checked": row["checked"],
                    "locked": row["locked"],
                    "source_label": str(row["source_label"]),
                    "standard": row["standard"],
                }
            )
        return Response({"contract_id": contract.pk, "rows": rows}, status=200)

    def post(self, request, pk):
        blocked = require_perm(request, "payroll.change_contract")
        if blocked:
            return blocked
        contract = Contract.objects.filter(pk=pk).first()
        if contract is None:
            return Response({"detail": _("Contract not found.")}, status=404)
        wanted = set(request.data.get("components") or [])
        employee = contract.employee_id
        added = removed = 0
        for row in _rows_for(contract):
            if row["locked"]:
                continue
            token = f"{row['kind']}:{row['pk']}"
            should_apply = token in wanted
            if should_apply and not row["checked"]:
                row["component"].specific_employees.add(employee)
                added += 1
            elif not should_apply and row["checked"]:
                row["component"].specific_employees.remove(employee)
                removed += 1
        return Response({"added": added, "removed": removed}, status=200)


class LoanInstallmentView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, pk):
        blocked = require_perm(request, "payroll.view_loanaccount")
        if blocked:
            return blocked
        loan = LoanAccount.objects.filter(pk=pk).first()
        if loan is None:
            return Response({"detail": _("Loan not found.")}, status=404)
        rows = []
        for deduction in loan.deduction_ids.all().order_by("one_time_date"):
            payslip = deduction.installment_payslip
            rows.append(
                {
                    "id": deduction.pk,
                    "title": deduction.title,
                    "amount": deduction.amount,
                    "one_time_date": deduction.one_time_date,
                    "paid": bool(payslip),
                    "payslip_id": payslip.pk if payslip else None,
                }
            )
        return Response({"loan_id": loan.pk, "installments": rows}, status=200)

    def put(self, request, pk, deduction_id):
        blocked = require_perm(request, "payroll.change_loanaccount")
        if blocked:
            return blocked
        loan = LoanAccount.objects.filter(pk=pk).first()
        if loan is None:
            return Response({"detail": _("Loan not found.")}, status=404)
        try:
            value = float(request.data.get("amount"))
        except (TypeError, ValueError):
            return Response({"amount": [_("Amount is required.")]}, status=400)
        deductions = loan.deduction_ids.all().order_by("one_time_date")
        deduction = deductions.filter(id=deduction_id).first()
        if deduction is None:
            return Response({"detail": _("Installment not found.")}, status=404)
        if deduction.installment_payslip:
            return Response({"detail": _("Cannot change a paid installment.")}, status=400)
        before = deductions.filter(one_time_date__lt=deduction.one_time_date)
        after = deductions.filter(one_time_date__gt=deduction.one_time_date)
        total_sum = before.aggregate(Sum("amount"))["amount__sum"] or 0
        balance = len(after) or 1
        new_installment = round((loan.loan_amount - total_sum - value) / balance, 2)
        if total_sum + value > loan.loan_amount:
            value = loan.loan_amount - total_sum
            new_installment = 0
        deduction.amount = value
        deduction.save()
        for item in deductions.filter(one_time_date__gt=deduction.one_time_date):
            if new_installment > 0:
                item.amount = new_installment
                item.save()
            else:
                item.delete()
                loan.deduction_ids.remove(item)
        if len(after) == 0 and new_installment != 0:
            if loan.installment_start_date:
                when = get_nth_month_same_date(
                    loan.installment_start_date, len(loan.deduction_ids.all())
                )
            else:
                when = get_next_month_same_date(deduction.one_time_date)
            installment = create_deductions(loan, new_installment, when)
            loan.deduction_ids.add(installment)
        LoanAccount.objects.filter(pk=loan.pk).update(
            installments=loan.deduction_ids.count()
        )
        return self.get(request, pk)


class ReimbursementCommentView(APIView):
    permission_classes = [IsAuthenticated]

    def _reimbursement(self, pk):
        return Reimbursement.objects.filter(pk=pk).first()

    def _allowed(self, request, reimbursement, write):
        employee = getattr(request.user, "employee_get", None)
        if employee and reimbursement.employee_id_id == getattr(employee, "pk", None):
            return None
        perm = "payroll.change_reimbursement" if write else "payroll.view_reimbursement"
        return require_perm(request, perm)

    def get(self, request, pk):
        reimbursement = self._reimbursement(pk)
        if reimbursement is None:
            return Response({"detail": _("Not found.")}, status=404)
        blocked = self._allowed(request, reimbursement, write=False)
        if blocked:
            return blocked
        comments = reimbursement.reimbursementrequestcomment_set.select_related(
            "employee_id"
        )
        return Response(
            [
                {
                    "id": comment.pk,
                    "comment": comment.comment,
                    "employee": employee_brief(comment.employee_id),
                    "created_at": comment.created_at,
                }
                for comment in comments
            ],
            status=200,
        )

    def post(self, request, pk):
        reimbursement = self._reimbursement(pk)
        if reimbursement is None:
            return Response({"detail": _("Not found.")}, status=404)
        blocked = self._allowed(request, reimbursement, write=True)
        if blocked:
            return blocked
        employee = getattr(request.user, "employee_get", None)
        if employee is None:
            return Response({"detail": _("No employee is linked to this user.")}, status=400)
        text = (request.data.get("comment") or "").strip()
        if not text:
            return Response({"comment": [_("Comment is required.")]}, status=400)
        comment = ReimbursementrequestComment.objects.create(
            request_id=reimbursement, employee_id=employee, comment=text
        )
        return Response(
            {
                "id": comment.pk,
                "comment": comment.comment,
                "employee": employee_brief(employee),
                "created_at": comment.created_at,
            },
            status=201,
        )


class ReimbursementCommentDeleteView(APIView):
    permission_classes = [IsAuthenticated]

    def delete(self, request, pk):
        comment = ReimbursementrequestComment.objects.filter(pk=pk).first()
        if comment is None:
            return Response({"detail": _("Not found.")}, status=404)
        employee = getattr(request.user, "employee_get", None)
        owns = employee and comment.employee_id_id == employee.pk
        if not owns:
            blocked = require_perm(request, "payroll.change_reimbursement")
            if blocked:
                return blocked
        comment.delete()
        return Response({"status": "deleted"}, status=200)


class EncashmentSettingsView(APIView):
    permission_classes = [IsAuthenticated]

    def _payload(self, row):
        return {
            "id": row.pk,
            "bonus_amount": row.bonus_amount,
            "leave_amount": row.leave_amount,
            "leave_encashment_enabled": row.leave_encashment_enabled,
            "is_applicable_to_all": row.is_applicable_to_all,
            "employee_ids": list(row.employees.values_list("pk", flat=True)),
            "department_ids": list(row.department.values_list("pk", flat=True)),
            "job_position_ids": list(row.job_position.values_list("pk", flat=True)),
        }

    def get(self, request):
        blocked = require_perm(request, "payroll.view_reimbursement")
        if blocked:
            return blocked
        row = EncashmentGeneralSettings.objects.first()
        if row is None:
            row = EncashmentGeneralSettings.objects.create()
        return Response(self._payload(row), status=200)

    def put(self, request):
        blocked = require_perm(request, "payroll.change_encashmentgeneralsettings")
        if blocked:
            return blocked
        row = EncashmentGeneralSettings.objects.first()
        if row is None:
            row = EncashmentGeneralSettings.objects.create()
        for field in (
            "bonus_amount",
            "leave_amount",
            "leave_encashment_enabled",
            "is_applicable_to_all",
        ):
            if field in request.data:
                setattr(row, field, request.data[field])
        row.save()
        from base.models import Department, JobPosition

        if "employee_ids" in request.data:
            row.employees.set(as_id_list(request.data.get("employee_ids")))
        if "department_ids" in request.data:
            row.department.set(
                Department.objects.filter(pk__in=as_id_list(request.data.get("department_ids")))
            )
        if "job_position_ids" in request.data:
            row.job_position.set(
                JobPosition.objects.filter(
                    pk__in=as_id_list(request.data.get("job_position_ids"))
                )
            )
        return Response(self._payload(row), status=200)
