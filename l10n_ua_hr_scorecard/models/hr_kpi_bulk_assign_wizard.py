from odoo import models, fields, api, _
from odoo.exceptions import UserError


class HrKpiBulkAssignWizard(models.TransientModel):
    _name = 'hr.kpi.bulk.assign.wizard'
    _description = 'Bulk Assign KPIs by Job Position'

    company_id = fields.Many2one(
        'res.company',
        string='Company',
        required=True,
        default=lambda self: self.env.company,
        domain=lambda self: [('id', 'in', self.env.companies.ids)],
    )
    period_id = fields.Many2one(
        'hr.kpi.period',
        string='Period',
        required=True,
    )

    def action_run(self):
        self.ensure_one()
        if self.company_id.id not in self.env.companies.ids:
            raise UserError(_(
                'The selected company is not accessible in your current session.'
            ))

        company = self.company_id
        period = self.period_id

        Scorecard = self.env['hr.scorecard']
        Line = self.env['hr.scorecard.line']
        Kpi = self.env['hr.kpi']
        Employee = self.env['hr.employee']

        # KPIs that target at least one job position, visible to this company
        kpis = Kpi.search([
            ('active', '=', True),
            '|', ('company_id', '=', False), ('company_id', '=', company.id),
        ]).filtered(lambda k: k.job_ids)

        employees = Employee.search([
            ('company_id', '=', company.id),
            ('job_id', '!=', False),
        ])

        created_scorecards = 0
        created_lines = 0
        skipped_lines = 0
        touched_scorecards = Scorecard

        for employee in employees:
            employee_kpis = kpis.filtered(lambda k: employee.job_id in k.job_ids)
            if not employee_kpis:
                continue

            scorecard = Scorecard.search([
                ('employee_id', '=', employee.id),
                ('period_id', '=', period.id),
                ('company_id', '=', company.id),
            ], limit=1)
            if not scorecard:
                scorecard = Scorecard.create({
                    'employee_id': employee.id,
                    'period_id': period.id,
                    'company_id': company.id,
                })
                created_scorecards += 1

            touched_scorecards |= scorecard
            existing_kpi_ids = set(scorecard.line_ids.mapped('kpi_id').ids)
            for kpi in employee_kpis:
                if kpi.id in existing_kpi_ids:
                    skipped_lines += 1
                    continue
                Line.create({
                    'scorecard_id': scorecard.id,
                    'kpi_id': kpi.id,
                })
                created_lines += 1

        message = _(
            'Created %(sc)d new scorecard(s) and %(lines)d new KPI assignment(s); '
            '%(skipped)d already existed.'
        ) % {
            'sc': created_scorecards,
            'lines': created_lines,
            'skipped': skipped_lines,
        }

        if not touched_scorecards:
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _('No assignments to do'),
                    'message': _(
                        'No employees in %(company)s have a job position that matches '
                        'a KPI for %(period)s.'
                    ) % {
                        'company': company.name,
                        'period': period.name,
                    },
                    'type': 'warning',
                    'sticky': False,
                },
            }

        return {
            'type': 'ir.actions.act_window',
            'name': message,
            'res_model': 'hr.scorecard',
            'view_mode': 'list,form',
            'domain': [('id', 'in', touched_scorecards.ids)],
        }
