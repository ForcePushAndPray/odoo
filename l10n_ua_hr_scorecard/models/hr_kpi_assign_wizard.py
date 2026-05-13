from odoo import models, fields, api, _
from odoo.exceptions import UserError


class HrKpiAssignWizard(models.TransientModel):
    _name = 'hr.kpi.assign.wizard'
    _description = 'Assign KPI to Employees'

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
    employee_ids = fields.Many2many(
        'hr.employee',
        string='Employees',
        domain="[('company_id', '=', company_id)]",
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
        if 'employee_ids' in fields_list and kpi_id and period_id:
            lines = self.env['hr.scorecard.line'].search([
                ('kpi_id', '=', kpi_id),
                ('scorecard_id.period_id', '=', period_id),
                ('scorecard_id.company_id', '=', company_id),
            ])
            current_emp_ids = lines.mapped('scorecard_id.employee_id').ids
            vals['employee_ids'] = [(6, 0, current_emp_ids)]
        return vals

    @api.onchange('company_id')
    def _onchange_company_id(self):
        """Drop selected employees that don't belong to the new company."""
        if self.company_id and self.employee_ids:
            mismatched = self.employee_ids.filtered(
                lambda e: e.company_id and e.company_id != self.company_id
            )
            if mismatched:
                self.employee_ids = self.employee_ids - mismatched

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
        current_emp_ids = set(current_lines.mapped('scorecard_id.employee_id').ids)
        new_emp_ids = set(self.employee_ids.ids)

        # Add new assignments
        for emp_id in new_emp_ids - current_emp_ids:
            scorecard = Scorecard.search([
                ('employee_id', '=', emp_id),
                ('period_id', '=', self.period_id.id),
                ('company_id', '=', self.company_id.id),
            ], limit=1)
            if not scorecard:
                scorecard = Scorecard.create({
                    'employee_id': emp_id,
                    'period_id': self.period_id.id,
                    'company_id': self.company_id.id,
                })
            Line.create({
                'scorecard_id': scorecard.id,
                'kpi_id': self.kpi_id.id,
            })

        # Remove deselected assignments; block if scorecard not draft
        to_remove = current_lines.filtered(
            lambda l: l.scorecard_id.employee_id.id not in new_emp_ids
        )
        blocking = to_remove.filtered(lambda l: l.scorecard_id.state != 'draft')
        if blocking:
            sample = blocking[0]
            raise UserError(_(
                'Cannot unassign %(emp)s from KPI %(kpi)s in %(period)s '
                'because the scorecard is %(state)s. '
                'Reset the scorecard to draft first.'
            ) % {
                'emp': sample.scorecard_id.employee_id.name,
                'kpi': self.kpi_id.name,
                'period': self.period_id.name,
                'state': sample.scorecard_id.state,
            })
        to_remove.unlink()

        return {'type': 'ir.actions.act_window_close'}
