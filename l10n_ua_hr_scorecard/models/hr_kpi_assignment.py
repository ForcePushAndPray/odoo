from odoo import models, fields, api, _
from odoo.exceptions import ValidationError
from odoo.tools.float_utils import float_compare


class HrKpiAssignment(models.Model):
    """The KPIs of a job position and their weights, from a date on.

    An assignment is in force from `date_from` until the next assignment of
    the same job position starts, so weights can change (e.g. from a new year)
    without rewriting the past.
    """
    _name = 'hr.kpi.assignment'
    _description = 'KPI Assignment'
    _order = 'job_id, date_from desc, id desc'
    _check_company_auto = True

    job_id = fields.Many2one(
        'hr.job', string='Job Position', required=True, index=True, check_company=True,
    )
    department_id = fields.Many2one(related='job_id.department_id', store=True)
    date_from = fields.Date(
        string='Valid From', required=True, index=True,
        default=lambda self: fields.Date.context_today(self).replace(month=1, day=1),
        help='The assignment is in force from this date until the next assignment '
             'of the job position starts.',
    )
    date_to = fields.Date(
        string='Valid Until', compute='_compute_date_to',
        help='Last day before the next assignment of the job position, if any.',
    )
    company_id = fields.Many2one(
        'res.company', string='Company', required=True,
        default=lambda self: self.env.company,
        domain=lambda self: [('id', 'in', self.env.companies.ids)],
    )
    line_ids = fields.One2many('hr.kpi.assignment.line', 'assignment_id', string='KPIs', copy=True)
    kpi_count = fields.Integer(string='KPI Count', compute='_compute_totals', store=True)
    total_weight = fields.Float(string='Total Weight (%)', compute='_compute_totals', store=True)
    employee_count = fields.Integer(
        string='Employee Count', compute='_compute_employee_count',
        help='Employees who hold the job position while the assignment is in force '
             '(up to today for an assignment still in force).',
    )
    target_count = fields.Integer(
        string='Target Count', compute='_compute_target_count',
        help='KPI targets of these KPIs for the periods starting while the assignment is in force.',
    )
    active = fields.Boolean(default=True)

    _job_date_company_uniq = models.Constraint(
        'unique(job_id, date_from, company_id)',
        'A job position already has a KPI assignment from this date.',
    )

    @api.depends('line_ids.weight', 'line_ids.kpi_id')
    def _compute_totals(self):
        for assignment in self:
            assignment.kpi_count = len(assignment.line_ids)
            assignment.total_weight = sum(assignment.line_ids.mapped('weight'))

    @api.depends('job_id', 'company_id', 'date_from')
    def _compute_date_to(self):
        for assignment in self:
            following = assignment.id and self.search([
                ('job_id', '=', assignment.job_id.id),
                ('company_id', '=', assignment.company_id.id),
                ('date_from', '>', assignment.date_from),
            ], order='date_from', limit=1)
            assignment.date_to = following and fields.Date.subtract(following.date_from, days=1)

    @api.depends('job_id', 'date_from')
    def _compute_display_name(self):
        for assignment in self:
            assignment.display_name = _(
                '%(job)s from %(date)s',
                job=assignment.job_id.display_name or '',
                date=fields.Date.to_string(assignment.date_from) if assignment.date_from else '',
            )

    @api.model_create_multi
    def create(self, vals_list):
        # Lines are saved one by one: check the total once all are written.
        assignments = super(
            HrKpiAssignment, self.with_context(kpi_assignment_defer_weight_check=True),
        ).create(vals_list)
        assignments.with_env(self.env)._check_total_weight()
        return assignments.with_env(self.env)

    def write(self, vals):
        res = super(
            HrKpiAssignment, self.with_context(kpi_assignment_defer_weight_check=True),
        ).write(vals)
        if 'line_ids' in vals:
            self._check_total_weight()
        return res

    @api.constrains('line_ids')
    def _check_total_weight_constraint(self):
        if not self.env.context.get('kpi_assignment_defer_weight_check'):
            self._check_total_weight()

    def _check_total_weight(self):
        for assignment in self:
            if float_compare(assignment.total_weight, 100.0, precision_digits=2) > 0:
                raise ValidationError(_(
                    'The total weight of the KPIs of job position %(job)s is %(total)s%%. '
                    'It must not exceed 100%%.',
                    job=assignment.job_id.display_name,
                    total=round(assignment.total_weight, 2),
                ))

    @api.model
    def _get_in_force(self, job, company, date):
        """The assignment of ``job`` in ``company`` in force on ``date``."""
        return self.search([
            ('job_id', '=', job.id),
            ('company_id', '=', company.id),
            ('date_from', '<=', date),
        ], order='date_from desc', limit=1)

    def _get_targets_domain(self):
        """KPI targets of the KPIs of this assignment whose period starts while
        the assignment is in force."""
        self.ensure_one()
        domain = [
            ('kpi_id', 'in', self.line_ids.kpi_id.ids),
            ('company_id', '=', self.company_id.id),
            ('period_id.date_from', '>=', self.date_from),
        ]
        if self.date_to:
            domain.append(('period_id.date_from', '<=', self.date_to))
        return domain

    @api.depends('line_ids.kpi_id', 'company_id', 'date_from', 'date_to')
    def _compute_target_count(self):
        Target = self.env['hr.kpi.target']
        for assignment in self:
            assignment.target_count = Target.search_count(assignment._get_targets_domain()) \
                if assignment.id and assignment.line_ids else 0

    def _get_employees(self):
        """Holders of the job position while the assignment is in force: from
        its start until its end, or until today if it is still in force."""
        self.ensure_one()
        if not (self.job_id and self.date_from):
            return self.env['hr.employee']
        date_to = self.date_to or max(fields.Date.context_today(self), self.date_from)
        intervals = self.env['hr.scorecard']._get_job_employee_intervals_between(
            self.job_id, self.company_id, self.date_from, date_to,
        )
        return self.env['hr.employee'].browse(sorted(intervals))

    @api.depends('job_id', 'company_id', 'date_from', 'date_to')
    def _compute_employee_count(self):
        for assignment in self:
            assignment.employee_count = len(assignment._get_employees()) if assignment.id else 0

    def action_open_employees(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Employees with the KPIs of %s', self.job_id.display_name),
            'res_model': 'hr.employee',
            'view_mode': 'list,kanban,form',
            'domain': [('id', 'in', self._get_employees().ids)],
            'context': {'create': False, 'active_test': False},
        }

    def action_open_kpis(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('KPIs of %s', self.job_id.display_name),
            'res_model': 'hr.kpi',
            'view_mode': 'list,form',
            'domain': [('id', 'in', self.line_ids.kpi_id.ids)],
            'context': {'create': False},
        }

    def action_open_targets(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('KPI Targets of %s', self.job_id.display_name),
            'res_model': 'hr.kpi.target',
            'view_mode': 'list,form',
            'domain': self._get_targets_domain(),
            'context': {'create': False},
        }


class HrKpiAssignmentLine(models.Model):
    _name = 'hr.kpi.assignment.line'
    _description = 'KPI Assignment Line'
    _order = 'assignment_id, sequence, id'
    _check_company_auto = True

    assignment_id = fields.Many2one('hr.kpi.assignment', string='Assignment', required=True,
                                    ondelete='cascade', index=True)
    company_id = fields.Many2one(related='assignment_id.company_id', store=True)
    job_id = fields.Many2one(related='assignment_id.job_id', store=True, index=True)
    sequence = fields.Integer(default=10)
    kpi_id = fields.Many2one('hr.kpi', string='KPI', required=True, check_company=True)
    weight = fields.Float(string='Weight (%)', default=0.0)

    _assignment_kpi_uniq = models.Constraint(
        'unique(assignment_id, kpi_id)',
        'A KPI appears only once in an assignment.',
    )

    @api.constrains('weight')
    def _check_weight(self):
        for line in self:
            if float_compare(line.weight, 0.0, precision_digits=2) < 0 \
                    or float_compare(line.weight, 100.0, precision_digits=2) > 0:
                raise ValidationError(_('Weight must be between 0 and 100.'))
        # Lines written through their assignment are checked by it at the end.
        if not self.env.context.get('kpi_assignment_defer_weight_check'):
            self.assignment_id._check_total_weight()

