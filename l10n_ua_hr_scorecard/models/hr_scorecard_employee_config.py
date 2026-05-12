from odoo import models, fields, api, _
from odoo.exceptions import ValidationError
from odoo.tools.float_utils import float_compare


class HrScorecardEmployeeConfig(models.Model):
    _name = 'hr.scorecard.employee.config'
    _description = 'Employee KPI Compensation Config'
    _order = 'employee_id'
    _rec_name = 'employee_id'

    employee_id = fields.Many2one(
        'hr.employee',
        string='Employee',
        required=True,
        index=True,
        ondelete='cascade',
    )
    salary_pct = fields.Float(
        string='Salary Share (%)',
        default=100.0,
        help='Share of total compensation paid as fixed salary.',
    )
    bonus_pct = fields.Float(
        string='Bonus Share (%)',
        default=0.0,
        help='Share of total compensation paid as KPI-driven bonus. '
             'Salary + Bonus shares must sum to 100%.',
    )
    bonus_base = fields.Monetary(
        string='Bonus Base',
        help='Default bonus amount used as the scorecard base when weighted '
             'KPI result equals 100%.',
    )
    bonus_model = fields.Selection([
        ('period', 'Period-based (single payout)'),
        ('monthly_advance', 'Monthly advance with reconciliation'),
    ], string='Bonus Model', required=True, default='period')
    bonus_type_id = fields.Many2one(
        'hr.bonus.type',
        string='Bonus Type',
        required=True,
        help='Type used when auto-accruing hr.bonus records from scorecards.',
    )
    company_id = fields.Many2one(
        'res.company',
        string='Company',
        required=True,
        default=lambda self: self.env.company,
    )
    currency_id = fields.Many2one(
        'res.currency',
        related='company_id.currency_id',
        store=True,
        readonly=True,
    )
    active = fields.Boolean(default=True)
    notes = fields.Text(string='Notes')

    _sql_constraints = [
        ('employee_company_uniq', 'unique(employee_id, company_id)',
         'A KPI compensation config already exists for this employee in this company.'),
    ]

    @api.constrains('salary_pct', 'bonus_pct')
    def _check_shares(self):
        for rec in self:
            total = (rec.salary_pct or 0.0) + (rec.bonus_pct or 0.0)
            if float_compare(total, 100.0, precision_digits=2) != 0:
                raise ValidationError(_(
                    'Salary share + Bonus share must equal 100%% '
                    '(currently %.2f%%).'
                ) % total)

    @api.model
    def get_for_employee(self, employee, company=None):
        """Return the active config for an employee (and optional company)."""
        if not employee:
            return self.browse()
        company = company or self.env.company
        return self.search([
            ('employee_id', '=', employee.id),
            ('company_id', '=', company.id),
        ], limit=1)
