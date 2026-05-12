from odoo import models, fields, api, _
from odoo.exceptions import ValidationError
from odoo.tools.float_utils import float_round


class HrScorecardLine(models.Model):
    _name = 'hr.scorecard.line'
    _description = 'Scorecard KPI Line'
    _order = 'sequence, id'

    scorecard_id = fields.Many2one(
        'hr.scorecard',
        string='Scorecard',
        required=True,
        ondelete='cascade',
        index=True,
    )
    sequence = fields.Integer(default=10)
    kpi_id = fields.Many2one('hr.kpi', string='KPI', required=True)
    calculation_method = fields.Selection(
        related='kpi_id.calculation_method',
        store=True,
        readonly=True,
    )
    higher_is_better = fields.Boolean(
        related='kpi_id.higher_is_better',
        readonly=True,
    )
    uom_name = fields.Char(related='kpi_id.uom_name', readonly=True)
    weight = fields.Float(
        string='Weight (%)',
        required=True,
        default=0.0,
        help='Weight of this KPI in the overall scorecard. All weights on a confirmed '
             'scorecard must total 100%.',
    )
    planned_value = fields.Float(string='Planned Value')
    actual_value = fields.Float(string='Actual Value')
    binary_achieved = fields.Boolean(
        string='Achieved',
        help='Used when calculation method is Binary.',
    )
    achievement = fields.Float(
        string='Achievement (%)',
        compute='_compute_achievement',
        store=True,
    )
    weighted_achievement = fields.Float(
        string='Weighted (%)',
        compute='_compute_achievement',
        store=True,
        help='achievement x weight / 100',
    )
    company_id = fields.Many2one(
        related='scorecard_id.company_id',
        store=True,
        readonly=True,
    )

    @api.constrains('weight')
    def _check_weight(self):
        for line in self:
            if line.weight < 0 or line.weight > 100:
                raise ValidationError(_('Weight must be between 0 and 100.'))

    @api.depends(
        'calculation_method', 'higher_is_better',
        'planned_value', 'actual_value', 'binary_achieved', 'weight',
    )
    def _compute_achievement(self):
        for line in self:
            if line.calculation_method == 'binary':
                achievement = 100.0 if line.binary_achieved else 0.0
            else:
                if not line.planned_value:
                    achievement = 0.0
                elif line.higher_is_better:
                    achievement = line.actual_value / line.planned_value * 100.0
                else:
                    if not line.actual_value:
                        achievement = 0.0
                    else:
                        achievement = line.planned_value / line.actual_value * 100.0
            line.achievement = float_round(achievement, precision_digits=2)
            line.weighted_achievement = float_round(
                line.achievement * line.weight / 100.0,
                precision_digits=2,
            )
