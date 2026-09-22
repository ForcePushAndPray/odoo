"""A KPI of a job position cannot have targets for nested periods."""

from odoo.exceptions import ValidationError
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestKpiTargetNestedPeriods(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.job = cls.env['hr.job'].create({'name': 'Nested Job', 'company_id': cls.company.id})
        cls.other_job = cls.env['hr.job'].create({'name': 'Other Nested Job', 'company_id': cls.company.id})
        cls.kpi = cls.env['hr.kpi'].create({'name': 'Nested KPI', 'company_id': cls.company.id})
        cls.other_kpi = cls.env['hr.kpi'].create({'name': 'Other Nested KPI', 'company_id': cls.company.id})
        Period = cls.env['hr.kpi.period']
        cls.year = Period._find_or_create('year', 2045, company=cls.company)
        cls.q1 = Period._find_or_create('quarter', 2045, quarter='1', company=cls.company)
        cls.q2 = Period._find_or_create('quarter', 2045, quarter='2', company=cls.company)
        cls.january = Period._find_or_create('month', 2045, month='1', company=cls.company)
        cls.april = Period._find_or_create('month', 2045, month='4', company=cls.company)
        cls.next_year = Period._find_or_create('year', 2046, company=cls.company)

    def _target(self, period, kpi=None):
        return self.env['hr.kpi.target'].create({
            'kpi_id': (kpi or self.kpi).id,
            'period_id': period.id,
            'company_id': self.company.id,
        })

    def test_month_inside_existing_quarter_is_rejected(self):
        self._target(self.q1)
        with self.assertRaises(ValidationError):
            self._target(self.january)

    def test_quarter_containing_existing_month_is_rejected(self):
        self._target(self.january)
        with self.assertRaises(ValidationError):
            self._target(self.q1)

    def test_quarter_and_month_inside_existing_year_are_rejected(self):
        self._target(self.year)
        with self.assertRaises(ValidationError):
            self._target(self.q2)
        with self.assertRaises(ValidationError):
            self._target(self.april)

    def test_year_containing_existing_quarter_is_rejected(self):
        self._target(self.q2)
        with self.assertRaises(ValidationError):
            self._target(self.year)

    def test_moving_target_into_a_nested_period_is_rejected(self):
        self._target(self.q1)
        target = self._target(self.q2)
        with self.assertRaises(ValidationError):
            target.period_id = self.january

    def test_disjoint_periods_are_accepted(self):
        self._target(self.q1)
        self._target(self.april)
        self._target(self.next_year)

    def test_other_kpi_is_not_affected(self):
        self._target(self.q1)
        self._target(self.january, kpi=self.other_kpi)

