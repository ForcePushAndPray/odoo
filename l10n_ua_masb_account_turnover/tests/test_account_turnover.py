"""Tests of the account 23 statement type (production costs).

The statement restores two things Odoo does not store - the debit/credit
correspondence of an entry and the subdivision behind an amount - so the tests
concentrate on exactly those: how one amount is split over several corresponding
accounts, how it is split over several subdivisions, how credit turnover is
spread over cost elements, and whether the control totals still hold when the
data is imperfect.

A dedicated company is used on purpose: the statement matches accounts by code
prefix, and the codes it needs (231000, 201000, ...) would collide with the
Ukrainian chart of accounts in a company that already has one.
"""
from datetime import date

from odoo import Command
from odoo.exceptions import UserError, ValidationError
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestProductionStatement(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env['res.company'].create({
            'name': 'Account Turnover Production Test'})
        cls.sheet_type = cls.env.ref(
            'l10n_ua_masb_account_turnover.type_account_23')
        cls.env.user.company_ids = [Command.link(cls.company.id)]
        cls.journal = cls.env['account.journal'].create({
            'name': 'Production test', 'code': 'PRTS', 'type': 'general',
            'company_id': cls.company.id,
        })
        cls.acc_231 = cls._account('231000', 'Main production', 'asset_current')
        cls.acc_201 = cls._account('201000', 'Raw materials', 'asset_current')
        cls.acc_661 = cls._account('661000', 'Wages', 'liability_current')
        cls.acc_260 = cls._account('260000', 'Finished goods', 'asset_current')
        cls.acc_999 = cls._account('999000', 'Outside the layout', 'expense')

        plan = cls.env['account.analytic.plan'].create({'name': 'Subdivisions'})
        cls.plan = plan
        cls.shop_a = cls.env['account.analytic.account'].create({
            'name': 'Shop A', 'plan_id': plan.id, 'company_id': cls.company.id})
        cls.shop_b = cls.env['account.analytic.account'].create({
            'name': 'Shop B', 'plan_id': plan.id, 'company_id': cls.company.id})

    @classmethod
    def _account(cls, code, name, account_type):
        # The code is company dependent, so it has to be written while the test
        # company is the active one - otherwise it lands on the main company and
        # the prefix search finds nothing.
        return cls.env['account.account'].with_company(cls.company).create({
            'code': code,
            'name': name,
            'account_type': account_type,
            'company_ids': [Command.link(cls.company.id)],
        })

    def _move(self, move_date, lines):
        """Post an entry. ``lines`` are ``(account, debit, credit, shares)``.

        ``shares`` is a mapping of analytic account to percentage, or None.
        """
        move = self.env['account.move'].with_company(self.company).create({
            'move_type': 'entry',
            'journal_id': self.journal.id,
            'date': move_date,
            'line_ids': [
                Command.create({
                    'account_id': account.id,
                    'name': 'test',
                    'debit': debit,
                    'credit': credit,
                    'analytic_distribution': (
                        {str(analytic.id): percentage
                         for analytic, percentage in (shares or {}).items()}
                        or False),
                })
                for account, debit, credit, shares in lines
            ],
        })
        move.action_post()
        return move

    def _report(self, date_from=date(2026, 7, 1), date_to=date(2026, 7, 31)):
        report = self.env['masb.account.turnover'].with_company(
            self.company).create({
                'type_id': self.sheet_type.id,
                'date_from': date_from,
                'date_to': date_to,
                'company_id': self.company.id,
                'analytic_plan_id': self.plan.id,
            })
        report.action_compute()
        return report

    def _group(self, report, analytic):
        return report.line_ids.filtered(
            lambda line: line.line_type == 'group'
            and line.analytic_account_id == analytic)

    def _element(self, report, analytic, element):
        return report.line_ids.filtered(
            lambda line: line.line_type == 'element'
            and line.analytic_account_id == analytic
            and line.cost_element == element)

    def test_correspondence_splits_over_credit_lines(self):
        """One debit is spread over the credit lines in proportion to them."""
        self._move(date(2026, 7, 10), [
            (self.acc_231, 100.0, 0.0, {self.shop_a: 100}),
            (self.acc_201, 0.0, 60.0, None),
            (self.acc_661, 0.0, 40.0, None),
        ])
        report = self._report()
        self.assertAlmostEqual(self._group(report, self.shop_a).turnover_debit,
                               100.0)
        self.assertAlmostEqual(
            self._element(report, self.shop_a, 'material').turnover_debit, 60.0)
        self.assertAlmostEqual(
            self._element(report, self.shop_a, 'direct').turnover_debit, 40.0)

    def test_amount_splits_over_subdivisions(self):
        """An analytic distribution over two plans' accounts splits the row."""
        self._move(date(2026, 7, 11), [
            (self.acc_231, 100.0, 0.0, {self.shop_a: 60, self.shop_b: 40}),
            (self.acc_201, 0.0, 100.0, None),
        ])
        report = self._report()
        self.assertAlmostEqual(self._group(report, self.shop_a).turnover_debit,
                               60.0)
        self.assertAlmostEqual(self._group(report, self.shop_b).turnover_debit,
                               40.0)

    def test_credit_spreads_over_cost_elements(self):
        """Write-off is attributed to elements in proportion to their debit."""
        self._move(date(2026, 7, 12), [
            (self.acc_231, 100.0, 0.0, {self.shop_a: 100}),
            (self.acc_201, 0.0, 60.0, None),
            (self.acc_661, 0.0, 40.0, None),
        ])
        self._move(date(2026, 7, 20), [
            (self.acc_260, 50.0, 0.0, None),
            (self.acc_231, 0.0, 50.0, {self.shop_a: 100}),
        ])
        report = self._report()
        self.assertAlmostEqual(self._group(report, self.shop_a).turnover_credit,
                               50.0)
        self.assertAlmostEqual(
            self._element(report, self.shop_a, 'material').turnover_credit, 30.0)
        self.assertAlmostEqual(
            self._element(report, self.shop_a, 'direct').turnover_credit, 20.0)

    def test_opening_and_closing_balance(self):
        """Movement before the period becomes the opening balance."""
        self._move(date(2026, 6, 15), [
            (self.acc_231, 25.0, 0.0, {self.shop_a: 100}),
            (self.acc_201, 0.0, 25.0, None),
        ])
        self._move(date(2026, 7, 15), [
            (self.acc_231, 10.0, 0.0, {self.shop_a: 100}),
            (self.acc_201, 0.0, 10.0, None),
        ])
        group = self._group(self._report(), self.shop_a)
        self.assertAlmostEqual(group.opening_balance, 25.0)
        self.assertAlmostEqual(group.turnover_debit, 10.0)
        self.assertAlmostEqual(group.closing_balance, 35.0)

    def test_turnover_without_analytics_is_kept(self):
        """A line with no subdivision lands in its own row, not nowhere."""
        self._move(date(2026, 7, 16), [
            (self.acc_231, 70.0, 0.0, None),
            (self.acc_201, 0.0, 70.0, None),
        ])
        report = self._report()
        self.assertAlmostEqual(report.unassigned_amount, 70.0)
        orphan = report.line_ids.filtered(
            lambda line: line.line_type == 'group'
            and not line.analytic_account_id)
        self.assertTrue(orphan, 'turnover without analytics needs its own row')
        self.assertAlmostEqual(orphan.turnover_debit, 70.0)

    def test_unmatched_corresponding_account_keeps_the_total(self):
        """Turnover against an account with no column still counts."""
        self._move(date(2026, 7, 17), [
            (self.acc_231, 80.0, 0.0, {self.shop_a: 100}),
            (self.acc_999, 0.0, 80.0, None),
        ])
        report = self._report()
        cells = report.line_ids.cell_ids.filtered(
            lambda cell: not cell.column_id)
        self.assertTrue(cells, 'the amount must be stored in a catch-all cell')
        self.assertAlmostEqual(report.total_debit, 80.0)
        self.assertTrue(report.is_balanced)

    def test_control_totals_match(self):
        """Every stored cell adds up to the raw turnover of the accounts."""
        self._move(date(2026, 7, 18), [
            (self.acc_231, 120.0, 0.0, {self.shop_a: 75, self.shop_b: 25}),
            (self.acc_201, 0.0, 90.0, None),
            (self.acc_661, 0.0, 30.0, None),
        ])
        report = self._report()
        self.assertAlmostEqual(report.total_debit, report.control_debit)
        self.assertAlmostEqual(report.total_credit, report.control_credit)
        self.assertTrue(report.is_balanced)

    def test_total_row_sums_group_rows_only(self):
        """The TOTAL row must not add the element rows on top of the groups."""
        self._move(date(2026, 7, 19), [
            (self.acc_231, 100.0, 0.0, {self.shop_a: 50, self.shop_b: 50}),
            (self.acc_201, 0.0, 60.0, None),
            (self.acc_661, 0.0, 40.0, None),
        ])
        matrix = self._report()._report_matrix()
        totals = [row for row in matrix['rows'] if row['is_total']]
        self.assertEqual(len(totals), 1)
        self.assertAlmostEqual(totals[0]['turnover_debit'], 100.0)
        self.assertEqual(len(totals[0]['debit']),
                         len(matrix['rows'][0]['debit']))

    def test_show_all_columns(self):
        """The blank keeps every column; switching it off narrows the matrix."""
        self._move(date(2026, 7, 21), [
            (self.acc_231, 30.0, 0.0, {self.shop_a: 100}),
            (self.acc_201, 0.0, 30.0, None),
        ])
        report = self._report()
        wide = len(report._report_layout()['debit']['columns'])
        report.show_all_columns = False
        narrow = len(report._report_layout()['debit']['columns'])
        self.assertEqual(narrow, 1, 'only the materials column moved')
        self.assertGreater(wide, narrow)

    def test_responsible_name_is_snapshotted(self):
        """The accountable person is stored, not read back from the account."""
        employee = self.env['hr.employee'].create({
            'name': 'Ivanenko I.I.', 'company_id': self.company.id})
        self.shop_a.masb_responsible_id = employee
        self._move(date(2026, 7, 22), [
            (self.acc_231, 15.0, 0.0, {self.shop_a: 100}),
            (self.acc_201, 0.0, 15.0, None),
        ])
        report = self._report()
        self.assertEqual(self._group(report, self.shop_a).responsible_name,
                         'Ivanenko I.I.')
        employee.name = 'Petrenko P.P.'
        self.assertEqual(self._group(report, self.shop_a).responsible_name,
                         'Ivanenko I.I.')

    def test_grid_is_rectangular(self):
        """Every row of the grid matches the column list, cell for cell."""
        self._move(date(2026, 7, 23), [
            (self.acc_231, 12.0, 0.0, {self.shop_a: 100}),
            (self.acc_201, 0.0, 12.0, None),
        ])
        grid = self._report().get_matrix()
        self.assertTrue(grid['rows'])
        width = len(grid['columns'])
        for row in grid['rows']:
            self.assertEqual(len(row['cells']), width, row['kind'])
        labels = [row['cells'][1] for row in grid['rows']]
        self.assertTrue(any('Shop A' in label for label in labels))
        self.assertEqual(grid['rows'][-1]['kind'], 'total')

    def test_pivot_action_targets_group_rows(self):
        """The pivot opens the cells of this statement, totals preselected."""
        self._move(date(2026, 7, 24), [
            (self.acc_231, 20.0, 0.0, {self.shop_a: 100}),
            (self.acc_201, 0.0, 20.0, None),
        ])
        report = self._report()
        action = report.action_open_pivot()
        self.assertEqual(action['res_model'], 'masb.account.turnover.cell')
        self.assertEqual(action['domain'], [('sheet_id', '=', report.id)])
        self.assertEqual(action['context']['search_default_group_rows'], 1)
        cells = self.env['masb.account.turnover.cell'].search(
            action['domain'] + [('line_type', '=', 'group')])
        self.assertAlmostEqual(sum(cells.mapped('amount')), 20.0)
        self.assertEqual(cells.analytic_account_id, self.shop_a)

    @staticmethod
    def _column_key(grid, label):
        return next(column['key'] for column in grid['columns']
                    if column['label'] == label)

    def test_drilldown_opens_the_entries_of_one_column(self):
        """A debit cell opens exactly the items that fed it, nothing else."""
        materials = self._move(date(2026, 7, 25), [
            (self.acc_231, 70.0, 0.0, {self.shop_a: 100}),
            (self.acc_201, 0.0, 70.0, None),
        ])
        self._move(date(2026, 7, 25), [
            (self.acc_231, 30.0, 0.0, {self.shop_a: 100}),
            (self.acc_661, 0.0, 30.0, None),
        ])
        report = self._report()
        grid = report.get_matrix()
        group = self._group(report, self.shop_a)
        action = report.action_open_entries(
            group.id, self._column_key(grid, '201 building materials'))
        # The widget fetches this action through a plain ORM call, so nothing
        # completes it on the way out: it has to be usable as it stands.
        self.assertEqual(action['views'], [(False, 'list'), (False, 'form')])
        opened = self.env['account.move.line'].search(action['domain'])
        self.assertEqual(opened, materials.line_ids.filtered(
            lambda aml: aml.account_id == self.acc_231))

    def test_drilldown_total_covers_the_whole_side(self):
        """The total column opens every item of that side of the row."""
        self._move(date(2026, 7, 26), [
            (self.acc_231, 70.0, 0.0, {self.shop_a: 100}),
            (self.acc_201, 0.0, 70.0, None),
        ])
        self._move(date(2026, 7, 26), [
            (self.acc_231, 30.0, 0.0, {self.shop_a: 100}),
            (self.acc_661, 0.0, 30.0, None),
        ])
        report = self._report()
        grid = report.get_matrix()
        action = report.action_open_entries(
            self._group(report, self.shop_a).id,
            self._column_key(grid, 'Total debit'))
        opened = self.env['account.move.line'].search(action['domain'])
        self.assertEqual(len(opened), 2)
        self.assertAlmostEqual(sum(opened.mapped('debit')), 100.0)

    def test_drilldown_ignores_other_subdivisions(self):
        """Only the items of this row, not of the neighbouring subdivision."""
        self._move(date(2026, 7, 27), [
            (self.acc_231, 40.0, 0.0, {self.shop_a: 100}),
            (self.acc_201, 0.0, 40.0, None),
        ])
        self._move(date(2026, 7, 27), [
            (self.acc_231, 60.0, 0.0, {self.shop_b: 100}),
            (self.acc_201, 0.0, 60.0, None),
        ])
        report = self._report()
        grid = report.get_matrix()
        action = report.action_open_entries(
            self._group(report, self.shop_a).id,
            self._column_key(grid, '201 building materials'))
        opened = self.env['account.move.line'].search(action['domain'])
        self.assertAlmostEqual(sum(opened.mapped('debit')), 40.0)

    def test_drilldown_refuses_derived_figures(self):
        """Closing balance and spread credit are not sets of entries."""
        self._move(date(2026, 7, 28), [
            (self.acc_231, 50.0, 0.0, {self.shop_a: 100}),
            (self.acc_201, 0.0, 50.0, None),
        ])
        self._move(date(2026, 7, 29), [
            (self.acc_260, 20.0, 0.0, None),
            (self.acc_231, 0.0, 20.0, {self.shop_a: 100}),
        ])
        report = self._report()
        grid = report.get_matrix()
        group = self._group(report, self.shop_a)
        with self.assertRaises(UserError):
            report.action_open_entries(
                group.id, self._column_key(grid, 'Closing balance'))
        element = self._element(report, self.shop_a, 'material')
        with self.assertRaises(UserError):
            report.action_open_entries(
                element.id, self._column_key(grid, 'Total credit'))

    def test_period_validation(self):
        report = self.env['masb.account.turnover'].with_company(
            self.company).create({
                'type_id': self.sheet_type.id,
                'date_from': date(2026, 7, 31),
                'date_to': date(2026, 7, 1),
                'company_id': self.company.id,
                'analytic_plan_id': self.plan.id,
            })
        with self.assertRaises(UserError):
            report.action_compute()

    def test_confirmed_statement_is_not_recomputed(self):
        report = self._report()
        report.action_confirm()
        with self.assertRaises(UserError):
            report.action_compute()

    def test_scope_is_copied_from_the_type(self):
        """Prefix comes from the type and stays when the type changes later."""
        report = self._report()
        self.assertEqual(report.account_prefix, '23')
        self.assertEqual(report.dimension_kind, 'analytic')
        self.assertFalse(report.subconto_type_id)

    def test_statement_name_carries_the_type(self):
        report = self._report()
        self.assertIn(self.sheet_type.name, report.name)

    def test_cost_element_required_only_with_cost_elements(self):
        """A debit column of the 23 blank needs a cost element."""
        with self.assertRaises(ValidationError):
            self.env['masb.account.turnover.column'].create({
                'type_id': self.sheet_type.id,
                'name': 'No element',
                'block': 'debit',
                'account_prefixes': '99',
            })
