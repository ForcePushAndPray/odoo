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
    employee_ids = fields.Many2many(
        'hr.employee',
        string='Employees',
        required=True,
    )
    weight = fields.Float(
        string='Weight (%)',
        default=0.0,
        help='Weight assigned to this KPI on each employee scorecard. '
             'Can be edited later on individual lines.',
    )
    company_id = fields.Many2one(
        'res.company',
        default=lambda self: self.env.company,
        required=True,
    )

    @api.constrains('weight')
    def _check_weight(self):
        for rec in self:
            if rec.weight < 0 or rec.weight > 100:
                raise UserError(_('Weight must be between 0 and 100.'))

    def action_assign(self):
        self.ensure_one()
        Scorecard = self.env['hr.scorecard']
        Line = self.env['hr.scorecard.line']
        created_lines = Line
        for employee in self.employee_ids:
            scorecard = Scorecard.search([
                ('employee_id', '=', employee.id),
                ('period_id', '=', self.period_id.id),
                ('company_id', '=', self.company_id.id),
            ], limit=1)
            if not scorecard:
                scorecard = Scorecard.create({
                    'employee_id': employee.id,
                    'period_id': self.period_id.id,
                    'company_id': self.company_id.id,
                })
            existing = scorecard.line_ids.filtered(lambda l: l.kpi_id.id == self.kpi_id.id)
            if existing:
                continue
            created_lines |= Line.create({
                'scorecard_id': scorecard.id,
                'kpi_id': self.kpi_id.id,
                'weight': self.weight,
            })
        return {
            'type': 'ir.actions.act_window',
            'name': _('Assigned Scorecard Lines'),
            'res_model': 'hr.scorecard.line',
            'view_mode': 'list,form',
            'domain': [('id', 'in', created_lines.ids)],
        }
