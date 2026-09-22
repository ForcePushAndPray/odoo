"""Tests of the account 631 statement type (settlements with suppliers).

Account 23 exercises the analytic plan; this type exercises the other kind of
rows - a subconto, falling back to the partner of the journal item - and the
blank of a settlement account: no cost elements, balances on both sides, rows
of settled suppliers left out.
"""
from datetime import date

from odoo import Command
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestSupplierLedger(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env['res.company'].create({
            'name': 'Account Turnover Supplier Test'})
        cls.env.user.company_ids = [Command.link(cls.company.id)]
        cls.sheet_type = cls.env.ref(
            'l10n_ua_masb_account_turnover.type_account_631')
        cls.journal = cls.env['account.journal'].create({
            'name': 'Supplier test', 'code': 'SUTS', 'type': 'general',
            'company_id': cls.company.id,
        })
        cls.acc_631 = cls._account(
            '631000', 'Domestic suppliers', 'liability_payable', reconcile=True)
        cls.acc_201 = cls._account('201000', 'Raw materials', 'asset_current')
        cls.acc_644 = cls._account('644100', 'Tax credit', 'asset_current')
        cls.acc_311 = cls._account('311000', 'Bank', 'asset_cash')
        cls.acc_231 = cls._account('231000', 'Production', 'asset_current')

        Partner = cls.env['res.partner']
        cls.supplier_a = Partner.create({'name': 'Supplier A', 'is_company': True})
        cls.contact_a = Partner.create({
            'name': 'John Smith', 'parent_id': cls.supplier_a.id})
        cls.supplier_b = Partner.create({'name': 'Supplier B', 'is_company': True})
        cls.supplier_c = Partner.create({'name': 'Supplier C', 'is_company': True})

    @classmethod
    def _account(cls, code, name, account_type, reconcile=False):
        # The code is company dependent, so it has to be written while the test
        # company is the active one - otherwise it lands on the main company and
        # the prefix search finds nothing.
        return cls.env['account.account'].with_company(cls.company).create({
            'code': code,
            'name': name,
            'account_type': account_type,
            'reconcile': reconcile,
            'company_ids': [Command.link(cls.company.id)],
        })

    def _move(self, move_date, lines):
        """Post an entry. ``lines`` are ``(account, debit, credit, partner)``."""
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
                    'partner_id': partner.id if partner else False,
                })
                for account, debit, credit, partner in lines
            ],
        })
        move.action_post()
        return move

    def _bill(self, move_date, partner, net, tax=0.0):
        """Goods received from a supplier: Dt 201, Dt 644 - Ct 631."""
        lines = [(self.acc_201, net, 0.0, None)]
        if tax:
            lines.append((self.acc_644, tax, 0.0, None))
        lines.append((self.acc_631, 0.0, net + tax, partner))
        return self._move(move_date, lines)

    def _payment(self, move_date, partner, amount):
        """Payment to a supplier: Dt 631 - Ct 311."""
        return self._move(move_date, [
            (self.acc_631, amount, 0.0, partner),
            (self.acc_311, 0.0, amount, None),
        ])

    def _sheet(self, date_from=date(2026, 1, 1), date_to=date(2026, 1, 31)):
        sheet = self.env['masb.account.turnover'].with_company(
            self.company).create({
                'type_id': self.sheet_type.id,
                'date_from': date_from,
                'date_to': date_to,
                'company_id': self.company.id,
            })
        sheet.action_compute()
        return sheet

    def _row(self, sheet, partner):
        return sheet.line_ids.filtered(lambda line: line.partner_id == partner)

    @staticmethod
    def _cell(line, column_name):
        return sum(line.cell_ids.filtered(
            lambda cell: cell.column_id.name == column_name).mapped('amount'))

    def test_scope_is_copied_from_the_type(self):
        sheet = self._sheet()
        self.assertEqual(sheet.account_prefix, '631')
        self.assertEqual(sheet.subconto_type_id, self.sheet_type.subconto_type_id)
        self.assertFalse(sheet.analytic_plan_id)

    def test_rows_are_suppliers(self):
        """One row per supplier, debit and credit turnover on their own sides."""
        self._bill(date(2026, 1, 10), self.supplier_a, 1000.0, 200.0)
        self._payment(date(2026, 1, 12), self.supplier_b, 700.0)
        sheet = self._sheet()
        row_a = self._row(sheet, self.supplier_a)
        row_b = self._row(sheet, self.supplier_b)
        self.assertEqual(len(row_a), 1)
        self.assertEqual(row_a.dimension_name, 'Supplier A')
        self.assertAlmostEqual(row_a.turnover_credit, 1200.0)
        self.assertAlmostEqual(row_a.turnover_debit, 0.0)
        self.assertAlmostEqual(row_b.turnover_debit, 700.0)
        self.assertTrue(sheet.is_balanced)

    def test_credit_split_by_corresponding_debit_account(self):
        """A bill lands in the columns of the accounts it was debited to."""
        self._bill(date(2026, 1, 10), self.supplier_a, 1000.0, 200.0)
        self._payment(date(2026, 1, 20), self.supplier_a, 1200.0)
        row = self._row(self._sheet(), self.supplier_a)
        self.assertAlmostEqual(self._cell(row, '201 raw materials'), 1000.0)
        self.assertAlmostEqual(self._cell(row, '644 tax credit'), 200.0)
        self.assertAlmostEqual(self._cell(row, '311 current accounts'), 1200.0)

    def test_contact_is_reduced_to_its_company(self):
        """A payment made out to a contact stays on the supplier's row."""
        self._bill(date(2026, 1, 10), self.supplier_a, 500.0)
        self._payment(date(2026, 1, 15), self.contact_a, 500.0)
        sheet = self._sheet()
        self.assertFalse(self._row(sheet, self.contact_a))
        row = self._row(sheet, self.supplier_a)
        self.assertEqual(len(row), 1)
        self.assertAlmostEqual(row.turnover_debit, 500.0)
        self.assertAlmostEqual(row.turnover_credit, 500.0)
        self.assertAlmostEqual(row.closing_balance, 0.0)

    def test_balances_on_both_sides_are_not_netted(self):
        """A debt and an advance are shown apart, in the rows and in the total."""
        self._bill(date(2025, 12, 5), self.supplier_a, 500.0)
        self._payment(date(2025, 12, 6), self.supplier_b, 300.0)
        sheet = self._sheet()
        row_a = self._row(sheet, self.supplier_a)
        row_b = self._row(sheet, self.supplier_b)
        self.assertAlmostEqual(row_a.opening_credit, 500.0)
        self.assertAlmostEqual(row_a.opening_debit, 0.0)
        self.assertAlmostEqual(row_b.opening_debit, 300.0)
        self.assertAlmostEqual(row_b.closing_debit, 300.0)

        grid = sheet.get_matrix()
        keys = [column['key'] for column in grid['columns']]
        self.assertIn('opening_debit', keys)
        self.assertIn('closing_credit', keys)
        total = grid['rows'][-1]
        self.assertEqual(total['kind'], 'total')
        self.assertAlmostEqual(total['cells'][keys.index('opening_debit')], 300.0)
        self.assertAlmostEqual(total['cells'][keys.index('opening_credit')], 500.0)
        for row in grid['rows']:
            self.assertEqual(len(row['cells']), len(keys), row['kind'])

    def test_subconto_value_wins_over_the_partner(self):
        """An entered subconto decides the row, the partner is only a fallback."""
        move = self._bill(date(2026, 1, 10), self.supplier_a, 100.0)
        line_631 = move.line_ids.filtered(
            lambda aml: aml.account_id == self.acc_631)
        self.env['l10n_ua.move.line.subconto'].create({
            'move_line_id': line_631.id,
            'subconto_type_id': self.sheet_type.subconto_type_id.id,
            'res_id': self.supplier_c.id,
        })
        sheet = self._sheet()
        self.assertFalse(self._row(sheet, self.supplier_a))
        self.assertAlmostEqual(
            self._row(sheet, self.supplier_c).turnover_credit, 100.0)

    def test_turnover_without_partner_is_kept(self):
        """A line with no supplier lands in its own row at the end."""
        self._bill(date(2026, 1, 10), self.supplier_a, 50.0)
        self._bill(date(2026, 1, 11), None, 80.0)
        sheet = self._sheet()
        orphan = sheet.line_ids.filtered(lambda line: not line.dimension_res_id)
        self.assertEqual(len(orphan), 1)
        self.assertAlmostEqual(orphan.turnover_credit, 80.0)
        self.assertAlmostEqual(sheet.unassigned_amount, 80.0)
        self.assertEqual(orphan._row_label(), self.sheet_type.no_dimension_label)
        self.assertEqual(sheet.line_ids.sorted('sequence')[-1], orphan)

    def test_no_cost_element_rows(self):
        self._bill(date(2026, 1, 10), self.supplier_a, 100.0)
        self._payment(date(2026, 1, 11), self.supplier_a, 100.0)
        sheet = self._sheet()
        self.assertEqual(set(sheet.line_ids.mapped('line_type')), {'group'})

    def test_settled_supplier_without_movement_is_skipped(self):
        """No opening balance and no turnover - no row."""
        self._bill(date(2025, 12, 5), self.supplier_a, 100.0)
        self._payment(date(2025, 12, 20), self.supplier_a, 100.0)
        self._bill(date(2026, 1, 10), self.supplier_b, 40.0)
        sheet = self._sheet()
        self.assertFalse(self._row(sheet, self.supplier_a))
        self.assertTrue(self._row(sheet, self.supplier_b))

    def test_columns_of_other_types_do_not_mix(self):
        """The 631 blank carries its own columns only."""
        self._bill(date(2026, 1, 10), self.supplier_a, 100.0)
        grid = self._sheet().get_matrix()
        labels = [column['label'] for column in grid['columns']]
        self.assertIn('311 current accounts', labels)
        self.assertNotIn('13 depreciation', labels)

    def test_unmatched_corresponding_account_goes_to_other(self):
        """Turnover against an account with no column still counts."""
        self._move(date(2026, 1, 10), [
            (self.acc_231, 90.0, 0.0, None),
            (self.acc_631, 0.0, 90.0, self.supplier_a),
        ])
        sheet = self._sheet()
        row = self._row(sheet, self.supplier_a)
        self.assertAlmostEqual(self._cell(row, '23 production'), 90.0)
        sheet.type_id.column_ids.filtered(
            lambda column: column.name == '23 production').active = False
        sheet.action_compute()
        row = self._row(sheet, self.supplier_a)
        other = row.cell_ids.filtered(lambda cell: not cell.column_id)
        self.assertAlmostEqual(sum(other.mapped('amount')), 90.0)
        self.assertTrue(sheet.is_balanced)

    def test_drilldown_opens_one_supplier_only(self):
        """A cell of one supplier opens that supplier's items, not a neighbour's."""
        bill_a = self._bill(date(2026, 1, 10), self.supplier_a, 100.0)
        self._bill(date(2026, 1, 10), self.supplier_b, 300.0)
        sheet = self._sheet()
        grid = sheet.get_matrix()
        key = next(column['key'] for column in grid['columns']
                   if column['label'] == '201 raw materials')
        action = sheet.action_open_entries(
            self._row(sheet, self.supplier_a).id, key)
        opened = self.env['account.move.line'].search(action['domain'])
        self.assertEqual(opened, bill_a.line_ids.filtered(
            lambda aml: aml.account_id == self.acc_631))
