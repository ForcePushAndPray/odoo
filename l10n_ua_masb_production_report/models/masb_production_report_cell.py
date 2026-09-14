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
    block = fields.Selection(
        selection=[('debit', 'Debit turnover'), ('credit', 'Credit turnover')],
        required=True,
    )
    amount = fields.Monetary(currency_field='currency_id')
    currency_id = fields.Many2one(related='line_id.currency_id')
