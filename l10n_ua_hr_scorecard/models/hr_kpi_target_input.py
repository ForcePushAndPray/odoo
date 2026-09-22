from odoo import models, fields


class HrKpiTargetInput(models.Model):
    """Value of a variable of the KPI formula for one target, read from the
    source report."""
    _name = 'hr.kpi.target.input'
    _description = 'KPI Target Formula Input'
    _order = 'target_id, sequence, id'

    target_id = fields.Many2one('hr.kpi.target', string='KPI Target', required=True,
                                ondelete='cascade', index=True)
    variable_id = fields.Many2one('hr.kpi.variable', string='Variable', required=True,
                                  ondelete='cascade')
    sequence = fields.Integer(related='variable_id.sequence', store=True)
    code = fields.Char(related='variable_id.code')
    name = fields.Char(related='variable_id.name')
    system_field = fields.Selection(related='variable_id.system_field')
    value = fields.Float(string='Value')

    _target_variable_uniq = models.Constraint(
        'unique(target_id, variable_id)',
        'A KPI target has one value per formula variable.',
    )
