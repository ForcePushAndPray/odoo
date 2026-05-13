from odoo import models, fields, api, _
from odoo.exceptions import UserError
from odoo.tools.float_utils import float_round


class HrKpiTarget(models.Model):
    _name = 'hr.kpi.target'
    _description = 'KPI Target'
    _order = 'period_id desc, kpi_id'
    _rec_name = 'display_name'

    kpi_id = fields.Many2one(
        'hr.kpi',
        string='KPI',
        required=True,
        ondelete='cascade',
        index=True,
    )
    period_id = fields.Many2one(
        'hr.kpi.period',
        string='Period',
        required=True,
        ondelete='cascade',
        index=True,
    )
    calculation_method = fields.Selection(
        related='kpi_id.calculation_method',
        store=True,
        readonly=True,
    )
    higher_is_better = fields.Boolean(
        related='kpi_id.higher_is_better',
        readonly=True,
    )
    uom_name = fields.Char(related='kpi_id.uom_name', readonly=True)
    planned_value = fields.Float(string='Planned Value')
    actual_value = fields.Float(string='Actual Value')
    binary_achieved = fields.Boolean(
        string='Achieved',
        help='Used when calculation method is Binary.',
    )
    achievement = fields.Float(
        string='Achievement (%)',
        compute='_compute_achievement',
        store=True,
        help='100% for Binary if achieved, else 0%. '
             'For Coefficient: actual/planned x 100% (inverted when Higher is better = False).',
    )
    state = fields.Selection([
        ('draft', 'Draft'),
        ('confirmed', 'Confirmed'),
    ], string='Status', required=True, default='draft', index=True)
    company_id = fields.Many2one(
        'res.company',
        string='Company',
        required=True,
        default=lambda self: self.env.company,
    )
    display_name = fields.Char(compute='_compute_display_name', store=True)

    _sql_constraints = [
        ('kpi_period_company_uniq',
         'unique(kpi_id, period_id, company_id)',
         'A KPI target already exists for this KPI and period.'),
    ]

    @api.depends(
        'calculation_method', 'higher_is_better',
        'planned_value', 'actual_value', 'binary_achieved',
    )
    def _compute_achievement(self):
        for target in self:
            if target.calculation_method == 'binary':
                achievement = 100.0 if target.binary_achieved else 0.0
            else:
                if not target.planned_value:
                    achievement = 0.0
                elif target.higher_is_better:
                    achievement = target.actual_value / target.planned_value * 100.0
                else:
                    if not target.actual_value:
                        achievement = 0.0
                    else:
                        achievement = target.planned_value / target.actual_value * 100.0
            target.achievement = float_round(achievement, precision_digits=2)

    @api.depends('kpi_id.name', 'period_id.name')
    def _compute_display_name(self):
        for target in self:
            target.display_name = '%s / %s' % (
                target.kpi_id.name or '',
                target.period_id.name or '',
            )

    def action_confirm(self):
        for target in self:
            if target.state != 'draft':
                raise UserError(_('Only draft targets can be confirmed.'))
        self.write({'state': 'confirmed'})

    def action_draft(self):
        for target in self:
            if target.state != 'confirmed':
                raise UserError(_('Only confirmed targets can be reset to draft.'))
        self.write({'state': 'draft'})

    def action_open_employees(self):
        """Open employees who have this KPI in this period via a scorecard line."""
        self.ensure_one()
        lines = self.env['hr.scorecard.line'].search([
            ('kpi_id', '=', self.kpi_id.id),
            ('scorecard_id.period_id', '=', self.period_id.id),
            ('scorecard_id.company_id', 'in', self.env.companies.ids),
        ])
        employees = lines.mapped('scorecard_id.employee_id')
        return {
            'type': 'ir.actions.act_window',
            'name': _('Employees with %s in %s') % (
                self.kpi_id.name, self.period_id.name,
            ),
            'res_model': 'hr.employee',
            'view_mode': 'list,form',
            'domain': [('id', 'in', employees.ids)],
            'context': {
                'default_kpi_id': self.kpi_id.id,
                'default_period_id': self.period_id.id,
            },
        }

    def action_assign_to_employee(self):
        """Open the wizard to assign this KPI to one or more employees."""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Assign KPI to Employee'),
            'res_model': 'hr.kpi.assign.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_kpi_id': self.kpi_id.id,
                'default_period_id': self.period_id.id,
            },
        }

    def action_open_kpi(self):
        """Open the KPI form for this target's KPI."""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': self.kpi_id.name,
            'res_model': 'hr.kpi',
            'res_id': self.kpi_id.id,
            'view_mode': 'form',
            'target': 'current',
        }

    @api.model
    def get_or_create(self, kpi, period, company=None):
        """Return existing target for (kpi, period, company) or create one in draft."""
        company = company or self.env.company
        target = self.search([
            ('kpi_id', '=', kpi.id),
            ('period_id', '=', period.id),
            ('company_id', '=', company.id),
        ], limit=1)
        if not target:
            target = self.create({
                'kpi_id': kpi.id,
                'period_id': period.id,
                'company_id': company.id,
            })
        return target
