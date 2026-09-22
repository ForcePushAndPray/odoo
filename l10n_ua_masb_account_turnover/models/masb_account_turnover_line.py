"""Rows of a turnover statement.

Every value of the dimension (a subdivision, a supplier) produces a main row
carrying the balances and the totals of the ``account x dimension value`` pair.
A statement with cost elements adds element rows below it that break the same
turnover down. Keeping both as records instead of computing the main row on the
fly is what lets the accountant sort, filter and drill into any row.

The dimension value is stored generically - model, id and the name it had when
the statement was computed - because the statement type decides what the
dimension is. The two dimensions in use today also get a Many2one of their own
so that the list and the pivot can filter and group by them.
"""
from odoo import _, api, fields, models

from .masb_account_turnover_column import COST_ELEMENTS


class MasbAccountTurnoverLine(models.Model):
    _name = 'masb.account.turnover.line'
    _description = 'Account Turnover Statement Line'
    _order = 'sheet_id, sequence, id'

    sheet_id = fields.Many2one(
        'masb.account.turnover',
        string='Statement',
        required=True,
        ondelete='cascade',
        index=True,
    )
    sequence = fields.Integer(default=10)
    line_type = fields.Selection(
        selection=[
            ('group', 'Row total'),
            ('element', 'Cost element'),
        ],
        required=True,
        default='group',
    )
    account_id = fields.Many2one(
        'account.account', string='Account', required=True)
    dimension_model = fields.Char(string='Dimension Model')
    dimension_res_id = fields.Many2oneReference(
        string='Dimension Record', model_field='dimension_model')
    dimension_name = fields.Char(
        string='Row',
        help='Name of the row value as it stood when the statement was '
             'computed, so that a closed period keeps the names it was signed '
             'with.',
    )
    analytic_account_id = fields.Many2one(
        'account.analytic.account', string='Subdivision')
    partner_id = fields.Many2one('res.partner', string='Partner')
    cost_element = fields.Selection(selection=COST_ELEMENTS)
    responsible_name = fields.Char(
        string='Accountable Person',
        help='Name of the accountable person as it stood when the statement '
             'was computed. Stored rather than read through the analytic '
             'account, so that a closed period keeps the name it was signed '
             'with.',
    )
    company_id = fields.Many2one(
        related='sheet_id.company_id', store=True, index=True)
    currency_id = fields.Many2one(related='sheet_id.currency_id')

    opening_balance = fields.Monetary(
        currency_field='currency_id',
        help='Balance before the period, debit positive.')
    turnover_debit = fields.Monetary(
        compute='_compute_turnovers', store=True, currency_field='currency_id')
    turnover_credit = fields.Monetary(
        compute='_compute_turnovers', store=True, currency_field='currency_id')
    closing_balance = fields.Monetary(
        compute='_compute_turnovers', store=True, currency_field='currency_id',
        help='Balance at the end of the period, debit positive.')
    opening_debit = fields.Monetary(
        compute='_compute_sides', store=True, currency_field='currency_id')
    opening_credit = fields.Monetary(
        compute='_compute_sides', store=True, currency_field='currency_id')
    closing_debit = fields.Monetary(
        compute='_compute_sides', store=True, currency_field='currency_id')
    closing_credit = fields.Monetary(
        compute='_compute_sides', store=True, currency_field='currency_id')
    cell_ids = fields.One2many(
        'masb.account.turnover.cell', 'line_id', string='Cells')

    @api.depends('cell_ids.amount', 'cell_ids.block', 'opening_balance')
    def _compute_turnovers(self):
        for line in self:
            debit = credit = 0.0
            for cell in line.cell_ids:
                if cell.block == 'debit':
                    debit += cell.amount
                else:
                    credit += cell.amount
            line.turnover_debit = debit
            line.turnover_credit = credit
            line.closing_balance = line.opening_balance + debit - credit

    @api.depends('opening_balance', 'closing_balance')
    def _compute_sides(self):
        for line in self:
            line.opening_debit, line.opening_credit = self._split_balance(
                line.opening_balance)
            line.closing_debit, line.closing_credit = self._split_balance(
                line.closing_balance)

    @api.model
    def _split_balance(self, balance):
        """A signed balance as ``(debit side, credit side)``."""
        return (balance, 0.0) if balance > 0 else (0.0, -balance)

    @api.depends('line_type', 'dimension_name', 'cost_element', 'account_id')
    def _compute_display_name(self):
        # From the field rather than from the raw selection list: the list is
        # the English source, the field is what the .po translated.
        elements = dict(
            self._fields['cost_element']._description_selection(self.env))
        for line in self:
            if line.line_type == 'group':
                line.display_name = '%s / %s' % (
                    line.account_id.code or line.account_id.name,
                    line._row_label())
            else:
                line.display_name = elements.get(line.cost_element, '')

    def _row_label(self):
        """Name of the row value, or the caption of the unassigned row."""
        self.ensure_one()
        if self.dimension_res_id:
            return self.dimension_name or ''
        return self.sheet_id.type_id.no_dimension_label or _('Not specified')

    def _dimension_key(self):
        """Key of the row value, as ``_dimension_shares`` of the sheet yields it."""
        self.ensure_one()
        if not self.dimension_res_id:
            return False
        return (self.dimension_model, self.dimension_res_id)

    def _cell_values(self, debit_amounts, credit_amounts):
        """Values of the row cells, the empty ones dropped.

        Zero cells are not stored: an empty statement cell is the absence of a
        fact, and keeping thousands of zeros would only slow the matrix down.
        """
        self.ensure_one()
        currency = self.currency_id
        values = []
        for block, amounts in (('debit', debit_amounts),
                               ('credit', credit_amounts)):
            for column_id, amount in (amounts or {}).items():
                if currency and currency.is_zero(amount):
                    continue
                values.append({
                    'line_id': self.id,
                    'column_id': column_id or False,
                    'block': block,
                    'amount': amount,
                })
        return values
