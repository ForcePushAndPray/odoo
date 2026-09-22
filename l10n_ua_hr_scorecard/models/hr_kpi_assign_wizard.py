from odoo import models, fields, api, _
from odoo.exceptions import UserError


class HrKpiAssignWizard(models.TransientModel):
    _name = 'hr.kpi.assign.wizard'
    _description = 'Assign KPI to Job Positions'
    _check_company_auto = True

    kpi_id = fields.Many2one(
        'hr.kpi',
        string='KPI',
        required=True,
        readonly=True,
    )
    period_id = fields.Many2one(
        'hr.kpi.period',
        string='Period',
        required=True,
        readonly=True,
    )
    company_id = fields.Many2one(
        'res.company',
        string='Company',
        required=True,
        default=lambda self: self.env.company,
        domain=lambda self: [('id', 'in', self.env.companies.ids)],
    )
    job_ids = fields.Many2many(
        'hr.job',
        string='Job Positions',
        check_company=True,
    )

    @api.model
    def default_get(self, fields_list):
        vals = super().default_get(fields_list)
        kpi_id = vals.get('kpi_id') or self.env.context.get('default_kpi_id')
        period_id = vals.get('period_id') or self.env.context.get('default_period_id')
        company_id = vals.get('company_id') or self.env.context.get(
            'default_company_id', self.env.company.id,
        )
        if company_id and company_id not in self.env.companies.ids:
            # context-supplied company is not in the user's allowed set; fall back
            company_id = self.env.company.id
            vals['company_id'] = company_id
        if 'job_ids' in fields_list and kpi_id and period_id:
            lines = self.env['hr.scorecard.line'].search([
                ('kpi_id', '=', kpi_id),
                ('scorecard_id.period_id', '=', period_id),
                ('scorecard_id.company_id', '=', company_id),
            ])
            vals['job_ids'] = [(6, 0, lines.mapped('scorecard_id.job_id').ids)]
        return vals

    @api.onchange('company_id')
    def _onchange_company_id(self):
        """Drop selected job positions that don't belong to the new company."""
        if self.company_id and self.job_ids:
            mismatched = self.job_ids.filtered(
                lambda j: j.company_id and j.company_id != self.company_id
            )
            if mismatched:
                self.job_ids = self.job_ids - mismatched

    def action_save_assignments(self):
        self.ensure_one()
        if self.company_id.id not in self.env.companies.ids:
            raise UserError(_(
                'The selected company is not accessible in your current session.'
            ))
        Scorecard = self.env['hr.scorecard']
        Line = self.env['hr.scorecard.line']
        current_lines = Line.search([
            ('kpi_id', '=', self.kpi_id.id),
            ('scorecard_id.period_id', '=', self.period_id.id),
            ('scorecard_id.company_id', '=', self.company_id.id),
        ])
        current_job_ids = set(current_lines.mapped('scorecard_id.job_id').ids)
        new_job_ids = set(self.job_ids.ids)

        # Add new assignments
        for job_id in new_job_ids - current_job_ids:
            scorecard = Scorecard.search([
                ('job_id', '=', job_id),
                ('period_id', '=', self.period_id.id),
                ('company_id', '=', self.company_id.id),
            ], limit=1)
            if not scorecard:
                scorecard = Scorecard.create({
                    'job_id': job_id,
                    'period_id': self.period_id.id,
                    'company_id': self.company_id.id,
                })
            Line.create({
                'scorecard_id': scorecard.id,
                'kpi_id': self.kpi_id.id,
            })

        # Remove deselected assignments; block if scorecard not draft
        to_remove = current_lines.filtered(
            lambda l: l.scorecard_id.job_id.id not in new_job_ids
        )
        blocking = to_remove.filtered(lambda l: l.scorecard_id.state != 'draft')
        if blocking:
            scorecard = blocking[0].scorecard_id
            states = dict(scorecard._fields['state']._description_selection(self.env))
            raise UserError(_(
                'Cannot remove KPI %(kpi)s from job position %(job)s in %(period)s '
                'because the scorecard is %(state)s. '
                'Reset the scorecard to draft first.'
            ) % {
                'kpi': self.kpi_id.name,
                'job': scorecard.job_id.name,
                'period': self.period_id.display_name,
                'state': states[scorecard.state],
            })
        to_remove.unlink()

        return {'type': 'ir.actions.act_window_close'}
