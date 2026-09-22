import calendar
from collections import defaultdict
from datetime import date, timedelta

from odoo import models, fields, api, _, Command
from odoo.exceptions import UserError, ValidationError
from odoo.tools.float_utils import float_compare, float_round


class HrScorecard(models.Model):
    _name = 'hr.scorecard'
    _description = 'Job Position KPI Scorecard'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'period_id desc, job_id'
    _rec_name = 'name'
    _check_company_auto = True

    name = fields.Char(
        string='Reference',
        required=True,
        copy=False,
        readonly=True,
        default=lambda self: _('New'),
    )
    job_id = fields.Many2one(
        'hr.job',
        string='Job Position',
        required=True,
        tracking=True,
        index=True,
        check_company=True,
    )
    department_id = fields.Many2one(
        'hr.department',
        string='Department',
        related='job_id.department_id',
        store=True,
        readonly=True,
    )
    period_id = fields.Many2one(
        'hr.kpi.period',
        string='Period',
        required=True,
        tracking=True,
        index=True,
        check_company=True,
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
    employee_count = fields.Integer(
        string='Employee Count',
        compute='_compute_employee_count',
        help='Employees who held the job position for at least one day of the period.',
    )
    advance_bonus_ids = fields.Many2many(
        'hr.bonus',
        'hr_scorecard_advance_bonus_rel',
        'scorecard_id',
        'bonus_id',
        string='Accrued Advances',
        copy=False,
        readonly=True,
    )
    final_bonus_ids = fields.Many2many(
        'hr.bonus',
        'hr_scorecard_final_bonus_rel',
        'scorecard_id',
        'bonus_id',
        string='Accrued Final Bonuses',
        copy=False,
        readonly=True,
        help='Period-based bonuses and monthly-advance reconciliations.',
    )
    bonus_ids = fields.Many2many(
        'hr.bonus',
        string='Accrued Bonuses',
        compute='_compute_bonus_ids',
    )
    bonus_count = fields.Integer(
        string='Bonus Count',
        compute='_compute_bonus_ids',
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

    _job_period_uniq = models.Constraint(
        'unique(job_id, period_id, company_id)',
        'A scorecard already exists for this job position and period.',
    )

    @api.depends('line_ids.weight', 'line_ids.weighted_achievement')
    def _compute_totals(self):
        for card in self:
            card.total_weight = sum(card.line_ids.mapped('weight'))
            card.weighted_result = sum(card.line_ids.mapped('weighted_achievement'))

    @api.depends('job_id', 'period_id', 'company_id')
    def _compute_employee_count(self):
        for card in self:
            card.employee_count = len(card._get_employee_intervals())

    @api.depends('advance_bonus_ids', 'final_bonus_ids')
    def _compute_bonus_ids(self):
        for card in self:
            card.bonus_ids = card.advance_bonus_ids | card.final_bonus_ids
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

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', _('New')) == _('New'):
                vals['name'] = self.env['ir.sequence'].next_by_code('hr.scorecard') or _('New')
        return super().create(vals_list)

    # ------------------------------------------------------------------
    # Employees of the job position
    # ------------------------------------------------------------------

    def _get_employee_intervals(self):
        """Return ``{employee_id: [(date_start, date_end), ...]}``: the days of
        the period on which each employee held this job position.

        Read from ``hr.version``, never from ``hr.employee``: ``job_id`` on the
        card is the one in force today and cannot answer for a past quarter.
        A version is in force from its ``date_version`` until the next version
        starts, clipped by the contract dates. The rules follow
        ``hr.staffing.table._occupancy_from_versions`` so that the scorecard
        and the staffing table agree on who held a position:

        * a departure date on any version ends employment when the contract
          has no end date;
        * an archived employee without any end date is dropped, since there
          is no telling when they left.

        Contract dates are restricted to HR managers, so the timeline is read
        as superuser; only dates and ids leave this method.
        """
        self.ensure_one()
        return self._get_job_employee_intervals(self.job_id, self.period_id, self.company_id)

    @api.model
    def _get_job_employee_intervals(self, job, period, company):
        """Same as ``_get_employee_intervals`` for any job position, period
        and company, with or without a scorecard."""
        return self._get_job_employee_intervals_between(job, company, period.date_from, period.date_to)

    @api.model
    def _get_job_employee_intervals_between(self, job, company, date_from, date_to):
        """Same as ``_get_job_employee_intervals`` for any date range."""
        if not (job and company and date_from and date_to):
            return {}
        Version = self.env['hr.version'].sudo().with_context(active_test=False)
        holders = Version.search([
            ('employee_id', '!=', False),
            ('company_id', '=', company.id),
            ('job_id', '=', job.id),
            ('date_version', '<=', date_to),
        ])
        if not holders:
            return {}
        employee_ids = holders.employee_id.ids
        rows = Version.search_read(
            [('employee_id', 'in', employee_ids),
             ('date_version', '<=', date_to)],
            ['employee_id', 'company_id', 'job_id', 'date_version',
             'contract_date_start', 'contract_date_end', 'departure_date'],
            order='date_version, id',
        )
        archived = set(self.env['hr.employee'].sudo().with_context(active_test=False).search([
            ('id', 'in', employee_ids), ('active', '=', False),
        ]).ids)

        timelines = defaultdict(list)
        departures = {}
        for row in rows:
            employee_id = row['employee_id'][0]
            timelines[employee_id].append(row)
            departure = row['departure_date']
            if departure and (employee_id not in departures or departure > departures[employee_id]):
                departures[employee_id] = departure

        result = {}
        for employee_id, timeline in timelines.items():
            intervals = []
            for index, row in enumerate(timeline):  # ordered by date_version ascending
                if (row['job_id'] and row['job_id'][0]) != job.id:
                    continue
                if (row['company_id'] and row['company_id'][0]) != company.id:
                    continue
                end = row['contract_date_end'] or departures.get(employee_id)
                if not end and employee_id in archived:
                    continue
                start = row['date_version']
                if row['contract_date_start']:
                    start = max(start, row['contract_date_start'])
                if index + 1 < len(timeline):
                    version_end = timeline[index + 1]['date_version'] - timedelta(days=1)
                    end = min(end, version_end) if end else version_end
                start = max(start, date_from)
                end = min(end, date_to) if end else date_to
                if start <= end:
                    intervals.append((start, end))
            if intervals:
                result[employee_id] = intervals
        return result

    @staticmethod
    def _days_in_range(intervals, date_from, date_to):
        """Number of days of ``intervals`` that fall within [date_from, date_to]."""
        return sum(
            max((min(end, date_to) - max(start, date_from)).days + 1, 0)
            for start, end in intervals
        )

    def _get_employee_results(self):
        """Per-employee bonus figures, computed on the fly (nothing is stored).

        The bonus base from the employee KPI config is prorated by the share of
        the period the employee held the job position, so that an employee
        transferred mid-period is not paid the full base on both scorecards.
        """
        self.ensure_one()
        intervals = self._get_employee_intervals()
        if not intervals:
            return []
        period = self.period_id
        period_days = (period.date_to - period.date_from).days + 1
        Config = self.env['hr.scorecard.employee.config']
        results = []
        for employee in self.env['hr.employee'].browse(list(intervals)):
            days = self._days_in_range(intervals[employee.id], period.date_from, period.date_to)
            config = Config.get_for_employee(employee, self.company_id)
            bonus_base = float_round(config.bonus_base * days / period_days, precision_digits=2)
            results.append({
                'employee': employee,
                'config': config,
                'intervals': intervals[employee.id],
                'days': days,
                'period_days': period_days,
                'bonus_base': bonus_base,
                'bonus_amount': float_round(
                    bonus_base * self.weighted_result / 100.0, precision_digits=2,
                ),
            })
        return results

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------

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
            if card.advance_bonus_ids or card.final_bonus_ids:
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

    def action_open_employees(self):
        """Show the employees of the job position with their bonus figures."""
        self.ensure_one()
        Result = self.env['hr.scorecard.employee.result']
        records = Result.create([
            {
                'scorecard_id': self.id,
                'employee_id': result['employee'].id,
                'date_from': min(start for start, _end in result['intervals']),
                'date_to': max(end for _start, end in result['intervals']),
                'days_in_position': result['days'],
                'period_days': result['period_days'],
                'bonus_model': result['config'].bonus_model,
                'bonus_type_id': result['config'].bonus_type_id.id,
                'planned_bonus': result['config'].bonus_base,
                'bonus_base': result['bonus_base'],
                'bonus_amount': result['bonus_amount'],
                'accrued_amount': sum(self.bonus_ids.filtered(
                    lambda b, employee=result['employee']: b.employee_id == employee
                ).mapped('amount')),
            }
            for result in self._get_employee_results()
        ])
        return {
            'type': 'ir.actions.act_window',
            'name': _('Employees'),
            'res_model': 'hr.scorecard.employee.result',
            'view_mode': 'list',
            'views': [(self.env.ref('l10n_ua_hr_scorecard.hr_scorecard_employee_result_view_list').id, 'list')],
            'domain': [('id', 'in', records.ids)],
            'target': 'current',
        }

    def action_accrue_bonus(self):
        for card in self:
            card._accrue_bonus()
        return True

    def _accrue_bonus(self):
        """Create hr.bonus records for the employees of this scorecard.

        Each employee follows the bonus model of their own KPI config;
        employees without a config are skipped. Idempotent per employee: an
        employee who already has advances or a final bonus on this scorecard
        is not accrued them again.

        * Period-based: one bonus once the scorecard is closed.
        * Monthly advance: one advance per month of the period as soon as the
          scorecard is confirmed, prorated by the days in the position within
          that month, and a reconciliation of the difference on close.
        """
        self.ensure_one()
        if self.state == 'draft':
            raise UserError(_('Confirm the scorecard before accruing bonuses.'))
        Bonus = self.env['hr.bonus']
        period = self.period_id

        for result in self._get_employee_results():
            employee = result['employee']
            config = result['config']
            if not config:
                continue
            advances = self.advance_bonus_ids.filtered(lambda b: b.employee_id == employee)
            finals = self.final_bonus_ids.filtered(lambda b: b.employee_id == employee)

            if config.bonus_model == 'monthly_advance' and not advances:
                months = period.months_in_period()
                if not months:
                    raise UserError(_('Period does not cover any month.'))
                per_month = config.bonus_base / len(months)
                for year, month in months:
                    month_start = date(year, month, 1)
                    month_end = date(year, month, calendar.monthrange(year, month)[1])
                    days = self._days_in_range(result['intervals'], month_start, month_end)
                    amount = float_round(
                        per_month * days / month_end.day, precision_digits=2,
                    )
                    if self.currency_id.is_zero(amount):
                        continue
                    advances |= Bonus.create(self._prepare_bonus_vals(
                        employee, config,
                        amount=amount,
                        bonus_date=month_end,
                        note=_('Monthly advance from scorecard %s (%d-%02d)') % (
                            self.name, year, month,
                        ),
                    ))
                self.advance_bonus_ids = [Command.link(bonus.id) for bonus in advances]

            if self.state != 'closed' or finals:
                continue
            if config.bonus_model == 'period':
                amount = result['bonus_amount']
                note = _('Auto-accrued from scorecard %s') % self.name
            else:
                amount = float_round(
                    result['bonus_amount'] - sum(advances.mapped('amount')),
                    precision_digits=2,
                )
                note = _('Reconciliation for scorecard %s') % self.name
            if self.currency_id.is_zero(amount):
                continue
            bonus = Bonus.create(self._prepare_bonus_vals(
                employee, config, amount=amount, bonus_date=period.date_to, note=note,
            ))
            self.final_bonus_ids = [Command.link(bonus.id)]

    def _prepare_bonus_vals(self, employee, config, amount, bonus_date, note):
        self.ensure_one()
        return {
            'employee_id': employee.id,
            'bonus_type_id': config.bonus_type_id.id,
            'date': bonus_date,
            'amount': amount,
            'company_id': self.company_id.id,
            'notes': note,
        }
