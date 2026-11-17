"""Occupational Health and Safety domain models (Imara v1, Uganda-first)."""

from django.db import models
from django.utils.translation import gettext_lazy as _

from base.horilla_company_manager import HorillaCompanyManager
from base.models import Company
from employee.models import Employee
from horilla.models import HorillaModel, upload_path


JURISDICTION_CHOICES = [
    ("UG", _("Uganda")),
    ("KE", _("Kenya")),
    ("OTHER", _("Other")),
]

EVENT_TYPE_CHOICES = [
    ("accident", _("Accident")),
    ("near_miss", _("Near miss / incident")),
    ("occupational_disease", _("Occupational disease")),
]

EVENT_STATUS_CHOICES = [
    ("reported", _("Reported")),
    ("under_investigation", _("Under investigation")),
    ("awaiting_notification", _("Awaiting authority notification")),
    ("closed", _("Closed")),
]

SEVERITY_CHOICES = [
    ("low", _("Low")),
    ("medium", _("Medium")),
    ("high", _("High")),
    ("fatal", _("Fatal")),
]

NOTIFICATION_CHANNEL_CHOICES = [
    ("phone", _("Phone")),
    ("email", _("Email")),
    ("in_person", _("In person")),
    ("letter", _("Letter")),
    ("other", _("Other")),
]

CAPA_STATUS_CHOICES = [
    ("open", _("Open")),
    ("in_progress", _("In progress")),
    ("done", _("Done")),
    ("cancelled", _("Cancelled")),
]

MEDICAL_EXAM_TYPE_CHOICES = [
    ("pre_assignment", _("Pre-assignment")),
    ("periodic", _("Periodic")),
    ("post_assignment", _("Post-assignment")),
    ("post_accident", _("Post-accident")),
    ("other", _("Other")),
]

FITNESS_CHOICES = [
    ("fit", _("Fit")),
    ("fit_with_restrictions", _("Fit with restrictions")),
    ("unfit", _("Unfit")),
    ("pending", _("Pending")),
]

PPE_CONDITION_CHOICES = [
    ("new", _("New")),
    ("good", _("Good")),
    ("fair", _("Fair")),
    ("poor", _("Poor")),
    ("damaged", _("Damaged")),
]


class OshWorkplace(HorillaModel):
    """Registered workplace / site (Uganda OSH registration certificate)."""

    name = models.CharField(max_length=200, verbose_name=_("Workplace name"))
    company_id = models.ForeignKey(
        Company,
        on_delete=models.PROTECT,
        related_name="osh_workplaces",
        verbose_name=_("Company"),
    )
    jurisdiction = models.CharField(
        max_length=10,
        choices=JURISDICTION_CHOICES,
        default="UG",
        verbose_name=_("Jurisdiction"),
    )
    address = models.TextField(blank=True, verbose_name=_("Address"))
    registration_number = models.CharField(
        max_length=100, blank=True, verbose_name=_("Registration number")
    )
    certificate = models.FileField(
        upload_to=upload_path,
        null=True,
        blank=True,
        verbose_name=_("Registration certificate"),
    )
    registered_on = models.DateField(
        null=True, blank=True, verbose_name=_("Registered on")
    )
    expires_on = models.DateField(
        null=True,
        blank=True,
        verbose_name=_("Certificate expires on"),
        help_text=_("Uganda SI 87/2014: registration typically renews every 3 years."),
    )
    labour_officer_area = models.CharField(
        max_length=200,
        blank=True,
        verbose_name=_("Labour officer area"),
    )
    notes = models.TextField(blank=True, verbose_name=_("Notes"))

    objects = HorillaCompanyManager("company_id")

    class Meta:
        verbose_name = _("OSH Workplace")
        verbose_name_plural = _("OSH Workplaces")
        ordering = ["name"]

    def __str__(self):
        return self.name


class OshEvent(HorillaModel):
    """Accident, near-miss, or occupational disease case."""

    workplace = models.ForeignKey(
        OshWorkplace,
        on_delete=models.PROTECT,
        related_name="events",
        verbose_name=_("Workplace"),
    )
    event_type = models.CharField(
        max_length=32, choices=EVENT_TYPE_CHOICES, verbose_name=_("Event type")
    )
    title = models.CharField(max_length=200, verbose_name=_("Title"))
    description = models.TextField(verbose_name=_("Description"))
    occurred_at = models.DateTimeField(verbose_name=_("Occurred at"))
    location_detail = models.CharField(
        max_length=255, blank=True, verbose_name=_("Location detail")
    )
    employee = models.ForeignKey(
        Employee,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="osh_events",
        verbose_name=_("Affected employee"),
    )
    reported_by = models.ForeignKey(
        Employee,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="osh_events_reported",
        verbose_name=_("Reported by"),
    )
    severity = models.CharField(
        max_length=16,
        choices=SEVERITY_CHOICES,
        default="medium",
        verbose_name=_("Severity"),
    )
    status = models.CharField(
        max_length=32,
        choices=EVENT_STATUS_CHOICES,
        default="reported",
        verbose_name=_("Status"),
    )
    injury_occurred = models.BooleanField(
        default=False, verbose_name=_("Injury occurred")
    )
    days_lost = models.PositiveIntegerField(
        null=True, blank=True, verbose_name=_("Days lost")
    )
    fatality = models.BooleanField(default=False, verbose_name=_("Fatality"))
    compensable = models.BooleanField(
        default=False,
        verbose_name=_("Compensable"),
        help_text=_("Likely entitles the worker to compensation (Uganda WC Act)."),
    )
    attachment = models.FileField(
        upload_to=upload_path,
        null=True,
        blank=True,
        verbose_name=_("Attachment"),
    )

    objects = HorillaCompanyManager("workplace__company_id")

    class Meta:
        verbose_name = _("OSH Event")
        verbose_name_plural = _("OSH Events")
        ordering = ["-occurred_at"]

    def __str__(self):
        return f"{self.get_event_type_display()}: {self.title}"


class OshNotification(HorillaModel):
    """Authority / labour-officer notification log (Uganda WC s.10)."""

    event = models.ForeignKey(
        OshEvent,
        on_delete=models.CASCADE,
        related_name="notifications",
        verbose_name=_("Event"),
    )
    channel = models.CharField(
        max_length=20,
        choices=NOTIFICATION_CHANNEL_CHOICES,
        default="phone",
        verbose_name=_("Channel"),
    )
    notified_at = models.DateTimeField(verbose_name=_("Initial notification at"))
    written_report_at = models.DateTimeField(
        null=True, blank=True, verbose_name=_("Written report at")
    )
    authority_name = models.CharField(
        max_length=200,
        blank=True,
        verbose_name=_("Authority / labour officer"),
    )
    area = models.CharField(max_length=200, blank=True, verbose_name=_("Area"))
    reference = models.CharField(
        max_length=100, blank=True, verbose_name=_("Reference number")
    )
    notes = models.TextField(blank=True, verbose_name=_("Notes"))
    attachment = models.FileField(
        upload_to=upload_path,
        null=True,
        blank=True,
        verbose_name=_("Written report / evidence"),
    )

    objects = HorillaCompanyManager("event__workplace__company_id")

    class Meta:
        verbose_name = _("OSH Authority Notification")
        verbose_name_plural = _("OSH Authority Notifications")
        ordering = ["-notified_at"]

    def __str__(self):
        return f"Notification for {self.event_id} at {self.notified_at}"


class OshInvestigation(HorillaModel):
    event = models.OneToOneField(
        OshEvent,
        on_delete=models.CASCADE,
        related_name="investigation",
        verbose_name=_("Event"),
    )
    lead = models.ForeignKey(
        Employee,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="osh_investigations_led",
        verbose_name=_("Investigation lead"),
    )
    started_at = models.DateField(null=True, blank=True, verbose_name=_("Started on"))
    completed_at = models.DateField(
        null=True, blank=True, verbose_name=_("Completed on")
    )
    findings = models.TextField(blank=True, verbose_name=_("Findings"))
    root_cause = models.TextField(blank=True, verbose_name=_("Root cause"))

    objects = HorillaCompanyManager("event__workplace__company_id")

    class Meta:
        verbose_name = _("OSH Investigation")
        verbose_name_plural = _("OSH Investigations")

    def __str__(self):
        return f"Investigation #{self.pk} for event {self.event_id}"


class OshCorrectiveAction(HorillaModel):
    event = models.ForeignKey(
        OshEvent,
        on_delete=models.CASCADE,
        related_name="corrective_actions",
        verbose_name=_("Event"),
    )
    investigation = models.ForeignKey(
        OshInvestigation,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="actions",
        verbose_name=_("Investigation"),
    )
    title = models.CharField(max_length=200, verbose_name=_("Action"))
    description = models.TextField(blank=True, verbose_name=_("Description"))
    owner = models.ForeignKey(
        Employee,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="osh_corrective_actions",
        verbose_name=_("Owner"),
    )
    due_on = models.DateField(null=True, blank=True, verbose_name=_("Due on"))
    completed_on = models.DateField(
        null=True, blank=True, verbose_name=_("Completed on")
    )
    status = models.CharField(
        max_length=20,
        choices=CAPA_STATUS_CHOICES,
        default="open",
        verbose_name=_("Status"),
    )

    objects = HorillaCompanyManager("event__workplace__company_id")

    class Meta:
        verbose_name = _("OSH Corrective Action")
        verbose_name_plural = _("OSH Corrective Actions")
        ordering = ["status", "due_on"]

    def __str__(self):
        return self.title


class OshPolicy(HorillaModel):
    workplace = models.ForeignKey(
        OshWorkplace,
        on_delete=models.CASCADE,
        related_name="policies",
        verbose_name=_("Workplace"),
    )
    title = models.CharField(max_length=200, verbose_name=_("Title"))
    version = models.CharField(max_length=50, blank=True, verbose_name=_("Version"))
    effective_on = models.DateField(verbose_name=_("Effective on"))
    document = models.FileField(
        upload_to=upload_path,
        null=True,
        blank=True,
        verbose_name=_("Policy document"),
    )
    notes = models.TextField(blank=True, verbose_name=_("Notes"))

    objects = HorillaCompanyManager("workplace__company_id")

    class Meta:
        verbose_name = _("OSH Policy")
        verbose_name_plural = _("OSH Policies")
        ordering = ["-effective_on"]

    def __str__(self):
        return f"{self.title} ({self.version or self.effective_on})"


class OshPolicyAcknowledgement(HorillaModel):
    policy = models.ForeignKey(
        OshPolicy,
        on_delete=models.CASCADE,
        related_name="acknowledgements",
        verbose_name=_("Policy"),
    )
    employee = models.ForeignKey(
        Employee,
        on_delete=models.CASCADE,
        related_name="osh_policy_acknowledgements",
        verbose_name=_("Employee"),
    )
    acknowledged_at = models.DateTimeField(verbose_name=_("Acknowledged at"))

    objects = HorillaCompanyManager("policy__workplace__company_id")

    class Meta:
        verbose_name = _("OSH Policy Acknowledgement")
        verbose_name_plural = _("OSH Policy Acknowledgements")
        unique_together = [("policy", "employee")]

    def __str__(self):
        return f"{self.employee_id} ack {self.policy_id}"


class OshSafetyCommittee(HorillaModel):
    workplace = models.ForeignKey(
        OshWorkplace,
        on_delete=models.CASCADE,
        related_name="committees",
        verbose_name=_("Workplace"),
    )
    name = models.CharField(max_length=200, verbose_name=_("Committee name"))
    formed_on = models.DateField(null=True, blank=True, verbose_name=_("Formed on"))
    members = models.ManyToManyField(
        Employee,
        blank=True,
        related_name="osh_committees",
        verbose_name=_("Members"),
    )
    notes = models.TextField(blank=True, verbose_name=_("Notes"))

    objects = HorillaCompanyManager("workplace__company_id")

    class Meta:
        verbose_name = _("OSH Safety Committee")
        verbose_name_plural = _("OSH Safety Committees")

    def __str__(self):
        return self.name


class OshCommitteeMeeting(HorillaModel):
    committee = models.ForeignKey(
        OshSafetyCommittee,
        on_delete=models.CASCADE,
        related_name="meetings",
        verbose_name=_("Committee"),
    )
    held_on = models.DateField(verbose_name=_("Held on"))
    agenda = models.TextField(blank=True, verbose_name=_("Agenda"))
    minutes = models.TextField(blank=True, verbose_name=_("Minutes"))
    attachment = models.FileField(
        upload_to=upload_path,
        null=True,
        blank=True,
        verbose_name=_("Minutes attachment"),
    )

    objects = HorillaCompanyManager("committee__workplace__company_id")

    class Meta:
        verbose_name = _("OSH Committee Meeting")
        verbose_name_plural = _("OSH Committee Meetings")
        ordering = ["-held_on"]

    def __str__(self):
        return f"{self.committee} @ {self.held_on}"


class OshMedicalRecord(HorillaModel):
    """Fitness / surveillance metadata — not a clinical EHR."""

    employee = models.ForeignKey(
        Employee,
        on_delete=models.CASCADE,
        related_name="osh_medical_records",
        verbose_name=_("Employee"),
    )
    workplace = models.ForeignKey(
        OshWorkplace,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="medical_records",
        verbose_name=_("Workplace"),
    )
    event = models.ForeignKey(
        OshEvent,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="medical_records",
        verbose_name=_("Related event"),
    )
    exam_type = models.CharField(
        max_length=32,
        choices=MEDICAL_EXAM_TYPE_CHOICES,
        verbose_name=_("Examination type"),
    )
    exam_date = models.DateField(verbose_name=_("Examination date"))
    fitness = models.CharField(
        max_length=32,
        choices=FITNESS_CHOICES,
        default="pending",
        verbose_name=_("Fitness outcome"),
    )
    restrictions = models.TextField(blank=True, verbose_name=_("Restrictions"))
    next_due_on = models.DateField(
        null=True, blank=True, verbose_name=_("Next due on")
    )
    attachment = models.FileField(
        upload_to=upload_path,
        null=True,
        blank=True,
        verbose_name=_("Certificate / report"),
    )
    notes = models.TextField(blank=True, verbose_name=_("Notes"))

    objects = HorillaCompanyManager(
        "employee__employee_work_info__company_id"
    )

    class Meta:
        verbose_name = _("OSH Medical Record")
        verbose_name_plural = _("OSH Medical Records")
        ordering = ["-exam_date"]

    def __str__(self):
        return f"{self.get_exam_type_display()} — {self.employee_id}"


class OshPpeAssignment(HorillaModel):
    employee = models.ForeignKey(
        Employee,
        on_delete=models.CASCADE,
        related_name="osh_ppe_assignments",
        verbose_name=_("Employee"),
    )
    workplace = models.ForeignKey(
        OshWorkplace,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="ppe_assignments",
        verbose_name=_("Workplace"),
    )
    item_type = models.CharField(max_length=100, verbose_name=_("PPE item"))
    issued_on = models.DateField(verbose_name=_("Issued on"))
    returned_on = models.DateField(
        null=True, blank=True, verbose_name=_("Returned on")
    )
    condition = models.CharField(
        max_length=20,
        choices=PPE_CONDITION_CHOICES,
        default="new",
        verbose_name=_("Condition"),
    )
    notes = models.TextField(blank=True, verbose_name=_("Notes"))

    objects = HorillaCompanyManager(
        "employee__employee_work_info__company_id"
    )

    class Meta:
        verbose_name = _("OSH PPE Assignment")
        verbose_name_plural = _("OSH PPE Assignments")
        ordering = ["-issued_on"]

    def __str__(self):
        return f"{self.item_type} → {self.employee_id}"


class OshTrainingRecord(HorillaModel):
    employee = models.ForeignKey(
        Employee,
        on_delete=models.CASCADE,
        related_name="osh_training_records",
        verbose_name=_("Employee"),
    )
    workplace = models.ForeignKey(
        OshWorkplace,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="training_records",
        verbose_name=_("Workplace"),
    )
    course_name = models.CharField(max_length=200, verbose_name=_("Course"))
    completed_on = models.DateField(verbose_name=_("Completed on"))
    valid_until = models.DateField(
        null=True, blank=True, verbose_name=_("Valid until")
    )
    provider = models.CharField(
        max_length=200, blank=True, verbose_name=_("Provider")
    )
    certificate = models.FileField(
        upload_to=upload_path,
        null=True,
        blank=True,
        verbose_name=_("Certificate"),
    )
    notes = models.TextField(blank=True, verbose_name=_("Notes"))

    objects = HorillaCompanyManager(
        "employee__employee_work_info__company_id"
    )

    class Meta:
        verbose_name = _("OSH Training Record")
        verbose_name_plural = _("OSH Training Records")
        ordering = ["-completed_on"]

    def __str__(self):
        return f"{self.course_name} — {self.employee_id}"
