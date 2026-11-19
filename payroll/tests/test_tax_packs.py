"""
Tests for the ready-made tax configurations.

These packs are the argument that a real tax system does not need code: every
one is slabs plus the three declarative adjustments, with no Python anywhere.
If that stops being true — or a pack stops computing what its jurisdiction
publishes — these fail.

The expected figures are computed independently below rather than copied from
the engine, so this checks the engine instead of echoing it.
"""

from django.test import TestCase

from horilla.testkit import make_company, make_employee, make_user
from payroll.methods.tax_calc import preview_yearly_tax
from payroll.models.models import FilingStatus
from payroll.tax_packs import TAX_PACKS, load_tax_packs, pack_rows


def independent_tax(pack, income):
    """
    A second implementation of the documented order, written from the pack data
    alone. Agreement between this and the engine is the actual assertion.
    """
    taxable = max(income - pack.get("standard_deduction", 0), 0)
    tax = 0.0
    for lower, upper, rate in pack["slabs"]:
        top = taxable if upper is None else min(upper, taxable)
        if top > lower:
            tax += (top - lower) * rate / 100
    limit = pack.get("rebate_income_limit")
    if limit is not None and taxable <= limit:
        tax = max(tax - (pack.get("rebate_max_amount") or 0), 0.0)
    return round(tax * (1 + pack.get("cess_percent", 0) / 100), 2)


class TaxPackDataTests(TestCase):
    def test_no_pack_uses_a_python_formula(self):
        """The whole point: these are configuration, not code."""
        load_tax_packs()
        for status in FilingStatus.objects.all():
            self.assertFalse(status.use_py, f"{status} loaded in Python mode")

    def test_every_pack_computes_what_an_independent_pass_computes(self):
        load_tax_packs()
        for pack in TAX_PACKS:
            status = FilingStatus.objects.get(filing_status=pack["name"])
            for income in (0, 100000, 550000, 1275000, 2000000, 9000000):
                with self.subTest(pack=pack["key"], income=income):
                    self.assertAlmostEqual(
                        preview_yearly_tax(status, income)["tax"],
                        independent_tax(pack, income),
                        places=2,
                    )

    def test_slabs_are_contiguous_and_start_at_zero(self):
        """
        A gap silently under-taxes — the engine stops walking brackets at the
        first one that does not apply — so a shipped pack must not contain one.
        """
        for pack in TAX_PACKS:
            with self.subTest(pack=pack["key"]):
                slabs = pack["slabs"]
                self.assertEqual(slabs[0][0], 0)
                for (_lo, upper, _r), (next_lo, _u, _r2) in zip(slabs, slabs[1:]):
                    self.assertIsNotNone(upper, "only the last slab may be open-ended")
                    self.assertEqual(upper, next_lo, "slabs must be contiguous")
                self.assertIsNone(slabs[-1][1], "the last slab must be open-ended")

    def test_india_new_regime_matches_published_outcomes(self):
        """
        The two figures everyone checks: nil tax for a salaried employee at
        12.75L (75,000 standard deduction takes it to the 87A threshold), and
        the 4% cess showing up above it.
        """
        load_tax_packs(["in_new"])
        status = FilingStatus.objects.get(filing_status__startswith="India — New")
        self.assertAlmostEqual(
            preview_yearly_tax(status, 1275000)["tax"], 0.0, places=2
        )
        self.assertAlmostEqual(
            preview_yearly_tax(status, 2000000)["tax"], 192400.0, places=2
        )

    def test_the_preview_carries_the_rebate_rule_so_the_page_can_explain_it(self):
        load_tax_packs(["in_new"])
        status = FilingStatus.objects.get(filing_status__startswith="India — New")
        inside = preview_yearly_tax(status, 1275000)
        self.assertEqual(inside["rebate_limit"], float(status.rebate_income_limit))
        self.assertEqual(inside["rebate_max"], float(status.rebate_max_amount))
        self.assertGreater(inside["rebate_applied"], 0)
        above = preview_yearly_tax(status, 2000000)
        self.assertEqual(above["rebate_applied"], 0)
        self.assertGreater(above["taxable_income"], above["rebate_limit"])

    def test_us_single_matches_a_hand_computed_bracket_walk(self):
        """100,000 less the 15,000 deduction = 85,000 taxable."""
        load_tax_packs(["us_single"])
        status = FilingStatus.objects.get(
            filing_status__startswith="US Federal — Single"
        )
        expected = 11925 * 0.10 + (48475 - 11925) * 0.12 + (85000 - 48475) * 0.22
        self.assertAlmostEqual(
            preview_yearly_tax(status, 100000)["tax"], round(expected, 2), places=2
        )

    def test_uk_bands_land_on_hmrc_total_income_thresholds(self):
        """
        HMRC publishes the bands against TOTAL income (basic 12,571-50,270,
        higher 50,271-125,140), but the engine feeds slabs income AFTER the
        personal allowance. Writing HMRC's 125,140 straight into a slab bound
        started the additional rate at 137,710 of total income — this checks
        the boundaries in the terms HMRC states them.
        """
        load_tax_packs(["uk_paye"])
        status = FilingStatus.objects.get(filing_status__startswith="UK PAYE")
        allowance = 12570

        # Top of the basic rate band: all of it at 20%.
        self.assertAlmostEqual(
            preview_yearly_tax(status, 50270)["tax"],
            (50270 - allowance) * 0.20,
            places=2,
        )
        # Top of the higher rate band, i.e. where the additional rate starts.
        expected = (50270 - allowance) * 0.20 + (125140 - 50270) * 0.40
        self.assertAlmostEqual(
            preview_yearly_tax(status, 125140)["tax"], expected, places=2
        )

    def test_loading_twice_creates_nothing_and_preserves_edits(self):
        load_tax_packs()
        count = FilingStatus.objects.count()

        status = FilingStatus.objects.get(filing_status__startswith="India — New")
        status.standard_deduction = 999
        status.save()

        self.assertEqual(load_tax_packs(), [])
        self.assertEqual(FilingStatus.objects.count(), count)
        status.refresh_from_db()
        self.assertEqual(status.standard_deduction, 999)

    def test_rows_flag_what_is_already_loaded(self):
        self.assertFalse(any(row["already_loaded"] for row in pack_rows()))
        load_tax_packs(["in_new"])
        loaded = set(FilingStatus.objects.values_list("filing_status", flat=True))
        rows = {row["key"]: row["already_loaded"] for row in pack_rows(loaded)}
        self.assertTrue(rows["in_new"])
        self.assertFalse(rows["uk_paye"])


class TaxPackViewTests(TestCase):
    def setUp(self):
        user = make_user("packadmin", is_superuser=True)
        company = make_company("Pack Co")
        make_employee(company=company, email="packadmin@test.horilla", user=user)
        self.client.force_login(user)
        self.hx = {"HTTP_HX_REQUEST": "true"}

    def test_picker_lists_every_pack(self):
        from django.utils.html import escape

        response = self.client.get("/payroll/tax-pack-picker/", **self.hx)
        self.assertEqual(response.status_code, 200)
        body = response.content.decode()
        for pack in TAX_PACKS:
            # escape(): the UK pack's name contains "&", which Django renders
            # as &amp; — correctly.
            self.assertIn(escape(pack["name"]), body)

    def test_the_picker_uses_the_standard_title_and_stacks_each_summary_under_its_name(
        self,
    ):
        body = self.client.get("/payroll/tax-pack-picker/", **self.hx).content.decode()
        self.assertIn('class="oh-modal__dialog-title pick__title"', body)
        self.assertNotIn("text-lg font-semibold", body)
        self.assertRegex(body, r"\.pick__summary \{[^}]*display: block")

    def test_loading_selected_packs_creates_them_with_slabs(self):
        response = self.client.post(
            "/payroll/load-tax-pack/", {"packs": ["in_new", "uk_paye"]}, **self.hx
        )
        self.assertIn(response.status_code, (200, 302))
        self.assertEqual(FilingStatus.objects.count(), 2)
        india = FilingStatus.objects.get(filing_status__startswith="India — New")
        self.assertEqual(india.taxbracket_set.count(), 7)
        self.assertEqual(india.standard_deduction, 75000)
        self.assertEqual(india.cess_percent, 4.0)

    def test_loading_nothing_is_refused(self):
        self.client.post("/payroll/load-tax-pack/", {}, **self.hx)
        self.assertEqual(FilingStatus.objects.count(), 0)


class UgandaPackTests(TestCase):
    """
    The Uganda pack: monthly PAYE bands, NSSF on gross pay, an LST placeholder
    and the company currency. Expected tax is worked by hand from the URA
    resident bands, not read back from the engine.
    """

    def setUp(self):
        self.company = make_company("Kampala Co")

    def paye(self):
        return FilingStatus.objects.get(filing_status="Uganda PAYE (FY 2025/26)")

    def test_paye_is_monthly_and_matches_hand_worked_figures(self):
        load_tax_packs(["ug_paye"])
        status = self.paye()
        self.assertEqual(status.tax_scale, "period")
        # 10,000 + 15,000 + 30% of 4,590,000
        self.assertAlmostEqual(
            preview_yearly_tax(status, 5_000_000)["tax"], 1_402_000, places=2
        )
        # 2,902,000 up to 10M, then 40% of the 2M above it
        self.assertAlmostEqual(
            preview_yearly_tax(status, 12_000_000)["tax"], 3_702_000, places=2
        )
        self.assertAlmostEqual(preview_yearly_tax(status, 235_000)["tax"], 0, places=2)

    def test_nssf_is_on_gross_pay_and_after_tax(self):
        from payroll.models.models import Deduction

        load_tax_packs(["ug_paye"])
        employee = Deduction.objects.get(title="Employee NSSF Contribution")
        employer = Deduction.objects.get(title="Employer NSSF Contribution")
        for row in (employee, employer):
            self.assertEqual(row.based_on, "gross_pay")
            self.assertFalse(row.is_pretax)
            self.assertFalse(row.is_fixed)
        self.assertEqual((employee.rate, employee.employer_rate), (5.0, 0.0))
        self.assertEqual((employer.rate, employer.employer_rate), (0.0, 10.0))

    def test_lst_loads_as_banded_and_before_tax(self):
        from payroll.models.models import Deduction

        load_tax_packs(["ug_paye"])
        lst = Deduction.objects.get(title="LST")
        self.assertFalse(lst.is_fixed)
        self.assertEqual(lst.based_on, "uganda_lst")
        # Allowable for PAYE, so it reduces taxable pay.
        self.assertTrue(lst.is_pretax)

    def test_loading_again_duplicates_nothing(self):
        from payroll.models.models import Deduction
        from payroll.models.tax_models import TaxBracket

        first = load_tax_packs(["ug_paye"], company=self.company)
        self.assertIn("Uganda PAYE (FY 2025/26)", first)
        self.assertEqual(load_tax_packs(["ug_paye"], company=self.company), [])
        self.assertEqual(
            FilingStatus.objects.filter(filing_status__startswith="Uganda").count(), 1
        )
        self.assertEqual(
            TaxBracket.objects.filter(filing_status_id=self.paye()).count(), 5
        )
        for title in (
            "Employee NSSF Contribution",
            "Employer NSSF Contribution",
            "LST",
        ):
            self.assertEqual(Deduction.objects.filter(title=title).count(), 1, title)

    def test_existing_components_with_the_same_title_are_kept_as_they_are(self):
        from payroll.models.models import Deduction

        Deduction.objects.create(title="LST", is_fixed=True, amount=25000)
        Deduction.objects.create(
            title="Employee NSSF Contribution",
            is_fixed=False,
            based_on="basic_pay",
            rate=5,
        )
        created = load_tax_packs(["ug_paye"])
        self.assertNotIn("LST", created)
        self.assertNotIn("Employee NSSF Contribution", created)
        self.assertEqual(Deduction.objects.get(title="LST").amount, 25000)
        self.assertEqual(
            Deduction.objects.get(title="Employee NSSF Contribution").based_on,
            "basic_pay",
        )

    def test_currency_becomes_ugx_for_the_company(self):
        from payroll.models.tax_models import PayrollSettings

        created = load_tax_packs(["ug_paye"], company=self.company)
        self.assertIn("Currency UGX", created)
        settings = PayrollSettings.objects.get(company_id=self.company)
        self.assertEqual(
            (settings.currency_symbol, settings.position), ("UGX", "prefix")
        )

    def test_currency_is_left_alone_without_a_company(self):
        from payroll.models.tax_models import PayrollSettings

        before = PayrollSettings.objects.count()
        created = load_tax_packs(["ug_paye"])
        self.assertNotIn("Currency UGX", created)
        self.assertEqual(PayrollSettings.objects.count(), before)

    def test_other_packs_add_no_components(self):
        from payroll.models.models import Deduction

        before = Deduction.objects.count()
        load_tax_packs(["in_new"])
        self.assertEqual(Deduction.objects.count(), before)
