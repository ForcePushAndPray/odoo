from dateutil.relativedelta import relativedelta
from odoo import models, fields, api, _
from odoo.exceptions import ValidationError


class HrKpiPeriod(models.Model):
    _name = 'hr.kpi.period'
    _description = 'KPI Period'
    _order = 'date_from desc, id desc'

    name = fields.Char(string='Name', required=True)
    period_type = fields.Selection([
        ('quarter', 'Quarterly'),
        ('year', 'Annual'),
    ], string='Period Type', required=True, default='quarter')
    date_from = fields.Date(string='Start Date', required=True)
    date_to = fields.Date(string='End Date', required=True)
    state = fields.Selection([
        ('open', 'Open'),
        ('closed', 'Closed'),
    ], string='Status', required=True, default='open', tracking=False)
    company_id = fields.Many2one(
        'res.company',
        string='Company',
        default=lambda self: self.env.company,
        domain=lambda self: [('id', 'in', self.env.companies.ids)],
    )
    target_ids = fields.One2many(
        'hr.kpi.target',
        'period_id',
        string='KPI Targets',
    )

    @api.constrains('date_from', 'date_to')
    def _check_dates(self):
        for period in self:
            if period.date_from and period.date_to and period.date_from > period.date_to:
                raise ValidationError(_('Period start date must precede end date.'))

    def action_close(self):
        self.write({'state': 'closed'})

    def action_reopen(self):
        self.write({'state': 'open'})

    def action_accrue_bonuses(self):
        """Auto-accrue hr.bonus records for every confirmed/closed scorecard
        in the period across the active companies.
        """
        Scorecard = self.env['hr.scorecard']
        for period in self:
            scorecards = Scorecard.search([
                ('period_id', '=', period.id),
                ('state', 'in', ('confirmed', 'closed')),
                ('company_id', 'in', self.env.companies.ids),
            ])
            for sc in scorecards:
                if sc.bonus_model == 'period' and sc.state != 'closed':
                    continue
                sc._accrue_bonus()
        return True

    def months_in_period(self):
        """Return list of (year, month) tuples covered by the period."""
        self.ensure_one()
        months = []
        cursor = self.date_from.replace(day=1)
        end = self.date_to
        while cursor <= end:
            months.append((cursor.year, cursor.month))
            cursor = cursor + relativedelta(months=1)
        return months
