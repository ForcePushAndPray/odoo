from collections import defaultdict

from odoo import models, fields, api, _
from odoo.exceptions import AccessError
from odoo.fields import Domain
from odoo.tools.float_utils import float_round


class HrKpiMap(models.AbstractModel):
    """Data of the "KPI Map" report: every employee with the KPI targets of
    the job positions they held in the targets' periods."""
    _name = 'hr.kpi.map'
    _description = 'KPI Map'

    @api.model
    def action_open(self):
        """Open the KPI map on the KPI targets search, with the period in
        progress preselected in the search panel."""
        self._check_access()
        periods = self.env['hr.kpi.period'].search([
            ('target_ids.company_id', 'in', self.env.companies.ids),
        ])
        context = {}
        period = self._default_period(periods)
        if period:
            context['searchpanel_default_period_id'] = period.id
        return {
            'type': 'ir.actions.act_window',
            'name': _('KPI Map'),
            'res_model': 'hr.kpi.target',
            'views': [(self.env.ref('l10n_ua_hr_scorecard.hr_kpi_map_view').id, 'list')],
            'search_view_id': [self.env.ref('l10n_ua_hr_scorecard.hr_kpi_target_view_search').id],
            'context': context,
            'target': 'current',
        }

    @api.model
    def get_map_data(self, domain=None):
        """Return the employees of the KPI targets matching ``domain``.

        The job positions of a target are those whose KPI assignment in force
        at the start of the period includes its KPI, with the weight given
        there. Employees are not stored anywhere: they are the holders of each
        job position during the period, read from the version history (see
        ``hr.scorecard._get_job_employee_intervals``).
        """
        self._check_access()
        company_ids = self.env.companies.ids
        targets = self.env['hr.kpi.target'].search(Domain.AND([
            Domain(domain or []),
            Domain('company_id', 'in', company_ids),
        ]))
        Scorecard = self.env['hr.scorecard']
        Assignment = self.env['hr.kpi.assignment']
        periods = targets.period_id.sorted(
            lambda period: (period.date_from, -(period.date_to - period.date_from).days)
        )
        # {employee_id: {(job, company): {'kpis': {kpi: {period_id: cell}}, 'totals': {period_id: total}}}}
        rows = defaultdict(lambda: defaultdict(lambda: {'kpis': defaultdict(dict), 'totals': {}}))
        for (period, company), period_targets in targets.grouped(lambda t: (t.period_id, t.company_id)).items():
            targets_by_kpi = {target.kpi_id: target for target in period_targets}
            # Job positions whose assignment in force at the start of the period
            # includes a KPI of these targets.
            lines = self.env['hr.kpi.assignment.line'].search([
                ('kpi_id', 'in', period_targets.kpi_id.ids),
                ('company_id', '=', company.id),
                ('assignment_id.date_from', '<=', period.date_from),
            ])
            period_days = (period.date_to - period.date_from).days + 1
            for job in lines.job_id:
                assignment = Assignment._get_in_force(job, company, period.date_from)
                job_lines = assignment.line_ids.filtered(lambda line: line.kpi_id in targets_by_kpi)
                if not job_lines:
                    continue
                intervals = Scorecard._get_job_employee_intervals(job, period, company)
                if not intervals:
                    continue
                cells = {
                    line.kpi_id: self._target_values(targets_by_kpi[line.kpi_id], line.weight)
                    for line in job_lines
                }
                total = {
                    'total_weight': float_round(assignment.total_weight, precision_digits=2),
                    'weighted_result': float_round(
                        sum(cell['achievement'] * cell['weight'] / 100.0 for cell in cells.values()),
                        precision_digits=2,
                    ),
                    'period_days': period_days,
                }
                for employee_id, employee_intervals in intervals.items():
                    days = Scorecard._days_in_range(employee_intervals, period.date_from, period.date_to)
                    row = rows[employee_id][(job, company)]
                    for kpi, cell in cells.items():
                        row['kpis'][kpi][period.id] = cell
                    row['totals'][period.id] = {**total, 'days': days, 'partial': days < period_days}

        employees = self.env['hr.employee'].with_context(active_test=False).search(
            [('id', 'in', list(rows))], order='name',
        )
        result = []
        for employee in employees:
            jobs = []
            for (job, company), row in sorted(rows[employee.id].items(), key=lambda item: item[0][0].display_name):
                kpis = sorted(row['kpis'], key=lambda kpi: (kpi.sequence, kpi.name or ''))
                jobs.append({
                    'key': f'{job.id}-{company.id}',
                    'id': job.id,
                    'name': job.display_name,
                    'company': company.name if len(company_ids) > 1 else '',
                    'kpis': [{
                        'id': kpi.id,
                        'name': kpi.name,
                        'uom': kpi.uom_name or '',
                        'cells': {str(period_id): cell for period_id, cell in row['kpis'][kpi].items()},
                    } for kpi in kpis],
                    'totals': {str(period_id): total for period_id, total in row['totals'].items()},
                })
            result.append({
                'id': employee.id,
                'name': employee.name,
                'jobs': jobs,
                # One row per KPI plus the weighted result row of each job position
                'row_count': sum(len(job['kpis']) + 1 for job in jobs),
            })
        return {
            'periods': [{'id': period.id, 'name': period.display_name} for period in periods
                        if any(str(period.id) in job['totals'] for employee in result for job in employee['jobs'])],
            'employees': result,
        }

    @api.model
    def _check_access(self):
        if not self.env.user.has_group('hr.group_hr_user'):
            raise AccessError(_('Only HR users can see the KPI map.'))

    @api.model
    def _default_period(self, periods):
        """The period to open on: the shortest one in progress today, else the
        latest one that has already started, else the first one."""
        today = fields.Date.context_today(self)
        current = periods.filtered(lambda p: p.date_from <= today <= p.date_to)
        if current:
            return current.sorted(lambda p: (p.date_to - p.date_from).days)[:1]
        started = periods.filtered(lambda p: p.date_from <= today)
        if started:
            return started.sorted(lambda p: (p.date_from, -(p.date_to - p.date_from).days), reverse=True)[:1]
        return periods[:1]

    @api.model
    def _target_values(self, target, weight):
        return {
            'target_id': target.id,
            'kpi': target.kpi_id.name,
            'calculation_method': target.calculation_method,
            'uom': target.uom_name or '',
            'weight': weight,
            'planned': target.planned_value,
            'actual': target.actual_value,
            'achieved': target.binary_achieved,
            'achievement': target.achievement,
            'state': target.state,
        }
