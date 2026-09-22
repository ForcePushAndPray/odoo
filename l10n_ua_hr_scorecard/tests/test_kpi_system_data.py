"""KPIs fed by Odoo data (P&L statement lines) and by formulas."""

from datetime import date

from odoo.exceptions import UserError, ValidationError
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestKpiSystemData(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.job = cls.env['hr.job'].create({'name': 'Revenue Job', 'company_id': cls.company.id})
        cls.kpi = cls.env['hr.kpi'].create({
            'name': 'Revenue (test)',
            'company_id': cls.company.id,
            'data_source': 'system',
            'system_field': 'net_revenue',
        })
        Period = cls.env['hr.kpi.period']
        cls.q1 = Period._find_or_create('quarter', 2047, quarter='1', company=cls.company)
        cls.q2 = Period._find_or_create('quarter', 2047, quarter='2', company=cls.company)

        Account = cls.env['account.account']
        cls.revenue_account = Account.create({
            'code': '709901', 'name': 'Revenue (KPI test)', 'account_type': 'income',
        })
        cls.other_income_account = Account.create({
            'code': '719901', 'name': 'Other income (KPI test)', 'account_type': 'income_other',
        })
        cls.counterpart_account = Account.create({
            'code': '369901', 'name': 'Customers (KPI test)', 'account_type': 'asset_current',
        })
        cls.journal = cls.env['account.journal'].create({
            'name': 'KPI test journal', 'code': 'KPIT', 'type': 'general',
            'company_id': cls.company.id,
        })
        cls._post(date(2047, 2, 10), cls.revenue_account, 1000.0)
        cls._post(date(2047, 3, 31), cls.revenue_account, 500.0)
        # Refund: a debit on revenue, ignored by line 2000 of Form No. 2
        cls._post(date(2047, 3, 15), cls.revenue_account, -200.0)
        # Other operating income (account 71) is not revenue from sales
        cls._post(date(2047, 2, 11), cls.other_income_account, 300.0)
        # Next quarter
        cls._post(date(2047, 4, 1), cls.revenue_account, 700.0)
        # Draft entries do not count
        cls._post(date(2047, 2, 12), cls.revenue_account, 999.0, post=False)

    @classmethod
    def _post(cls, move_date, income_account, amount, post=True):
        credit, debit = (amount, 0.0) if amount > 0 else (0.0, -amount)
        move = cls.env['account.move'].create({
            'move_type': 'entry',
            'date': move_date,
            'journal_id': cls.journal.id,
            'line_ids': [
                (0, 0, {'account_id': income_account.id, 'credit': credit, 'debit': debit}),
                (0, 0, {'account_id': cls.counterpart_account.id, 'credit': debit, 'debit': credit}),
            ],
        })
        if post:
            move.action_post()
        return move

    def _report(self, period, company=None, confirm=True):
        report = self.env['l10n_ua.pnl.report'].create({
            'company_id': (company or self.company).id,
            'date_from': period.date_from,
            'date_to': period.date_to,
        })
        report.action_compute()
        if confirm:
            report.action_confirm()
        return report

    def _target(self, period, kpi=None, report=None):
        target = self.env['hr.kpi.target'].create({
            'kpi_id': (kpi or self.kpi).id,
            'period_id': period.id,
            'company_id': self.company.id,
            'planned_value': 2000.0,
        })
        if report:
            target.source_ids.pnl_report_id = report
        return target

    def test_parameter_reads_the_selected_report(self):
        target = self._target(self.q1)
        self.assertEqual(target.source_ids.model, 'l10n_ua.pnl.report')
        menu = self.env.ref('l10n_ua_accounting.menu_ua_reports_pnl')
        self.assertEqual(target.source_ids.model_name, menu.name)
        self.assertFalse(target.fetch_ready)
        report = self._report(self.q1)
        target.source_ids.pnl_report_id = report
        self.assertEqual(target.source_ids.report_id, report.id)
        self.assertTrue(target.source_ids.dates_match)
        self.assertTrue(target.fetch_ready)
        self.assertAlmostEqual(target.actual_value, 1500.0)
        self.assertAlmostEqual(target.achievement, 75.0)

    def test_every_parameter_matches_its_report_line(self):
        from odoo.addons.l10n_ua_accounting.models.l10n_ua_pnl_report import PNL_LINES
        report = self._report(self.q1)
        amounts_by_code = {line.code: line.current_amount for line in report.line_ids}
        selection = dict(self.env['hr.kpi']._fields['system_field'].selection)
        self.assertEqual(len(selection), len(PNL_LINES))
        for _sequence, key, _name, code, *_rest in PNL_LINES:
            self.assertIn(key, selection)
            kpi = self.env['hr.kpi'].create({
                'name': f'P&L {code} (test)',
                'company_id': self.company.id,
                'data_source': 'system',
                'system_field': key,
            })
            target = self._target(self.q1, kpi=kpi, report=report)
            self.assertAlmostEqual(target.actual_value, amounts_by_code[code], msg=key)

    def test_report_of_another_period_is_rejected(self):
        target = self._target(self.q1)
        with self.assertRaises(ValidationError):
            target.source_ids.pnl_report_id = self._report(self.q2)
        partial = self.env['l10n_ua.pnl.report'].create({
            'company_id': self.company.id,
            'date_from': self.q1.date_from,
            'date_to': date(2047, 2, 28),
        })
        partial.action_compute()
        partial.action_confirm()
        with self.assertRaises(ValidationError):
            target.source_ids.pnl_report_id = partial

    def test_changing_the_period_requires_a_matching_report(self):
        target = self._target(self.q1, report=self._report(self.q1))
        with self.assertRaises(ValidationError):
            target.period_id = self.q2

    def test_get_after_recalculating_the_report(self):
        report = self._report(self.q2)
        target = self._target(self.q2, report=report)
        self.assertAlmostEqual(target.actual_value, 700.0)
        self._post(date(2047, 5, 5), self.revenue_account, 50.0)
        report.action_draft()
        report.action_compute()
        report.action_confirm()
        target.action_update_from_system()
        self.assertAlmostEqual(target.actual_value, 750.0)

    def test_get_requires_reports(self):
        target = self._target(self.q1)
        with self.assertRaises(UserError):
            target.action_update_from_system()
        # A draft report cannot be a source
        with self.assertRaises(ValidationError):
            target.source_ids.pnl_report_id = self._report(self.q1, confirm=False)

    def test_report_reset_to_draft_blocks_get(self):
        report = self._report(self.q1)
        target = self._target(self.q1, report=report)
        self.assertAlmostEqual(target.actual_value, 1500.0)
        report.action_draft()
        target.invalidate_recordset(['fetch_ready'])
        target.source_ids.invalidate_recordset(['report_usable'])
        self.assertFalse(target.fetch_ready)
        with self.assertRaises(UserError):
            target.action_update_from_system()

    def test_report_of_another_company_is_rejected(self):
        other_company = self.env['res.company'].create({'name': 'KPI Report Company'})
        target = self._target(self.q1)
        with self.assertRaises(ValidationError):
            target.source_ids.pnl_report_id = self._report(self.q1, company=other_company)

    def test_confirmed_target_keeps_its_value(self):
        report = self._report(self.q2)
        target = self._target(self.q2, report=report)
        target.action_confirm()
        self._post(date(2047, 5, 6), self.revenue_account, 50.0)
        report.action_draft()
        report.action_compute()
        report.action_confirm()
        with self.assertRaises(UserError):
            target.action_update_from_system()
        self.assertAlmostEqual(target.actual_value, 700.0)

    def test_manual_kpi_is_not_touched(self):
        manual_kpi = self.env['hr.kpi'].create({'name': 'Manual (test)', 'company_id': self.company.id})
        target = self._target(self.q1, kpi=manual_kpi)
        target.actual_value = 42.0
        self.assertFalse(target.source_ids)
        self.assertFalse(target.computed_actual)
        with self.assertRaises(UserError):
            target.action_update_from_system()
        self.assertEqual(target.actual_value, 42.0)

    def test_system_source_requires_a_field(self):
        with self.assertRaises(ValidationError):
            self.env['hr.kpi'].create({'name': 'No field (test)', 'data_source': 'system'})

    # ------------------------------------------------------------------
    # Formulas
    # ------------------------------------------------------------------

    def _formula_kpi(self, formula, variables, data_source='system'):
        return self.env['hr.kpi'].create({
            'name': f'Formula {formula} (test)',
            'company_id': self.company.id,
            'data_source': data_source,
            'use_formula': True,
            'formula': formula,
            'variable_ids': [
                (0, 0, {'code': code, 'name': code, 'system_field': field})
                for code, field in variables
            ],
        })

    def test_formula_with_odoo_parameters_and_constants(self):
        kpi = self._formula_kpi('(A - B) / A * 100 + 5', [
            ('A', 'net_revenue'),
            ('B', 'other_operating_income'),
        ])
        target = self._target(self.q1, kpi=kpi)
        self.assertEqual(target.input_ids.mapped('code'), ['A', 'B'])
        # One report for both Odoo parameters of the P&L statement
        self.assertEqual(len(target.source_ids), 1)
        # Not ready yet: no report, the actual value is not computed
        self.assertFalse(target.fetch_ready)
        self.assertFalse(target.actual_value)
        target.source_ids.pnl_report_id = self._report(self.q1)
        values = {line.code: line.value for line in target.input_ids}
        self.assertEqual((values['A'], values['B']), (1500.0, 300.0))
        self.assertAlmostEqual(target.actual_value, 85.0)

    def test_formula_division_by_zero(self):
        # No cost of sales in the test data
        kpi = self._formula_kpi('A / B', [('A', 'net_revenue'), ('B', 'cost_of_sales')])
        target = self._target(self.q1, kpi=kpi, report=self._report(self.q1))
        self.assertFalse(target.actual_value)
        with self.assertRaises(UserError):
            target.action_update_from_system()

    def test_formula_validation(self):
        variables = [('A', 'net_revenue')]
        for formula in ('', 'A +', 'A ** 2', '__import__("os")', 'A + Z', 'A.real'):
            with self.subTest(formula=formula), self.assertRaises(ValidationError):
                self._formula_kpi(formula, variables)
        with self.assertRaises(ValidationError):
            self._formula_kpi('1A', [('1A', 'net_revenue')])
        with self.assertRaises(ValidationError):
            self._formula_kpi('A', [('A', False)])

    def test_formula_builder_requires_odoo_data(self):
        with self.assertRaises(ValidationError):
            self._formula_kpi('A * 2', [('A', 'net_revenue')], data_source='manual')

    def test_changing_kpi_variables_updates_draft_targets(self):
        kpi = self._formula_kpi('A', [('A', 'net_revenue')])
        target = self._target(self.q1, kpi=kpi)
        kpi.write({
            'variable_ids': [(0, 0, {'code': 'B', 'system_field': 'cost_of_sales'})],
            'formula': 'A - B',
        })
        self.assertEqual(target.input_ids.mapped('code'), ['A', 'B'])
        self.assertEqual(target.source_ids.model, 'l10n_ua.pnl.report')

    def test_kpi_turned_into_formula_while_target_confirmed(self):
        kpi = self.env['hr.kpi'].create({
            'name': 'Profitability (test)',
            'company_id': self.company.id,
            'data_source': 'system',
            'system_field': 'net_revenue',
        })
        report = self._report(self.q1)
        target = self._target(self.q1, kpi=kpi, report=report)
        target.action_confirm()
        # The KPI becomes a formula while its target is confirmed
        kpi.write({
            'use_formula': True,
            'formula': '100 - B / A',
            'variable_ids': [
                (0, 0, {'code': 'A', 'system_field': 'cost_of_sales'}),
                (0, 0, {'code': 'B', 'system_field': 'net_revenue'}),
            ],
        })
        self.assertFalse(target.input_ids)
        target.action_draft()
        self.assertEqual(target.input_ids.mapped('code'), ['A', 'B'])

    def test_get_is_not_ready_without_lines(self):
        kpi = self._formula_kpi('100 - B / A', [
            ('A', 'net_revenue'), ('B', 'other_operating_income'),
        ])
        target = self._target(self.q1, kpi=kpi)
        # Lines lost (e.g. created before the formula existed)
        target.write({'input_ids': [(5, 0, 0)], 'source_ids': [(5, 0, 0)]})
        self.assertFalse(target.fetch_ready)
        # Getting the data asks for the report (its savepoint is rolled back)
        with self.assertRaises(UserError):
            target.action_update_from_system()
        target._sync_formula_lines()
        self.assertEqual(target.input_ids.mapped('code'), ['A', 'B'])
        self.assertEqual(len(target.source_ids), 1)
        target.source_ids.pnl_report_id = self._report(self.q1)
        self.assertTrue(target.fetch_ready)
        self.assertAlmostEqual(target.actual_value, 100 - 300.0 / 1500.0, places=2)
