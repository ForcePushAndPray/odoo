import calendar

from odoo import models, fields, api, _
from odoo.exceptions import UserError, ValidationError
from odoo.tools.float_utils import float_compare, float_round


class HrScorecard(models.Model):
    _name = 'hr.scorecard'
    _description = 'Employee KPI Scorecard'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'period_id desc, employee_id'
    _rec_name = 'name'

    name = fields.Char(
        string='Reference',
        required=True,
        copy=False,
        readonly=True,
        default=lambda self: _('New'),
    )
    employee_id = fields.Many2one(
        'hr.employee',
        string='Employee',
        required=True,
        tracking=True,
        index=True,
    )
    department_id = fields.Many2one(
        'hr.department',
        string='Department',
        related='employee_id.department_id',
        store=True,
        readonly=True,
    )
    period_id = fields.Many2one(
        'hr.kpi.period',
        string='Period',
        required=True,
        tracking=True,
        index=True,
    )
    line_ids = fields.One2many(
        'hr.scorecard.line',
        'scorecard_id',
        string='KPI Lines',
        copy=True,
    )
    total_weight = fields.Float(
        string='Total Weight (%)',
        compute='_compute_totals',
        store=True,
    )
    weighted_result = fields.Float(
        string='Weighted Result (%)',
        compute='_compute_totals',
        store=True,
        help='Sum of (KPI achievement x weight) over all lines. May exceed or fall below 100%.',
    )
    bonus_base = fields.Monetary(
        string='Bonus Base',
        tracking=True,
        help='Bonus amount paid when weighted result equals 100%. '
             'Defaults to the value from the employee KPI config.',
    )
    bonus_amount = fields.Monetary(
        string='Bonus Amount',
        compute='_compute_bonus_amount',
        store=True,
        help='bonus_base x weighted_result / 100',
    )
    bonus_model = fields.Selection([
        ('period', 'Period-based (single payout)'),
        ('monthly_advance', 'Monthly advance with reconciliation'),
    ], string='Bonus Model', required=True, default='period', tracking=True)
    bonus_type_id = fields.Many2one(
        'hr.bonus.type',
        string='Bonus Type',
        tracking=True,
        help='Bonus type used when auto-accruing hr.bonus records. '
             'Defaults from the employee KPI config.',
    )
    bonus_ids = fields.Many2many(
        'hr.bonus',
        'hr_scorecard_bonus_rel',
        'scorecard_id',
        'bonus_id',
        string='Accrued Bonuses',
        copy=False,
        readonly=True,
    )
    bonus_count = fields.Integer(
        string='Bonus Count',
        compute='_compute_bonus_count',
    )
    advances_accrued = fields.Boolean(
        string='Advances Accrued',
        readonly=True,
        copy=False,
        default=False,
    )
    final_accrued = fields.Boolean(
        string='Final Accrued',
        readonly=True,
        copy=False,
        default=False,
    )
    currency_id = fields.Many2one(
        'res.currency',
        string='Currency',
        related='company_id.currency_id',
        store=True,
        readonly=True,
    )
    company_id = fields.Many2one(
        'res.company',
        string='Company',
        required=True,
        default=lambda self: self.env.company,
        domain=lambda self: [('id', 'in', self.env.companies.ids)],
    )    
    state = fields.Selection([
        ('draft', 'Draft'),
        ('confirmed', 'Confirmed'),
        ('closed', 'Closed'),
    ], string='Status', required=True, default='draft', tracking=True, index=True)
    notes = fields.Text(string='Notes')

    _sql_constraints = [
        ('employee_period_uniq', 'unique(employee_id, period_id, company_id)',
         'A scorecard already exists for this employee and period.'),
    ]

    @api.depends('line_ids.weight', 'line_ids.weighted_achievement')
    def _compute_totals(self):
        for card in self:
            card.total_weight = sum(card.line_ids.mapped('weight'))
            card.weighted_result = sum(card.line_ids.mapped('weighted_achievement'))

    @api.depends('bonus_base', 'weighted_result')
    def _compute_bonus_amount(self):
        for card in self:
            card.bonus_amount = float_round(
                card.bonus_base * card.weighted_result / 100.0,
                precision_digits=2,
            )

    @api.depends('bonus_ids')
    def _compute_bonus_count(self):
        for card in self:
            card.bonus_count = len(card.bonus_ids)

    @api.constrains('line_ids', 'state')
    def _check_total_weight_on_confirm(self):
        for card in self:
            if card.state in ('confirmed', 'closed'):
                if float_compare(card.total_weight, 100.0, precision_digits=2) != 0:
                    raise ValidationError(_(
                        'Total weight of KPI lines must equal 100%% on confirmed scorecards '
                        '(currently %.2f%%).'
                    ) % card.total_weight)

    @api.onchange('employee_id', 'company_id')
    def _onchange_employee_id(self):
        if self.employee_id:
            config = self.env['hr.scorecard.employee.config'].get_for_employee(
                self.employee_id, self.company_id,
            )
            if config:
                self.bonus_base = config.bonus_base
                self.bonus_model = config.bonus_model
                self.bonus_type_id = config.bonus_type_id

    @api.model_create_multi
    def create(self, vals_list):
        Config = self.env['hr.scorecard.employee.config']
        for vals in vals_list:
            if vals.get('name', _('New')) == _('New'):
                vals['name'] = self.env['ir.sequence'].next_by_code('hr.scorecard') or _('New')
            employee_id = vals.get('employee_id')
            if employee_id:
                company = self.env['res.company'].browse(
                    vals.get('company_id') or self.env.company.id
                )
                config = Config.get_for_employee(
                    self.env['hr.employee'].browse(employee_id), company,
                )
                if config:
                    vals.setdefault('bonus_base', config.bonus_base)
                    vals.setdefault('bonus_model', config.bonus_model)
                    vals.setdefault('bonus_type_id', config.bonus_type_id.id)
        return super().create(vals_list)

    def action_confirm(self):
        for card in self:
            if card.state != 'draft':
                raise UserError(_('Only draft scorecards can be confirmed.'))
            if not card.line_ids:
                raise UserError(_('Add at least one KPI line before confirming.'))
        self.write({'state': 'confirmed'})

    def action_draft(self):
        for card in self:
            if card.state == 'closed':
                raise UserError(_('Closed scorecards cannot be reset to draft.'))
            if card.bonus_ids:
                raise UserError(_(
                    'Cannot reset a scorecard with accrued bonuses. '
                    'Cancel the linked hr.bonus records first.'
                ))
        self.write({'state': 'draft'})

    def action_close(self):
        for card in self:
            if card.state != 'confirmed':
                raise UserError(_('Only confirmed scorecards can be closed.'))
        self.write({'state': 'closed'})

    def action_open_bonuses(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Bonuses'),
            'res_model': 'hr.bonus',
            'view_mode': 'list,form',
            'domain': [('id', 'in', self.bonus_ids.ids)],
        }

    def action_accrue_bonus(self):
        for card in self:
            card._accrue_bonus()
        return True

    def _accrue_bonus(self):
        """Create hr.bonus records for this scorecard.

        Idempotent: re-running skips already-accrued advances and the final
        reconciliation. For period-based bonuses, creates one hr.bonus when
        the scorecard is closed. For monthly-advance bonuses, creates N
        advances on first call (scorecard confirmed or closed) and a
        reconciliation on close.
        """
        self.ensure_one()
        if self.state == 'draft':
            raise UserError(_('Confirm the scorecard before accruing bonuses.'))
        if not self.bonus_type_id:
            raise UserError(_(
                'Set a Bonus Type on the scorecard (or in the employee KPI config) '
                'before accruing bonuses.'
            ))
        Bonus = self.env['hr.bonus']

        if self.bonus_model == 'period':
            if self.state != 'closed':
                raise UserError(_(
                    'Period-based bonus can only be accrued after the scorecard is closed.'
                ))
            if self.final_accrued:
                return
            bonus = Bonus.create(self._prepare_bonus_vals(
                amount=self.bonus_amount,
                date=self.period_id.date_to,
                note=_('Auto-accrued from scorecard %s') % self.name,
            ))
            self.write({'bonus_ids': [(4, bonus.id)], 'final_accrued': True})
            return

        # monthly_advance
        if not self.advances_accrued:
            months = self.period_id.months_in_period()
            if not months:
                raise UserError(_('Period does not cover any month.'))
            per_month = float_round(self.bonus_base / len(months), precision_digits=2)
            for year, month in months:
                last_day = calendar.monthrange(year, month)[1]
                bonus = Bonus.create(self._prepare_bonus_vals(
                    amount=per_month,
                    date=fields.Date.to_date(f'{year:04d}-{month:02d}-{last_day:02d}'),
                    note=_('Monthly advance from scorecard %s (%d-%02d)') % (
                        self.name, year, month,
                    ),
                ))
                self.write({'bonus_ids': [(4, bonus.id)]})
            self.advances_accrued = True

        if self.state == 'closed' and not self.final_accrued:
            accrued = sum(self.bonus_ids.mapped('amount'))
            diff = float_round(self.bonus_amount - accrued, precision_digits=2)
            if not self.currency_id.is_zero(diff):
                bonus = Bonus.create(self._prepare_bonus_vals(
                    amount=diff,
                    date=self.period_id.date_to,
                    note=_('Reconciliation for scorecard %s') % self.name,
                ))
                self.write({'bonus_ids': [(4, bonus.id)]})
            self.final_accrued = True

    def _prepare_bonus_vals(self, amount, date, note):
        self.ensure_one()
        return {
            'employee_id': self.employee_id.id,
            'bonus_type_id': self.bonus_type_id.id,
            'date': date,
            'amount': amount,
            'company_id': self.company_id.id,
            'notes': note,
        }
