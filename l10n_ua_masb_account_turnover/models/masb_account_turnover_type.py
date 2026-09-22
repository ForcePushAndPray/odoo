"""Type of a turnover statement: which account, in which cut, on which blank.

The journal-order and ledger by account is one register with many faces. For
account 23 its rows are subdivisions broken down by cost element and its
balance is always on the debit side; for account 631 its rows are suppliers and
a balance may sit on either side. None of this is law - it is how a given
company keeps a given account - so it lives in a directory, and a statement for
one more account is one more record here rather than one more module.
"""
from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


def split_prefixes(text):
    """Comma separated account code prefixes as a tuple for ``str.startswith``."""
    return tuple(
        prefix for prefix in (part.strip() for part in (text or '').split(','))
        if prefix
    )


class MasbAccountTurnoverType(models.Model):
    _name = 'masb.account.turnover.type'
    _description = 'Account Turnover Statement Type'
    _order = 'sequence, id'

    name = fields.Char(
        string='Statement Type',
        required=True,
        translate=True,
        help='Title of the statement, e.g. "Account 631 Domestic suppliers".',
    )
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)
    account_prefixes = fields.Char(
        string='Account Prefixes',
        required=True,
        help='Comma separated prefixes of the accounts covered by the '
             'statement, e.g. "631" or "231, 233, 235, 236".',
    )
    dimension_kind = fields.Selection(
        selection=[
            ('analytic', 'Analytic plan'),
            ('subconto', 'Subconto'),
        ],
        string='Rows By',
        required=True,
        default='subconto',
        help='Where the value of a row comes from. Analytic plan: the analytic '
             'distribution of the journal item, which may split one item '
             'between several rows. Subconto: the subconto value of the journal '
             'item or, when none was entered, the matching field of the item '
             'itself (the partner of a bill, the product of an invoice line).',
    )
    analytic_plan_id = fields.Many2one(
        'account.analytic.plan',
        string='Analytic Plan',
        domain="[('parent_id', '=', False)]",
        help='Root analytic plan whose accounts become the rows. Leave empty to '
             'use the default project plan of the database.',
    )
    subconto_type_id = fields.Many2one(
        'l10n_ua.subconto.type',
        string='Subconto Type',
        help='Subconto whose values become the rows of the statement.',
    )
    use_cost_elements = fields.Boolean(
        string='Cost Elements',
        help='Break every row down by cost element (materials, other direct '
             'costs, prior period costs, production overheads). Meant for the '
             'production accounts; every debit column then needs a cost '
             'element.',
    )
    balance_layout = fields.Selection(
        selection=[
            ('net', 'Single column'),
            ('expanded', 'Debit and credit columns'),
        ],
        string='Balance',
        required=True,
        default='expanded',
        help='Single column: the balance is shown as one signed amount, debit '
             'positive - right for an account that only ever has a debit '
             'balance. Debit and credit columns: every row shows its balance on '
             'its own side and the total adds the debit and the credit balances '
             'separately instead of netting them, the way settlement accounts '
             'are read.',
    )
    skip_empty_rows = fields.Boolean(
        string='Skip Empty Rows',
        default=True,
        help='Leave out rows with no opening balance and no turnover in the '
             'period - for a settlement account, every counterparty that was '
             'ever settled with would otherwise stay in the statement forever.',
    )
    row_label = fields.Char(
        string='Row Caption',
        translate=True,
        help='Header of the row column, e.g. "Supplier".',
    )
    no_dimension_label = fields.Char(
        string='Caption Of The Unassigned Row',
        translate=True,
        help='Label of the row that collects turnover without a value of the '
             'dimension, e.g. "No supplier".',
    )
    column_ids = fields.One2many(
        'masb.account.turnover.column', 'type_id', string='Columns')
    company_id = fields.Many2one(
        'res.company',
        string='Company',
        help='Leave empty to share the statement type between companies.',
    )

    @api.constrains('account_prefixes')
    def _check_account_prefixes(self):
        for sheet_type in self:
            if not split_prefixes(sheet_type.account_prefixes):
                raise ValidationError(_(
                    'Statement type "%(name)s" has no usable account prefix.',
                    name=sheet_type.name))

    @api.constrains('dimension_kind', 'subconto_type_id')
    def _check_subconto_type(self):
        for sheet_type in self:
            if (sheet_type.dimension_kind == 'subconto'
                    and not sheet_type.subconto_type_id):
                raise ValidationError(_(
                    'Statement type "%(name)s" takes its rows from a subconto, '
                    'so it needs a subconto type.', name=sheet_type.name))
