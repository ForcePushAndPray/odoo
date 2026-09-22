"""Multi-company behaviour of the journal-orders and ledgers.

A statement is a document of one company: it counts the journal items of that
company only and is visible in that company only. Statement types and columns
are configuration: shared when they carry no company, and otherwise available
to their company only. Companies are independent of each other.
"""
from datetime import date

from odoo import Command
from odoo.exceptions import AccessError, UserError
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestMultiCompany(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        Company = cls.env['res.company']
        cls.company_a = Company.create({'name': 'Account Turnover MC Company A'})
        cls.company_b = Company.create({'name': 'Account Turnover MC Company B'})
        cls.env.user.company_ids = [Command.link(company.id) for company in (
            cls.company_a, cls.company_b)]

        cls.shared_type = cls.env.ref(
            'l10n_ua_masb_account_turnover.type_account_631')
        cls.supplier = cls.env['res.partner'].create({
            'name': 'MC Supplier', 'is_company': True})

        cls.books = {}
        for company, code in ((cls.company_a, 'MCA'), (cls.company_b, 'MCB')):
            cls.books[company] = {
                'journal': cls._journal(company, code),
                '631': cls._account(company, '631000', 'liability_payable'),
                '201': cls._account(company, '201000', 'asset_current'),
            }

    @classmethod
    def _journal(cls, company, code):
        return cls.env['account.journal'].create({
            'name': 'MC %s' % code, 'code': code, 'type': 'general',
            'company_id': company.id,
        })

    @classmethod
    def _account(cls, company, code, account_type):
        return cls.env['account.account'].with_company(company).create({
            'code': code,
            'name': 'MC %s' % code,
            'account_type': account_type,
            'reconcile': account_type == 'liability_payable',
            'company_ids': [Command.link(company.id)],
        })

    def _bill(self, company, amount):
        """Goods received: Dt 201 - Ct 631, in the books of ``company``."""
        books = self.books[company]
        move = self.env['account.move'].with_company(company).create({
            'move_type': 'entry',
            'journal_id': books['journal'].id,
            'date': date(2026, 1, 10),
            'line_ids': [
                Command.create({'account_id': books['201'].id, 'name': 'mc',
                                'debit': amount, 'credit': 0.0}),
                Command.create({'account_id': books['631'].id, 'name': 'mc',
                                'debit': 0.0, 'credit': amount,
                                'partner_id': self.supplier.id}),
            ],
        })
        move.action_post()
        return move

    def _sheet(self, company, sheet_type=None, compute=True):
        sheet = self.env['masb.account.turnover'].with_company(company).create({
            'type_id': (sheet_type or self.shared_type).id,
            'date_from': date(2026, 1, 1),
            'date_to': date(2026, 1, 31),
            'company_id': company.id,
        })
        if compute:
            sheet.action_compute()
        return sheet

    def _type(self, company):
        return self.env['masb.account.turnover.type'].create({
            'name': 'MC type',
            'account_prefixes': '631',
            'dimension_kind': 'subconto',
            'subconto_type_id': self.shared_type.subconto_type_id.id,
            'company_id': company.id,
        })

    @staticmethod
    def _labels(sheet):
        return [column['label'] for column in sheet.get_matrix()['columns']]

    def test_statement_counts_its_own_company_only(self):
        """Same account codes in two companies do not leak into each other."""
        self._bill(self.company_a, 100.0)
        self._bill(self.company_b, 700.0)
        sheet_a = self._sheet(self.company_a)
        sheet_b = self._sheet(self.company_b)
        self.assertAlmostEqual(sheet_a.total_credit, 100.0)
        self.assertAlmostEqual(sheet_b.total_credit, 700.0)
        self.assertTrue(sheet_a.is_balanced)
        self.assertTrue(sheet_b.is_balanced)

    def test_user_sees_the_statements_of_their_company_only(self):
        self._bill(self.company_a, 100.0)
        self._bill(self.company_b, 700.0)
        sheet_a = self._sheet(self.company_a)
        sheet_b = self._sheet(self.company_b)
        user = self.env['res.users'].create({
            'name': 'MC accountant',
            'login': 'masb_account_turnover_mc_accountant',
            'company_id': self.company_a.id,
            'company_ids': [Command.set([self.company_a.id])],
            'group_ids': [Command.set([
                self.env.ref('account.group_account_user').id])],
        })
        ids = (sheet_a | sheet_b).ids
        Sheet = self.env['masb.account.turnover'].with_user(user)
        self.assertEqual(Sheet.search([('id', 'in', ids)]), sheet_a)
        Line = self.env['masb.account.turnover.line'].with_user(user)
        self.assertEqual(Line.search([('sheet_id', 'in', ids)]).sheet_id, sheet_a)
        Cell = self.env['masb.account.turnover.cell'].with_user(user)
        self.assertEqual(Cell.search([('sheet_id', 'in', ids)]).sheet_id, sheet_a)
        with self.assertRaises(AccessError):
            sheet_b.with_user(user).read(['name'])
        # Shared configuration stays visible to everyone.
        self.assertTrue(self.shared_type.with_user(user).read(['name']))

    def test_type_of_another_company_is_refused(self):
        type_b = self._type(self.company_b)
        with self.assertRaises(UserError):
            self._sheet(self.company_a, type_b, compute=False)

    def test_shared_column_is_refused_in_a_company_type(self):
        """A column of a company type belongs to that company as well."""
        type_b = self._type(self.company_b)
        with self.assertRaises(UserError):
            self.env['masb.account.turnover.column'].create({
                'type_id': type_b.id,
                'name': 'Shared column',
                'block': 'credit',
                'account_prefixes': '201',
                'company_id': False,
            })

    def test_company_column_of_a_shared_type_stays_in_its_company(self):
        """A company can refine a shared blank without touching the others."""
        self.env['masb.account.turnover.column'].create({
            'type_id': self.shared_type.id,
            'name': '201 company B only',
            'block': 'credit',
            'sequence': 1,
            'account_prefixes': '201',
            'company_id': self.company_b.id,
        })
        self._bill(self.company_a, 100.0)
        self._bill(self.company_b, 700.0)
        sheet_a = self._sheet(self.company_a)
        sheet_b = self._sheet(self.company_b)
        self.assertNotIn('201 company B only', self._labels(sheet_a))
        self.assertIn('201 company B only', self._labels(sheet_b))
        cells_b = sheet_b.line_ids.cell_ids.filtered(
            lambda cell: cell.column_id.name == '201 company B only')
        self.assertAlmostEqual(sum(cells_b.mapped('amount')), 700.0)
