"""One amount of the statement matrix: a row crossed with a column.

Cells are stored rather than recomputed on render so that the statement stays a
snapshot of the period as it was closed. A cell whose ``column_id`` is empty
holds turnover against a corresponding account that no configured column
matches - it is shown in the trailing "Other" column instead of being dropped,
so the control totals keep adding up.
"""
from odoo import fields, models


class MasbProductionReportCell(models.Model):
    _name = 'masb.production.report.cell'
    _description = 'Production Cost Statement Cell'
    _order = 'line_id, block desc, column_id'

    line_id = fields.Many2one(
        'masb.production.report.line',
        string='Line',
        required=True,
        ondelete='cascade',
        index=True,
    )
    report_id = fields.Many2one(
        related='line_id.report_id', store=True, index=True)
    column_id = fields.Many2one(
        'masb.production.column', string='Column', ondelete='restrict')
    # Axes of the standard pivot view. They are stored copies rather than plain
    # related fields because a pivot groups in SQL: an unstored related column
    # cannot be an axis at all.
    account_id = fields.Many2one(
        related='line_id.account_id', store=True, index=True)
    analytic_account_id = fields.Many2one(
        related='line_id.analytic_account_id', store=True, index=True)
    cost_element = fields.Selection(
        related='line_id.cost_element', store=True)
    line_type = fields.Selection(
        related='line_id.line_type', store=True, index=True)
    block = fields.Selection(
        selection=[('debit', 'Debit turnover'), ('credit', 'Credit turnover')],
        required=True,
    )
    amount = fields.Monetary(currency_field='currency_id')
    currency_id = fields.Many2one(related='line_id.currency_id')
