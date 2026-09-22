"""KPI periods defined by type, year and quarter/month, and the target creation wizard."""

from datetime import date

from psycopg2 import IntegrityError

from odoo.exceptions import UserError, ValidationError
from odoo.tests import TransactionCase, tagged
from odoo.tools import mute_logger


@tagged('post_install', '-at_install')
class TestKpiPeriod(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env['res.company'].create({'name': 'KPI Period Company'})
        cls.Period = cls.env['hr.kpi.period'].with_company(cls.company)
        cls.kpi = cls.env['hr.kpi'].create({
            'name': 'Period KPI', 'company_id': cls.company.id,
        })
        cls.job = cls.env['hr.job'].create({
            'name': 'Period Job', 'company_id': cls.company.id,
        })

    def _create(self, **vals):
        return self.Period.create({'company_id': self.company.id, **vals})

    def test_quarter_name_and_dates(self):
        period = self._create(period_type='quarter', year=2031, quarter='4')
        self.assertEqual(period.name, '2031-Q4')
        self.assertEqual((period.date_from, period.date_to), (date(2031, 10, 1), date(2031, 12, 31)))

    def test_month_name_and_dates(self):
        period = self._create(period_type='month', year=2032, month='2')
        self.assertEqual(period.name, '2032-02')
        self.assertEqual((period.date_from, period.date_to), (date(2032, 2, 1), date(2032, 2, 29)))
        self.assertEqual(period.months_in_period(), [(2032, 2)])

    def test_year_name_and_dates(self):
        period = self._create(period_type='year', year=2031, quarter='2', month='5')
        self.assertEqual(period.name, '2031')
        self.assertEqual((period.date_from, period.date_to), (date(2031, 1, 1), date(2031, 12, 31)))
        self.assertFalse(period.quarter)
        self.assertFalse(period.month)

    def test_changing_type_recomputes_dates(self):
        period = self._create(period_type='quarter', year=2031, quarter='2')
        period.write({'period_type': 'month', 'month': '5'})
        self.assertFalse(period.quarter)
        self.assertEqual(period.name, '2031-05')
        self.assertEqual((period.date_from, period.date_to), (date(2031, 5, 1), date(2031, 5, 31)))

    def test_quarter_required(self):
        with self.assertRaises(ValidationError):
            self._create(period_type='quarter', year=2031)

    def test_month_required(self):
        with self.assertRaises(ValidationError):
            self._create(period_type='month', year=2031)

    def test_year_out_of_range(self):
        with self.assertRaises(ValidationError):
            self._create(period_type='year', year=26)

    def test_duplicate_period_rejected(self):
        self._create(period_type='quarter', year=2033, quarter='1')
        with self.assertRaises(IntegrityError), mute_logger('odoo.sql_db'):
            self._create(period_type='quarter', year=2033, quarter='1')
            self.env.flush_all()

    def test_month_generates_quarter_and_year(self):
        month = self._create(period_type='month', year=2040, month='8')
        quarter = month.parent_id
        self.assertEqual(quarter.name, '2040-Q3')
        self.assertEqual(quarter.parent_id.name, '2040')
        self.assertFalse(quarter.parent_id.parent_id)
        self.assertEqual(quarter.company_id, self.company)
        # Existing parents are reused
        other_month = self._create(period_type='month', year=2040, month='9')
        self.assertEqual(other_month.parent_id, quarter)

    def test_parent_follows_definition_change(self):
        period = self._create(period_type='month', year=2041, month='2')
        period.write({'month': '11'})
        self.assertEqual(period.parent_id.name, '2041-Q4')
        period.write({'period_type': 'quarter', 'quarter': '2'})
        self.assertEqual(period.name, '2041-Q2')
        self.assertEqual(period.parent_id.name, '2041')

    def test_sync_all_parents_links_orphans(self):
        period = self._create(period_type='quarter', year=2042, quarter='2')
        year = period.parent_id
        period.parent_id = False
        self.Period._sync_all_parents()
        self.assertEqual(period.parent_id, year)

    def test_order_is_chronological_within_year(self):
        for month in ('12', '1', '7'):
            self._create(period_type='month', year=2043, month=month)
        months = self.Period.search([
            ('year', '=', 2043), ('period_type', '=', 'month'), ('company_id', '=', self.company.id),
        ])
        self.assertEqual(months.mapped('name'), ['2043-01', '2043-07', '2043-12'])
        quarters = self.Period.search([
            ('year', '=', 2043), ('period_type', '=', 'quarter'), ('company_id', '=', self.company.id),
        ])
        self.assertEqual(quarters.mapped('name'), ['2043-Q1', '2043-Q3', '2043-Q4'])

    def test_find_or_create_is_idempotent(self):
        first = self.Period._find_or_create('month', 2034, month='7', company=self.company)
        second = self.Period._find_or_create('month', 2034, month='7', company=self.company)
        self.assertEqual(first, second)

    def test_display_name(self):
        quarter = self._create(period_type='quarter', year=2031, quarter='3')
        year = quarter.parent_id
        self.assertEqual(quarter.with_context(lang='en_US').display_name, 'Q3 2031')
        self.assertEqual(year.display_name, '2031')

    # ------------------------------------------------------------------
    # Period selection on KPI targets
    # ------------------------------------------------------------------

    def _target(self, **vals):
        return self.env['hr.kpi.target'].with_company(self.company).create({
            'company_id': self.company.id,
            'kpi_id': self.kpi.id,
            **vals,
        })

    def test_target_create_generates_missing_period(self):
        self.assertFalse(self.Period._find('quarter', 2035, '2', company=self.company))
        target = self._target(period_type='quarter', period_year='2035', period_quarter='2')
        self.assertEqual(target.period_id.name, '2035-Q2')
        self.assertEqual(target.period_id.company_id, self.company)
        self.assertEqual(
            (target.period_type, target.period_year, target.period_quarter),
            ('quarter', '2035', '2'),
        )

    def test_target_create_uses_existing_period(self):
        period = self._create(period_type='month', year=2036, month='3')
        target = self._target(
            period_type='month', period_year='2036', period_month='3',
            planned_value=200.0, actual_value=150.0,
        )
        self.assertEqual(target.period_id, period)
        self.assertAlmostEqual(target.achievement, 75.0)

    def test_target_edit_changes_period(self):
        target = self._target(period_type='quarter', period_year='2037', period_quarter='1')
        target.write({'period_quarter': '3'})
        self.assertEqual(target.period_id.name, '2037-Q3')
        target.write({'period_type': 'year'})
        self.assertEqual(target.period_id.name, '2037')
        target.write({'period_type': 'month', 'period_month': '11'})
        self.assertEqual(target.period_id.name, '2037-11')
        self.assertEqual(
            set(self.Period.search([('year', '=', 2037), ('company_id', '=', self.company.id)]).mapped('name')),
            {'2037', '2037-Q1', '2037-Q3', '2037-Q4', '2037-11'},
        )

    def test_target_period_missing_flag(self):
        target = self.env['hr.kpi.target'].with_company(self.company).new({
            'company_id': self.company.id,
            'kpi_id': self.kpi.id,
            'period_type': 'month',
            'period_year': '2038',
            'period_month': '6',
        })
        self.assertTrue(target.period_missing)
        self._create(period_type='month', year=2038, month='6')
        target.invalidate_recordset(['period_missing'])
        self.assertFalse(target.period_missing)

    def test_target_incomplete_period_rejected(self):
        with self.assertRaises(UserError):
            self._target(period_type='quarter', period_year='2039', period_quarter=False)

    def test_year_selection_includes_existing_periods(self):
        self._create(period_type='year', year=2090)
        years = dict(self.env['hr.kpi.target']._selection_years())
        self.assertIn('2090', years)
        self.assertIn(str(date.today().year), years)

    def test_kpi_confirm_and_reset_to_draft(self):
        self.assertEqual(self.kpi.state, 'draft')
        self.kpi.action_confirm()
        self.assertEqual(self.kpi.state, 'confirmed')
        with self.assertRaises(UserError):
            self.kpi.action_confirm()
        self.kpi.action_draft()
        self.assertEqual(self.kpi.state, 'draft')
        with self.assertRaises(UserError):
            self.kpi.action_draft()

    def test_targets_are_ordered_by_kpi_then_period(self):
        other_kpi = self.env['hr.kpi'].create({'name': 'A Period KPI', 'company_id': self.company.id})
        q2 = self._create(period_type='quarter', year=2050, quarter='2')
        q1 = self._create(period_type='quarter', year=2050, quarter='1')
        Target = self.env['hr.kpi.target']
        for kpi in (self.kpi, other_kpi):
            for period in (q2, q1):
                Target.create({'kpi_id': kpi.id, 'period_id': period.id, 'company_id': self.company.id})
        targets = Target.search([('period_id', 'in', (q1 | q2).ids)])
        kpis = (self.kpi | other_kpi).sorted()
        self.assertEqual(
            [(target.kpi_id, target.period_id) for target in targets],
            [(kpis[0], q1), (kpis[0], q2), (kpis[1], q1), (kpis[1], q2)],
        )

    def test_target_count(self):
        q1 = self._create(period_type='quarter', year=2051, quarter='1')
        year = q1.parent_id
        self.assertEqual((q1.target_count, year.target_count), (0, 0))
        Target = self.env['hr.kpi.target']
        target = Target.create({'kpi_id': self.kpi.id, 'period_id': q1.id, 'company_id': self.company.id})
        self.assertEqual(q1.target_count, 1)
        # Only the targets of the period itself, not of the periods inside it
        self.assertEqual(year.target_count, 0)
        empty = self.Period.search([('year', '=', 2051), ('target_count', '=', 0)])
        self.assertEqual(empty, year)
        self.assertEqual(Target.search(q1.action_open_targets()['domain']), target)
        target.unlink()
        self.assertEqual(q1.target_count, 0)

    def test_binary_kpi_achieved_from_planned_and_actual(self):
        binary = self.env['hr.kpi'].create({
            'name': 'No fines (test)', 'company_id': self.company.id,
            'calculation_method': 'binary', 'higher_is_better': False,
        })
        period = self._create(period_type='quarter', year=2052, quarter='1')
        target = self.env['hr.kpi.target'].create({
            'kpi_id': binary.id, 'period_id': period.id, 'company_id': self.company.id,
            'planned_value': 0.0, 'actual_value': 0.0,
        })
        self.assertTrue(target.binary_achieved)
        self.assertEqual(target.achievement, 100.0)
        target.actual_value = 2.0
        self.assertFalse(target.binary_achieved)
        self.assertEqual(target.achievement, 0.0)
        # Higher is better: the actual value must reach the plan
        binary.higher_is_better = True
        target.write({'planned_value': 10.0, 'actual_value': 10.0})
        self.assertTrue(target.binary_achieved)
        target.actual_value = 9.99
        self.assertFalse(target.binary_achieved)
        self.assertEqual(target.achievement, 0.0)
