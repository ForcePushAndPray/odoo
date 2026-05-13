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
    period_id = fields.Many2one(
        'hr.kpi.period',
        related='scorecard_id.period_id',
        store=True,
        readonly=True,
    )
    target_id = fields.Many2one(
        'hr.kpi.target',
        string='Target',
        compute='_compute_target_id',
        store=True,
        readonly=True,
        help='Period-level planned/actual values for this KPI. '
             'Created automatically when the line is saved.',
    )
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
             'scorecard must total 100%. Always editable.',
    )
    planned_value = fields.Float(
        related='target_id.planned_value',
        readonly=True,
    )
    actual_value = fields.Float(
        related='target_id.actual_value',
        readonly=True,
    )
    binary_achieved = fields.Boolean(
        related='target_id.binary_achieved',
        readonly=True,
    )
    target_state = fields.Selection(
        related='target_id.state',
        readonly=True,
    )
    achievement = fields.Float(
        related='target_id.achievement',
        store=True,
        readonly=True,
    )
    weighted_achievement = fields.Float(
        string='Weighted (%)',
        compute='_compute_weighted_achievement',
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

    @api.depends('kpi_id', 'scorecard_id.period_id', 'scorecard_id.company_id')
    def _compute_target_id(self):
        Target = self.env['hr.kpi.target']
        for line in self:
            if not line.kpi_id or not line.scorecard_id.period_id:
                line.target_id = False
                continue
            line.target_id = Target.get_or_create(
                line.kpi_id,
                line.scorecard_id.period_id,
                line.scorecard_id.company_id,
            )

    @api.depends('achievement', 'weight')
    def _compute_weighted_achievement(self):
        for line in self:
            line.weighted_achievement = float_round(
                (line.achievement or 0.0) * (line.weight or 0.0) / 100.0,
                precision_digits=2,
            )
