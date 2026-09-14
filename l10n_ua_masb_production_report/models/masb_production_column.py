"""Column layout of the production cost statement.

The statement is a matrix: rows are production sub-account x subdivision x cost
element, columns are corresponding accounts. Which corresponding accounts get a
column of their own - and which of them are merged into one ("201/91",
"631/685") - is an accounting policy decision, not a law, so the layout lives in
a directory instead of the code.
"""
from odoo import _, api, fields, models
from odoo.exceptions import ValidationError

COST_ELEMENTS = [
    ('material', 'Materials'),
    ('direct', 'Other direct costs'),
    ('prior', 'Prior period costs'),
    ('overhead', 'Production overheads'),
]


class MasbProductionColumn(models.Model):
    _name = 'masb.production.column'
    _description = 'Production Statement Column'
    _order = 'block desc, sequence, id'

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
        help='Debit block holds accounts credited against account 23 (what was '
             'spent on production), credit block holds accounts debited from it '
             '(where the cost went).',
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
             'for the debit block; credit amounts are spread over the cost '
             'elements in proportion to their debit turnover.',
    )
    company_id = fields.Many2one(
        'res.company',
        string='Company',
        default=lambda self: self.env.company,
        help='Leave empty to share the column between companies.',
    )

    @api.constrains('block', 'cost_element')
    def _check_cost_element(self):
        for column in self:
            if column.block == 'debit' and not column.cost_element:
                raise ValidationError(_(
                    'Column "%(name)s" belongs to the debit block, so it needs '
                    'a cost element.', name=column.name))

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
        return tuple(
            prefix for prefix in
            (part.strip() for part in (self.account_prefixes or '').split(','))
            if prefix
        )

    @api.model
    def _layout(self, company, block):
        """Columns of one block, most specific prefix first.

        Ordering by prefix length makes "901" win over "90" regardless of how
        the user sequenced the rows, so a column can always be refined by adding
        a narrower one next to it.
        """
        columns = self.search([
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
