"""
Company GL codes for payroll accounting export lines.

Horilla does not keep a chart of accounts. Each row maps a catalog ``line_key``
(from ``payroll.accounting_components``) to a code the bookkeeper uses when
importing the CSV into their ledger.
"""

from django.db import models
from django.utils.translation import gettext_lazy as _

from base.horilla_company_manager import HorillaCompanyManager
from base.models import Company
from horilla.models import HorillaModel


class PayrollGLMapping(HorillaModel):
    """One GL code for one accounting line key, per company."""

    company_id = models.ForeignKey(
        Company,
        on_delete=models.CASCADE,
        verbose_name=_("Company"),
    )
    line_key = models.CharField(max_length=80, verbose_name=_("Line key"))
    gl_code = models.CharField(
        max_length=64,
        blank=True,
        default="",
        verbose_name=_("GL code"),
    )
    label = models.CharField(
        max_length=120,
        blank=True,
        default="",
        verbose_name=_("Label"),
    )

    objects = HorillaCompanyManager("company_id")

    class Meta:
        verbose_name = _("Payroll GL mapping")
        verbose_name_plural = _("Payroll GL mappings")
        unique_together = ("company_id", "line_key")

    def __str__(self):
        return f"{self.line_key} → {self.gl_code or '—'}"
