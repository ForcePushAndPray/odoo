"""Column layout of a turnover statement.

The statement is a matrix: rows are values of an analytic dimension, columns are
corresponding accounts. Which corresponding accounts get a column of their own -
and which of them are merged into one ("201/91", "631/685") - is an accounting
policy decision, not a law, so the layout lives in a directory instead of the
code. Every column belongs to one statement type: the blank of account 23 and
the blank of account 631 share nothing.
"""
from odoo import _, api, fields, models
from odoo.exceptions import ValidationError

from .masb_account_turnover_type import split_prefixes

COST_ELEMENTS = [
    ('material', 'Materials'),
    ('direct', 'Other direct costs'),
    ('prior', 'Prior period costs'),
    ('overhead', 'Production overheads'),
]


class MasbAccountTurnoverColumn(models.Model):
    _name = 'masb.account.turnover.column'
    _description = 'Account Turnover Statement Column'
    _order = 'type_id, block desc, sequence, id'
    _check_company_auto = True

    type_id = fields.Many2one(
        'masb.account.turnover.type',
        string='Statement Type',
        required=True,
        ondelete='cascade',
        index=True,
        check_company=True,
    )
    name = fields.Char(
        string='Column',
        required=True,
        translate=True,
        help='Header shown in the statement, e.g. "201/91 building materials".',
    )
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)
    block = fields.Selection(
        selection=[
            ('debit', 'Debit turnover'),
            ('credit', 'Credit turnover'),
        ],
        required=True,
        default='debit',
        help='Debit block holds the accounts credited against the statement '
             'account (where the debit turnover came from), credit block holds '
             'the accounts debited from it (where the credit turnover went).',
    )
    account_prefixes = fields.Char(
        string='Account Prefixes',
        required=True,
        help='Comma separated prefixes of the corresponding account code, '
             'e.g. "201, 91". A corresponding account falls into this column '
             'when its code starts with any of them.',
    )
    cost_element = fields.Selection(
        selection=COST_ELEMENTS,
        help='Row group the amounts of this column are reported in. Required '
             'for the debit block of a statement with cost elements; credit '
             'amounts are spread over the cost elements in proportion to their '
             'debit turnover.',
    )
    company_id = fields.Many2one(
        'res.company',
        string='Company',
        default=lambda self: self.env.company,
        help='Leave empty to share the column between the companies of the '
             'statement type. A column of one company refines the blank of a '
             'shared type for that company only.',
    )

    @api.constrains('block', 'cost_element', 'type_id')
    def _check_cost_element(self):
        for column in self:
            if (column.type_id.use_cost_elements and column.block == 'debit'
                    and not column.cost_element):
                raise ValidationError(_(
                    'Column "%(name)s" belongs to the debit block of a '
                    'statement with cost elements, so it needs a cost element.',
                    name=column.name))

    @api.constrains('account_prefixes')
    def _check_account_prefixes(self):
        for column in self:
            if not column._prefix_tuple():
                raise ValidationError(_(
                    'Column "%(name)s" has no usable account prefix.',
                    name=column.name))

    def _prefix_tuple(self):
        """Prefixes of this column as a tuple ready for ``str.startswith``."""
        self.ensure_one()
        return split_prefixes(self.account_prefixes)

    @api.model
    def _layout(self, sheet_type, company, block):
        """Columns of one block of one statement type, most specific first.

        Ordering by prefix length makes "901" win over "90" regardless of how
        the user sequenced the rows, so a column can always be refined by adding
        a narrower one next to it.
        """
        columns = self.search([
            ('type_id', '=', sheet_type.id),
            ('block', '=', block),
            ('company_id', 'in', [company.id, False]),
        ])
        return columns.sorted(
            key=lambda column: (
                -max((len(prefix) for prefix in column._prefix_tuple()),
                     default=0),
                column.sequence,
                column.id,
            ))
