"""
Monthly (``tax_scale="period"``) filing statuses: Uganda-style monthly PAYE.

Bands are monthly. A monthly payslip is taxed on its own pay; weekly and
semi-monthly pay is taxed at its monthly equivalent and scaled back.
"""

import datetime as dt

from django.test import TestCase

from payroll.methods.tax_calc import explain_period_tax, period_tax
from payroll.models.models import FilingStatus
from payroll.models.tax_models import TaxBracket

# Uganda resident individual, monthly (UGX), with the extra 10% above 10M.
UGANDA_MONTHLY = [
    (0, 235_000, 0),
    (235_000, 335_000, 10),
    (335_000, 410_000, 20),
    (410_000, 10_000_000, 30),
    (10_000_000, None, 40),
]


def uganda_filing(scale="period"):
    filing = FilingStatus.objects.create(filing_status="Uganda PAYE", tax_scale=scale)
    for low, high, rate in UGANDA_MONTHLY:
        TaxBracket.objects.create(
            filing_status_id=filing, min_income=low, max_income=high, tax_rate=rate
        )
    return filing


class MonthlyScaleTests(TestCase):
    def setUp(self):
        self.filing = uganda_filing()

    def tax(self, income, start, end, frequency="monthly"):
        return period_tax(self.filing, income, start, end, pay_frequency=frequency)

    def test_five_million_a_month_is_1_402_000_every_month(self):
        for month in range(1, 13):
            start = dt.date(2026, month, 1)
            end = dt.date(2026 + (month == 12), month % 12 + 1, 1) - dt.timedelta(1)
            self.assertAlmostEqual(self.tax(5_000_000, start, end), 1_402_000, 2)

    def test_a_cycle_crossing_month_end_is_still_one_month(self):
        tax = self.tax(5_000_000, dt.date(2026, 1, 26), dt.date(2026, 2, 25))
        self.assertAlmostEqual(tax, 1_402_000, 2)

    def test_a_part_month_is_taxed_on_what_was_paid(self):
        tax = self.tax(2_741_935, dt.date(2026, 1, 15), dt.date(2026, 1, 31))
        self.assertAlmostEqual(tax, 724_580.5, 2)

    def test_bonus_month_is_taxed_in_that_month(self):
        tax = self.tax(8_000_000, dt.date(2026, 12, 1), dt.date(2026, 12, 31))
        self.assertAlmostEqual(tax, 2_302_000, 2)

    def test_top_band_applies_above_ten_million(self):
        tax = self.tax(12_000_000, dt.date(2026, 3, 1), dt.date(2026, 3, 31))
        # 25,000 + 30% of 9,590,000 + 40% of 2,000,000
        self.assertAlmostEqual(tax, 25_000 + 2_877_000 + 800_000, 2)

    def test_weekly_pay_is_taxed_at_its_monthly_equivalent(self):
        # 1.2M a week is 5.2M a month: 25,000 + 30% x 4,790,000 = 1,462,000.
        tax = self.tax(
            1_200_000, dt.date(2026, 3, 2), dt.date(2026, 3, 8), frequency="weekly"
        )
        self.assertAlmostEqual(tax, 1_462_000 * 12 / 52, 2)

    def test_weekly_pay_below_the_monthly_threshold_equivalent_is_untaxed(self):
        # 50,000 a week is about 216,667 a month, under the 235,000 threshold.
        tax = self.tax(
            50_000, dt.date(2026, 3, 2), dt.date(2026, 3, 8), frequency="weekly"
        )
        self.assertEqual(tax, 0)

    def test_semi_monthly_halves_match_one_monthly_payslip(self):
        half = self.tax(
            2_500_000, dt.date(2026, 3, 1), dt.date(2026, 3, 15), "semi_monthly"
        )
        self.assertAlmostEqual(half * 2, 1_402_000, 2)

    def test_explanation_matches_the_charge(self):
        start, end = dt.date(2026, 3, 2), dt.date(2026, 3, 8)
        explained = explain_period_tax(
            self.filing, 1_200_000, start, end, pay_frequency="weekly"
        )
        self.assertEqual(explained["method"], "monthly_equivalent")
        self.assertEqual(explained["monthly_income"], 5_200_000)
        self.assertEqual(explained["monthly_tax"], 1_462_000)
        self.assertAlmostEqual(
            explained["period_tax"],
            round(self.tax(1_200_000, start, end, "weekly"), 2),
            2,
        )

    def test_annual_scale_is_unchanged(self):
        annual = uganda_filing(scale="annual")
        tax = period_tax(
            annual,
            5_000_000,
            dt.date(2026, 3, 1),
            dt.date(2026, 3, 31),
            pay_frequency="monthly",
        )
        # Monthly bands under annualisation overcharge; this pins old behaviour.
        self.assertAlmostEqual(tax, 1_908_500, 2)

