"""Rows of the production cost statement.

Every subdivision produces two kinds of row. The group row carries the balances
and the totals of the whole ``sub-account x subdivision`` pair; the element rows
below it break the same turnover down by cost element. Keeping both as records
instead of computing the group on the fly is what lets the accountant sort,
filter and drill into any row of the statement.
"""
from odoo import _, api, fields, models

from .masb_production_column import COST_ELEMENTS


class MasbProductionReportLine(models.Model):
    _name = 'masb.production.report.line'
    _description = 'Production Cost Statement Line'
    _order = 'report_id, sequence, id'

    report_id = fields.Many2one(
        'masb.production.report',
        string='Statement',
        required=True,
        ondelete='cascade',
        index=True,
    )
    sequence = fields.Integer(default=10)
    line_type = fields.Selection(
        selection=[
            ('group', 'Subdivision total'),
            ('element', 'Cost element'),
        ],
        required=True,
        default='element',
    )
    account_id = fields.Many2one(
        'account.account', string='Production Account', required=True)
    analytic_account_id = fields.Many2one(
        'account.analytic.account', string='Subdivision')
    cost_element = fields.Selection(selection=COST_ELEMENTS)
    responsible_name = fields.Char(
        string='Accountable Person',
        help='Name of the accountable person as it stood when the statement '
             'was computed. Stored rather than read through the analytic '
             'account, so that a closed period keeps the name it was signed '
             'with.',
    )
    company_id = fields.Many2one(
        related='report_id.company_id', store=True)
    currency_id = fields.Many2one(related='report_id.currency_id')

    opening_balance = fields.Monetary(currency_field='currency_id')
    turnover_debit = fields.Monetary(
        compute='_compute_turnovers', store=True, currency_field='currency_id')
    turnover_credit = fields.Monetary(
        compute='_compute_turnovers', store=True, currency_field='currency_id')
    closing_balance = fields.Monetary(
        compute='_compute_turnovers', store=True, currency_field='currency_id')
    cell_ids = fields.One2many(
        'masb.production.report.cell', 'line_id', string='Cells')

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

    @api.depends('line_type', 'analytic_account_id', 'cost_element',
                 'account_id')
    def _compute_display_name(self):
        # From the field rather than from the raw selection list: the list is
        # the English source, the field is what the .po translated.
        elements = dict(
            self._fields['cost_element']._description_selection(self.env))
        for line in self:
            if line.line_type == 'group':
                line.display_name = '%s / %s' % (
                    line.account_id.code or line.account_id.name,
                    line.analytic_account_id.display_name
                    or _('No subdivision'))
            else:
                line.display_name = elements.get(line.cost_element, '')

    def _write_cells(self, debit_amounts, credit_amounts):
        """Store the row amounts, dropping the empty ones.

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
        if values:
            self.env['masb.production.report.cell'].create(values)
        return True
