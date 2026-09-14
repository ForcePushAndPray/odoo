"""Tests of the production cost statement.

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
from odoo.exceptions import UserError
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestProductionReport(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env['res.company'].create({'name': 'Production Test'})
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
        report = self.env['masb.production.report'].with_company(
            self.company).create({
                'date_from': date_from,
                'date_to': date_to,
                'company_id': self.company.id,
                'analytic_plan_id': self.plan.id,
                'account_prefix': '23',
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

    def test_period_validation(self):
        report = self.env['masb.production.report'].with_company(
            self.company).create({
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
