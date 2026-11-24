"""
A pay period as a record that someone opens and closes.

``PayPeriodSettings`` says how long a period is; it never said which period a
company was *in*. Every screen answered that with today's date, so the day
after a cycle ended the system moved on by itself, with the old period still
unpaid and its inputs still being entered. A period is now a row: it stays
open until it is closed, closing needs its payroll paid, and the next one
cannot be opened while one is open.

Closed periods are locked (see ``payroll/methods/period_lock.py``). Reopening
is the one way back in, kept for corrections and allowed only for the latest
closed period.
"""

from datetime import date, timedelta

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models, transaction
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from base.horilla_company_manager import HorillaCompanyManager
from base.models import Company
from horilla.models import HorillaModel


class PayPeriod(HorillaModel):
    """One company's pay period: its dates, and whether it is still open."""

    OPEN = "open"
    CLOSED = "closed"
    STATUS_CHOICES = [(OPEN, _("Open")), (CLOSED, _("Closed"))]

    company_id = models.ForeignKey(
        Company,
        on_delete=models.PROTECT,
        related_name="pay_periods",
        verbose_name=_("Company"),
    )
    start_date = models.DateField(verbose_name=_("Start date"))
    end_date = models.DateField(verbose_name=_("End date"))
    status = models.CharField(
        max_length=10, choices=STATUS_CHOICES, default=OPEN, db_index=True
    )
    closed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        editable=False,
        on_delete=models.SET_NULL,
        related_name="+",
    )
    closed_on = models.DateTimeField(null=True, blank=True, editable=False)
    reopened_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        editable=False,
        on_delete=models.SET_NULL,
        related_name="+",
    )
    reopened_on = models.DateTimeField(null=True, blank=True, editable=False)

    objects = HorillaCompanyManager("company_id")

    class Meta:
        ordering = ["-start_date"]
        verbose_name = _("Pay Period")
        verbose_name_plural = _("Pay Periods")
        permissions = [("reopen_payperiod", "Can reopen a closed pay period")]
        constraints = [
            models.UniqueConstraint(
                fields=["company_id", "start_date"], name="pay_period_company_start"
            ),
            models.CheckConstraint(
                check=models.Q(end_date__gte=models.F("start_date")),
                name="pay_period_end_after_start",
            ),
        ]

    def __str__(self):
        return f"{self.company_id}: {self.start_date} — {self.end_date}"

    # ---- lookups: never scoped by the request, a period belongs to its company ----
    @classmethod
    def of(cls, company):
        company_id = getattr(company, "pk", company)
        return cls.objects.entire().filter(company_id=company_id)

    @classmethod
    def current(cls, company):
        """The period a company is working in: its earliest open one, or None."""
        if company is None:
            return None
        return cls.of(company).filter(status=cls.OPEN).order_by("start_date").first()

    @classmethod
    def latest(cls, company):
        return cls.of(company).order_by("-end_date").first()

    @classmethod
    def closed_covering(cls, company, start, end=None):
        """The first closed period of ``company`` that any of these days falls in."""
        if company is None or start is None:
            return None
        return (
            cls.of(company)
            .filter(
                status=cls.CLOSED, start_date__lte=end or start, end_date__gte=start
            )
            .order_by("start_date")
            .first()
        )

    @classmethod
    def dates_for(cls, company, today=None):
        """``(start, end)`` every screen defaults to: the open period, else the cycle today is in."""
        from payroll.models.payroll_batch import PayPeriodSettings

        period = cls.current(company)
        if period is not None:
            return period.start_date, period.end_date
        return PayPeriodSettings.for_company(company).period_for(today or date.today())

    # ---- opening ----
    @classmethod
    def _earliest_unposted_task_day(cls, company):
        from project.models import Task

        company_id = getattr(company, "pk", company)
        return (
            Task.objects.entire()
            .filter(
                project__company_id=company_id,
                is_payable=True,
                status="completed",
                completed_at__isnull=False,
                payroll_adjustment__isnull=True,
            )
            .order_by("completed_at")
            .values_list("completed_at", flat=True)
            .first()
        )

    @classmethod
    def suggest_next(cls, company, today=None):
        """
        ``(start, end, follows)`` for the period to open next.

        After an earlier period the start is fixed: the day after it ended.
        A company's first period starts where its oldest unposted payable work
        is, so that work is not stranded before the first period.
        """
        from payroll.models.payroll_batch import PayPeriodSettings

        cycle = PayPeriodSettings.for_company(company)
        last = cls.latest(company)
        if last is not None:
            start = last.end_date + timedelta(days=1)
            return start, cycle.period_for(start)[1], True
        anchor = cls._earliest_unposted_task_day(company) or today or date.today()
        start, end = cycle.period_for(anchor)
        return start, end, False

    @classmethod
    @transaction.atomic
    def open_next(cls, company, start, end, user=None):
        """Open the next period, or raise ``ValidationError`` saying why not."""
        if company is None:
            raise ValidationError({"company": _("Choose a company first.")})
        still_open = cls.current(company)
        if still_open is not None:
            raise ValidationError(
                {
                    "detail": _(
                        "The period %(start)s to %(end)s is still open. Close it before opening another."
                    )
                    % {"start": still_open.start_date, "end": still_open.end_date}
                }
            )
        if start is None or end is None:
            raise ValidationError({"end_date": _("Enter the period's dates.")})
        if end < start:
            raise ValidationError(
                {"end_date": _("The end date must be on or after the start date.")}
            )
        last = cls.latest(company)
        if last is not None and start != last.end_date + timedelta(days=1):
            raise ValidationError(
                {
                    "start_date": _(
                        "The next period must start on %(day)s, the day after the last one ended."
                    )
                    % {"day": last.end_date + timedelta(days=1)}
                }
            )
        if cls.of(company).filter(start_date__lte=end, end_date__gte=start).exists():
            raise ValidationError(
                {"start_date": _("These dates overlap an earlier pay period.")}
            )
        period = cls(start_date=start, end_date=end, status=cls.OPEN)
        period.company_id_id = getattr(company, "pk", company)
        period.save()
        return period

    # ---- closing ----
    def _unpaid_batches(self):
        from payroll.models.payroll_batch import PayrollBatch

        return (
            PayrollBatch.objects.entire()
            .filter(
                models.Q(company_id=self.company_id_id)
                | models.Q(company_id__isnull=True),
                period_start__lte=self.end_date,
                period_end__gte=self.start_date,
            )
            .exclude(status__in=[PayrollBatch.PAID, PayrollBatch.CANCELLED])
        )

    def _batches(self):
        from payroll.models.payroll_batch import PayrollBatch

        return PayrollBatch.objects.entire().filter(
            company_id=self.company_id_id,
            period_start__lte=self.end_date,
            period_end__gte=self.start_date,
            status=PayrollBatch.PAID,
        )

    def _draft_adjustments(self):
        from payroll.models.models import PayAdjustment

        return PayAdjustment.objects.entire().filter(
            employee_id__employee_work_info__company_id=self.company_id_id,
            pay_date__gte=self.start_date,
            pay_date__lte=self.end_date,
            status="draft",
        )

    def _unposted_tasks(self):
        from project.models import Task

        return Task.objects.entire().filter(
            project__company_id=self.company_id_id,
            is_payable=True,
            status="completed",
            completed_at__gte=self.start_date,
            completed_at__lte=self.end_date,
            payroll_adjustment__isnull=True,
        )

    def close_blockers(self):
        """What must be finished first. Empty means the period can be closed."""
        found = []
        unpaid = self._unpaid_batches().count()
        if unpaid:
            found.append(
                {
                    "code": "unpaid_runs",
                    "count": unpaid,
                    "message": str(
                        _("%(count)s payroll run(s) for these dates are not paid yet.")
                        % {"count": unpaid}
                    ),
                }
            )
        drafts = self._draft_adjustments().count()
        if drafts:
            found.append(
                {
                    "code": "draft_adjustments",
                    "count": drafts,
                    "message": str(
                        _(
                            "%(count)s arrears or recovery entries are still drafts. Confirm or delete them."
                        )
                        % {"count": drafts}
                    ),
                }
            )
        return found

    def close_warnings(self):
        """Worth knowing before closing, but not a reason to refuse."""
        found = []
        unposted = self._unposted_tasks().count()
        if unposted:
            found.append(
                {
                    "code": "unposted_tasks",
                    "count": unposted,
                    "message": str(
                        _(
                            "%(count)s completed payable task(s) in this period have not been posted to payroll."
                        )
                        % {"count": unposted}
                    ),
                }
            )
        if not self._batches().exists():
            found.append(
                {
                    "code": "no_payroll",
                    "count": 0,
                    "message": str(_("No payroll has been paid for this period.")),
                }
            )
        return found

    @transaction.atomic
    def close(self, user=None):
        if self.status == self.CLOSED:
            raise ValidationError({"detail": _("This period is already closed.")})
        blockers = self.close_blockers()
        if blockers:
            raise ValidationError(
                {"detail": [blocker["message"] for blocker in blockers]}
            )
        self.status = self.CLOSED
        self.closed_by = user if getattr(user, "pk", None) else None
        self.closed_on = timezone.now()
        self.save(update_fields=["status", "closed_by", "closed_on"])
        return self

    # ---- reopening ----
    def reopen_refusal(self):
        """Why this period cannot be reopened, or None."""
        if self.status != self.CLOSED:
            return _("This period is not closed.")
        later_closed = (
            type(self)
            .of(self.company_id_id)
            .filter(status=self.CLOSED, start_date__gt=self.start_date)
            .exists()
        )
        if later_closed:
            return _(
                "A later period has been closed since. Put the correction in the open period as arrears or a recovery."
            )
        return None

    @transaction.atomic
    def reopen(self, user=None):
        refusal = self.reopen_refusal()
        if refusal:
            raise ValidationError({"detail": refusal})
        self.status = self.OPEN
        self.reopened_by = user if getattr(user, "pk", None) else None
        self.reopened_on = timezone.now()
        self.save(update_fields=["status", "reopened_by", "reopened_on"])
        return self
