from odoo import models, fields


class HrKpi(models.Model):
    _name = 'hr.kpi'
    _description = 'Key Performance Indicator'
    _order = 'sequence, name'

    name = fields.Char(string='Name', required=True, translate=True)
    code = fields.Char(string='Code')
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)
    description = fields.Text(string='Description', translate=True)
    calculation_method = fields.Selection([
        ('binary', 'Binary (achieved / not achieved)'),
        ('coefficient', 'Fulfillment coefficient (actual / planned)'),
    ], string='Calculation Method', required=True, default='coefficient')
    uom_name = fields.Char(
        string='Unit of Measure',
        help='Free-form unit shown next to planned/actual values (UAH, pcs, %, ...).',
    )
    higher_is_better = fields.Boolean(
        string='Higher is better',
        default=True,
        help='Uncheck for KPIs where lower actual value means better performance '
             '(e.g. defects, downtime). The coefficient is then inverted: planned / actual.',
    )
    company_id = fields.Many2one(
        'res.company',
        string='Company',
        default=lambda self: self.env.company,
    )

    _sql_constraints = [
        ('code_company_uniq', 'unique(code, company_id)',
         'KPI code must be unique per company.'),
    ]
