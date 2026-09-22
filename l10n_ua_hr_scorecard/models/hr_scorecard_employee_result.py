from odoo import models, fields


class HrScorecardEmployeeResult(models.TransientModel):
    """Read-only snapshot of a job position scorecard for one employee.

    Rows are built on demand by ``hr.scorecard.action_open_employees`` from
    the employee version history and the employee KPI config; they are never
    edited and are vacuumed like any transient record.
    """
    _name = 'hr.scorecard.employee.result'
    _description = 'Scorecard Result per Employee'
    _order = 'employee_id'

    scorecard_id = fields.Many2one(
        'hr.scorecard',
        string='Scorecard',
        required=True,
        ondelete='cascade',
        readonly=True,
    )
    job_id = fields.Many2one(related='scorecard_id.job_id')
    period_id = fields.Many2one(related='scorecard_id.period_id')
    weighted_result = fields.Float(related='scorecard_id.weighted_result')
    currency_id = fields.Many2one(related='scorecard_id.currency_id')
    employee_id = fields.Many2one(
        'hr.employee',
        string='Employee',
        required=True,
        readonly=True,
    )
    date_from = fields.Date(
        string='In Position From',
        readonly=True,
        help='First day of the period on which the employee held the job position.',
    )
    date_to = fields.Date(
        string='In Position To',
        readonly=True,
        help='Last day of the period on which the employee held the job position.',
    )
    days_in_position = fields.Integer(string='Days in Position', readonly=True)
    period_days = fields.Integer(string='Days in Period', readonly=True)
    bonus_model = fields.Selection([
        ('period', 'Period-based (single payout)'),
        ('monthly_advance', 'Monthly advance with reconciliation'),
    ], string='Bonus Model', readonly=True,
        help='Taken from the employee KPI config. Empty when the employee has no config '
             'and therefore receives no bonus.')
    bonus_type_id = fields.Many2one('hr.bonus.type', string='Bonus Type', readonly=True)
    planned_bonus = fields.Monetary(
        string='Planned Bonus',
        readonly=True,
        help='Bonus base from the employee KPI config for the whole period.',
    )
    bonus_base = fields.Monetary(
        string='Prorated Bonus Base',
        readonly=True,
        help='Planned bonus x days in position / days in period.',
    )
    bonus_amount = fields.Monetary(
        string='Bonus Amount',
        readonly=True,
        help='Prorated bonus base x weighted result / 100',
    )
    accrued_amount = fields.Monetary(
        string='Accrued',
        readonly=True,
        help='Total of the hr.bonus records already accrued for the employee from this scorecard.',
    )
