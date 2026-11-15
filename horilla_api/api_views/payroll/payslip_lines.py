"""Correct one payslip's stored lines, and delete slips that are still open."""

from django.shortcuts import get_object_or_404
from django.utils.translation import gettext as _
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from payroll.methods.component_formula import ComponentFormulaError, run_component_formula
from payroll.methods.payslip_edit import (
    NewLineError,
    apply_edits,
    described_lines,
    editable_lines,
    formula_context,
    formula_codes,
    parse_amounts,
    parse_new_line,
    recompute_dependents,
    salary_adjustments,
    tax_explanation,
    taxable_loss_of_pay,
)
from payroll.models.models import Payslip

from .common import as_id_list, payslip_edit_block, require_perm


class _FormPost(dict):
    def getlist(self, key):
        value = dict.get(self, key, [])
        if isinstance(value, (list, tuple)):
            return list(value)
        if value in (None, ""):
            return []
        return [value]


def _form_post(data):
    post = _FormPost()
    for key, value in (data.get("amounts") or {}).items():
        post[f"amount:{key}"] = value
    post["remove"] = data.get("remove") or []
    post["given"] = data.get("given") or []
    new_line = data.get("new_line") or {}
    post["new_title"] = new_line.get("title") or ""
    amount = new_line.get("amount")
    post["new_amount"] = "" if amount is None else str(amount)
    post["new_formula"] = new_line.get("formula") or ""
    post["new_section"] = new_line.get("section") or "earning"
    return post


def _open_payslip(request, payslip_id):
    payslip = Payslip.objects.filter(pk=payslip_id).first()
    if payslip is None:
        return None, Response({"detail": _("Payslip not found.")}, status=404)
    blocked = payslip_edit_block(payslip)
    if blocked:
        return None, blocked
    return payslip, None


class PayslipLinesView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, payslip_id):
        blocked = require_perm(request, "payroll.view_payslip")
        if blocked:
            return blocked
        payslip = get_object_or_404(Payslip, pk=payslip_id)
        lines = editable_lines(payslip)
        amounts = {line["key"]: line["amount"] for line in lines}
        gross = sum(
            float(line["amount"] or 0) for line in lines if line["section"] == "earning"
        )
        explained = tax_explanation(
            payslip, described_lines(payslip), amounts, set(), gross
        )
        return Response(
            {
                "lines": lines,
                "adjustments": salary_adjustments(payslip),
                "taxable_lop": (
                    0.0
                    if any(line["key"] == "lop" for line in lines)
                    else taxable_loss_of_pay(payslip)
                ),
                "formula_codes": formula_codes(payslip),
                "tax": explained,
                "locked": bool(payslip.status_locked or payslip.status == "paid"),
            },
            status=200,
        )


class PayslipLinePreviewView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, payslip_id):
        blocked = require_perm(request, "payroll.change_payslip")
        if blocked:
            return blocked
        payslip = get_object_or_404(Payslip, pk=payslip_id)
        expression = request.data.get("formula") or ""
        context = formula_context(payslip)
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
                "expression": expression,
                "used": [
                    {"code": code, "value": round(float(context[code]), 2)} for code in used
                ],
            },
            status=200,
        )


class PayslipLineApplyView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, payslip_id):
        blocked = require_perm(request, "payroll.change_payslip")
        if blocked:
            return blocked
        payslip, error = _open_payslip(request, payslip_id)
        if error:
            return error
        lines = editable_lines(payslip)
        post = _form_post(request.data)
        amounts = parse_amounts(post, lines)
        removed = {
            key
            for key in post.getlist("remove")
            if any(line["key"] == key and line["removable"] for line in lines)
        }
        try:
            new_line = parse_new_line(post, payslip)
        except NewLineError as exc:
            return Response({"new_line": [str(exc)]}, status=400)
        apply_edits(payslip, amounts, removed, new_line=new_line)
        payslip.refresh_from_db()
        return Response(
            {
                "id": payslip.pk,
                "basic_pay": payslip.basic_pay,
                "gross_pay": payslip.gross_pay,
                "deduction": payslip.deduction,
                "net_pay": payslip.net_pay,
                "pay_head_data": payslip.pay_head_data,
            },
            status=200,
        )


class PayslipLineRecalculateView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, payslip_id):
        blocked = require_perm(request, "payroll.change_payslip")
        if blocked:
            return blocked
        payslip = get_object_or_404(Payslip, pk=payslip_id)
        lines = editable_lines(payslip)
        post = _form_post(request.data)
        amounts = parse_amounts(post, lines)
        removed = {
            key
            for key in post.getlist("remove")
            if any(line["key"] == key and line["removable"] for line in lines)
        }
        given = {key for key in post.getlist("given") if any(line["key"] == key for line in lines)}
        recomputed = recompute_dependents(payslip, amounts, removed=removed, given=given)
        final = {**amounts, **recomputed}
        gross = sum(
            float(final.get(line["key"], line["amount"]) or 0)
            for line in lines
            if line["section"] == "earning" and line["key"] not in removed
        )
        explained = tax_explanation(
            payslip, described_lines(payslip), final, removed, gross
        )
        return Response(
            {
                "ok": True,
                "amounts": {key: round(value, 2) for key, value in recomputed.items()},
                "tax": explained,
            },
            status=200,
        )


class PayslipBulkDeleteView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        blocked = require_perm(request, "payroll.delete_payslip")
        if blocked:
            return blocked
        ids = as_id_list(request.data.get("ids"))
        if not ids:
            return Response({"ids": [_("Select at least one payslip.")]}, status=400)
        deleted = []
        skipped = []
        for payslip in Payslip.objects.filter(id__in=ids):
            if payslip.status == "paid" or payslip.status_locked:
                skipped.append(payslip.pk)
                continue
            deleted.append(payslip.pk)
            payslip.delete()
        return Response({"deleted": deleted, "skipped": skipped}, status=200)
