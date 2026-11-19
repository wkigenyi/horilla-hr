"""
payroll/tax_packs.py

Ready-made income-tax configurations for common jurisdictions.

Every pack here is expressed purely as data — slabs plus the three declarative
adjustments — with no Python formula anywhere. That is the point: it shows that
the systems people actually run payroll under do not need code, and it gives an
admin a correct starting point instead of a blank slab table.

    Each pack = a FilingStatus + its slabs + its adjustments.

The engine applies them in this order (see tax_calc.compute_yearly_tax), which
is what makes the packs below express real law:

    income
      - standard_deduction
      = taxable income
      -> slabs
      - rebate (when taxable income is at or below its limit)
      + cess
      = tax

IMPORTANT: rates and thresholds change every year, and a payroll system must
not be the authority on them. These are dated starting points to be checked
against the current finance act before anyone is paid by them; the year each
one reflects is in its name and description.

Slab bounds are on income AFTER the standard deduction, because that is what
the engine feeds them — the same basis the published tables use for "taxable
income".
"""

from django.utils.translation import gettext_lazy as _

# (from, to, rate). ``None`` as the upper bound means "and above".
TAX_PACKS = [
    {
        "key": "in_new",
        "country": _("India"),
        "name": "India — New Regime (FY 2025-26)",
        "based_on": "taxable_gross_pay",
        "description": _(
            "Default regime under Budget 2025. Standard deduction of 75,000, "
            "section 87A rebate cancelling up to 60,000 of tax at or below "
            "12,00,000 of taxable income, and 4% health and education cess. "
            "Verify against the current finance act before use."
        ),
        "standard_deduction": 75000,
        "rebate_income_limit": 1200000,
        "rebate_max_amount": 60000,
        "cess_percent": 4.0,
        "slabs": [
            (0, 400000, 0),
            (400000, 800000, 5),
            (800000, 1200000, 10),
            (1200000, 1600000, 15),
            (1600000, 2000000, 20),
            (2000000, 2400000, 25),
            (2400000, None, 30),
        ],
    },
    {
        "key": "in_old",
        "country": _("India"),
        "name": "India — Old Regime (FY 2025-26)",
        "based_on": "taxable_gross_pay",
        "description": _(
            "The regime retaining chapter VI-A deductions. Standard deduction "
            "of 50,000, section 87A rebate up to 12,500 at or below 5,00,000, "
            "and 4% cess. Investment-linked deductions (80C, 80D and the like) "
            "are not modelled here — reduce the employee's taxable gross, or "
            "add a pre-tax deduction, to reflect them."
        ),
        "standard_deduction": 50000,
        "rebate_income_limit": 500000,
        "rebate_max_amount": 12500,
        "cess_percent": 4.0,
        "slabs": [
            (0, 250000, 0),
            (250000, 500000, 5),
            (500000, 1000000, 20),
            (1000000, None, 30),
        ],
    },
    {
        "key": "us_single",
        "country": _("United States"),
        "name": "US Federal — Single (2025)",
        "based_on": "taxable_gross_pay",
        "description": _(
            "Federal income tax only. Standard deduction of 15,000. State, "
            "local, Social Security and Medicare are separate and are better "
            "modelled as their own deductions."
        ),
        "standard_deduction": 15000,
        "slabs": [
            (0, 11925, 10),
            (11925, 48475, 12),
            (48475, 103350, 22),
            (103350, 197300, 24),
            (197300, 250525, 32),
            (250525, 626350, 35),
            (626350, None, 37),
        ],
    },
    {
        "key": "us_mfj",
        "country": _("United States"),
        "name": "US Federal — Married Filing Jointly (2025)",
        "based_on": "taxable_gross_pay",
        "description": _(
            "Federal income tax only. Standard deduction of 30,000. State, "
            "local, Social Security and Medicare are separate."
        ),
        "standard_deduction": 30000,
        "slabs": [
            (0, 23850, 10),
            (23850, 96950, 12),
            (96950, 206700, 22),
            (206700, 394600, 24),
            (394600, 501050, 32),
            (501050, 751600, 35),
            (751600, None, 37),
        ],
    },
    {
        "key": "uk_paye",
        "country": _("United Kingdom"),
        "name": "UK PAYE — England & NI (2025-26)",
        "based_on": "taxable_gross_pay",
        "description": _(
            "Personal allowance of 12,570 modelled as the standard deduction, "
            "then the basic, higher and additional rate bands. HMRC publishes "
            "the bands against total income (basic 12,571-50,270, higher "
            "50,271-125,140); the slabs below are the same bands restated "
            "against income AFTER the allowance, which is what this engine "
            "feeds them. Note the allowance taper above 100,000 is NOT "
            "modelled — earners between 100,000 and 125,140 will be "
            "under-taxed until that is handled. Scotland has its own bands."
        ),
        "standard_deduction": 12570,
        # Bounds are total-income thresholds less the 12,570 allowance:
        #   basic      up to  50,270 total -> 37,700 taxable
        #   higher     up to 125,140 total -> 112,570 taxable
        # Writing HMRC's published 125,140 here directly would have started the
        # additional rate at 137,710 of total income.
        "slabs": [
            (0, 37700, 20),
            (37700, 112570, 40),
            (112570, None, 45),
        ],
    },
    {
        "key": "ug_paye",
        "country": _("Uganda"),
        "name": "Uganda PAYE (FY 2025/26)",
        "based_on": "taxable_gross_pay",
        # URA publishes the resident bands per month, so they are entered as
        # monthly figures rather than restated as a year.
        "tax_scale": "period",
        "description": _(
            "Resident individual rates, charged on monthly pay. The 30% band "
            "runs up to 10,000,000 a month and everything above it pays 40% "
            "(30% plus the additional 10%). Also adds NSSF at 5% for the "
            "employee and 10% for the employer on gross pay, Local Service "
            "Tax by income band (July to October, before PAYE), and sets the "
            "company currency to UGX. Non-resident "
            "rates differ. Verify against the current Income Tax Act before "
            "use."
        ),
        "slabs": [
            (0, 235000, 0),
            (235000, 335000, 10),
            (335000, 410000, 20),
            (410000, 10000000, 30),
            (10000000, None, 40),
        ],
        # Keys into payroll.component_library, loaded alongside the slabs.
        "components": ["ug_nssf_employee", "ug_nssf_employer", "ug_lst"],
        "currency": {"symbol": "UGX", "position": "prefix"},
    },
    {
        "key": "flat_10",
        "country": _("Generic"),
        "name": "Flat 10%",
        "based_on": "taxable_gross_pay",
        "description": _(
            "A single rate on all taxable pay. Useful as a starting point, or "
            "where withholding really is a flat percentage."
        ),
        "slabs": [(0, None, 10)],
    },
]


def pack_rows(loaded_names=frozenset()):
    """
    The packs as display rows, each flagged with whether a filing status of
    that name already exists — so the picker shows what is already there
    rather than silently creating a duplicate.
    """
    rows = []
    for pack in TAX_PACKS:
        rows.append(
            {
                "key": pack["key"],
                "country": pack["country"],
                "name": pack["name"],
                "description": pack["description"],
                "slab_count": len(pack["slabs"]),
                "top_rate": max(rate for _lo, _hi, rate in pack["slabs"]),
                "standard_deduction": pack.get("standard_deduction", 0),
                "has_rebate": pack.get("rebate_income_limit") is not None,
                "cess_percent": pack.get("cess_percent", 0) or 0,
                "already_loaded": pack["name"] in loaded_names,
                "tax_scale": pack.get("tax_scale", "annual"),
                "components": [str(entry["name"]) for entry in _pack_components(pack)],
                "currency": pack.get("currency"),
            }
        )
    return rows


def _pack_components(pack):
    from payroll.component_library import COMPONENT_LIBRARY

    keys = pack.get("components") or []
    by_key = {entry["key"]: entry for entry in COMPONENT_LIBRARY}
    return [by_key[key] for key in keys if key in by_key]


def packs_setting_currency(keys=None):
    """The requested packs that would change the company currency."""
    wanted = set(keys) if keys is not None else None
    return [
        pack
        for pack in TAX_PACKS
        if pack.get("currency") and (wanted is None or pack["key"] in wanted)
    ]


def _set_currency(company, currency):
    from payroll.models.tax_models import PayrollSettings

    settings, _created = PayrollSettings.objects.get_or_create(company_id=company)
    if (
        settings.currency_symbol == currency["symbol"]
        and settings.position == currency["position"]
    ):
        return False
    settings.currency_symbol = currency["symbol"]
    settings.position = currency["position"]
    settings.save()
    PayrollSettings.forget_remembered()
    return True


def load_tax_packs(keys=None, company=None):
    """
    Create a FilingStatus (with slabs and adjustments) for each requested pack.

    Keyed on name via get_or_create, so re-running never duplicates and never
    overwrites an admin's edits to a pack they have already tuned. Returns the
    names actually created.

    A pack may also name components from the component library and a company
    currency. Components are matched on title like the library itself, so an
    existing one with the same name is kept as it is rather than duplicated.
    The currency is only set when a company is given; without one there is no
    settings row it could belong to.
    """
    from payroll.component_library import load_components
    from payroll.models.models import FilingStatus
    from payroll.models.tax_models import TaxBracket

    wanted = set(keys) if keys is not None else None
    created = []

    for pack in TAX_PACKS:
        if wanted is not None and pack["key"] not in wanted:
            continue

        filing_status, was_created = FilingStatus.objects.get_or_create(
            filing_status=pack["name"],
            defaults={
                "based_on": pack["based_on"],
                "description": pack["description"],
                "use_py": False,
                "tax_scale": pack.get("tax_scale", "annual"),
                "standard_deduction": pack.get("standard_deduction", 0) or 0,
                "rebate_income_limit": pack.get("rebate_income_limit"),
                "rebate_max_amount": pack.get("rebate_max_amount"),
                "cess_percent": pack.get("cess_percent", 0) or 0,
            },
        )
        if was_created:
            for lower, upper, rate in pack["slabs"]:
                TaxBracket.objects.create(
                    filing_status_id=filing_status,
                    min_income=lower,
                    max_income=upper,
                    tax_rate=rate,
                )
            created.append(pack["name"])

        # Done even when the filing status already existed, so a pack whose
        # first load was interrupted can be finished by loading it again.
        if pack.get("components"):
            for component in load_components(pack["components"]):
                created.append(component.title)
        if pack.get("currency") and company is not None:
            if _set_currency(company, pack["currency"]):
                created.append(f"Currency {pack['currency']['symbol']}")

    return created
