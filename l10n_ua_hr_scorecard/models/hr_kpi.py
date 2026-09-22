import string

from odoo import models, fields, api, _
from odoo.exceptions import UserError, ValidationError

from .kpi_formula import FormulaError, formula_variables

# Odoo parameters of the "Income and Expenses (P&L)" report (l10n_ua_accounting):
# keys are the line keys of its PNL_LINES, labels are its line names.
PNL_REPORT_PARAMETERS = [
    ('net_revenue', 'Net revenue from sales of products (goods, works, services)'),
    ('cost_of_sales', 'Cost of products (goods, works, services) sold'),
    ('gross_profit', 'Gross profit (loss)'),
    ('other_operating_income', 'Other operating income'),
    ('administrative_expenses', 'Administrative expenses'),
    ('selling_expenses', 'Selling expenses'),
    ('other_operating_expenses', 'Other operating expenses'),
    ('operating_profit', 'Financial result from operating activities'),
    ('financial_income', 'Financial income'),
    ('financial_expenses', 'Financial expenses'),
    ('other_income', 'Other income'),
    ('other_expenses', 'Other expenses'),
    ('profit_before_tax', 'Financial result before tax'),
    ('income_tax_expense', 'Income tax expense (income)'),
    ('net_profit', 'Net financial result'),
]

# Every Odoo parameter, and the model of the reports it is read from. A KPI
# target picks one record of that model; `hr.kpi.target` reads the value with
# `_read_system_value_<model with dots replaced by underscores>`. Parameters of
# other reports are added to both.
SYSTEM_PARAMETERS = PNL_REPORT_PARAMETERS
SYSTEM_PARAMETER_MODELS = dict.fromkeys(
    (key for key, _label in PNL_REPORT_PARAMETERS), 'l10n_ua.pnl.report',
)


class HrKpi(models.Model):
    _name = 'hr.kpi'
    _description = 'Key Performance Indicator'
    _order = 'sequence, name'

    name = fields.Char(string='Name', required=True, translate=True)
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)
    description = fields.Text(string='Description', translate=True)
    state = fields.Selection([
        ('draft', 'Draft'),
        ('confirmed', 'Confirmed'),
    ], string='Status', required=True, default='draft', copy=False,
        help='Only confirmed KPIs can be picked for KPI targets and assignments; '
             'a confirmed KPI cannot be edited until it is reset to draft.')
    calculation_method = fields.Selection([
        ('binary', 'Binary (achieved / not achieved)'),
        ('coefficient', 'Fulfillment coefficient (actual / planned)'),
    ], string='Calculation Method', required=True, default='coefficient')
    data_source = fields.Selection([
        ('manual', 'Manual input'),
        ('system', 'Odoo data'),
    ], string='Data Source', required=True, default='manual',
        help='Where the actual value of the KPI targets comes from: typed in by hand, '
             'or read from Odoo data for the period and company of the target.')
    system_field = fields.Selection(
        SYSTEM_PARAMETERS,
        string='Odoo Parameter',
        help='Figure of an Odoo report used as the actual value. The report itself '
             '(e.g. a P&L statement, Form No. 2) is chosen on each KPI target.',
    )
    system_source_model = fields.Char(
        string='Source Report Model',
        compute='_compute_system_source_model',
        help='Technical name of the model of the reports the Odoo parameter is read from.',
    )
    use_formula = fields.Boolean(
        string='Formula Builder',
        help='For Odoo data: compute the actual value of the targets with a formula of '
             'parameters of Odoo reports and numbers.',
    )
    variable_ids = fields.One2many('hr.kpi.variable', 'kpi_id', string='Variables', copy=True)
    formula = fields.Char(
        string='Formula',
        help='Arithmetic expression of the variable codes and numbers, with + - * / and '
             'parentheses, e.g. (A - B) / C * 100.',
    )
    formula_error = fields.Char(
        string='Formula Error',
        compute='_compute_formula_error',
        help='Why the formula cannot be used, if it cannot.',
    )
    source_models = fields.Char(
        string='Source Report Models',
        compute='_compute_source_models',
        help='Comma-separated technical names of the models of the reports the targets read from.',
    )
    target_count = fields.Integer(string='Target Count', compute='_compute_counts')
    job_count = fields.Integer(
        string='Job Position Count', compute='_compute_counts',
        help='Job positions whose KPI assignment in force today includes this KPI.',
    )
    employee_count = fields.Integer(
        string='Employee Count', compute='_compute_counts',
        help='Employees currently holding a job position that has this KPI.',
    )
    uom_name = fields.Char(
        string='Unit of Measure',
        help='Free-form unit shown next to planned/actual values (UAH, pcs, %, ...).',
    )
    higher_is_better = fields.Boolean(
        string='Higher is better',
        default=True,
        help='Uncheck for KPIs where lower actual value means better performance '
             '(e.g. defects, downtime). The coefficient is then inverted: planned / actual.',
    )
    company_id = fields.Many2one(
        'res.company',
        string='Company',
        default=lambda self: self.env.company,
        domain=lambda self: [('id', 'in', self.env.companies.ids)],
    )

    @api.depends('data_source', 'system_field')
    def _compute_system_source_model(self):
        for kpi in self:
            kpi.system_source_model = kpi.data_source == 'system' \
                and SYSTEM_PARAMETER_MODELS.get(kpi.system_field) or False

    def _compute_counts(self):
        Target = self.env['hr.kpi.target']
        for kpi in self:
            if not kpi.id:
                kpi.target_count = kpi.job_count = kpi.employee_count = 0
                continue
            kpi.target_count = Target.search_count([('kpi_id', '=', kpi.id)])
            jobs_by_company = kpi._get_assigned_jobs()
            kpi.job_count = len(set().union(*jobs_by_company.values())) if jobs_by_company else 0
            kpi.employee_count = len(kpi._get_assigned_employees(jobs_by_company))

    def _get_assigned_jobs(self, date=None):
        """Return ``{company: job positions}`` whose KPI assignment in force
        on ``date`` (today by default) includes this KPI."""
        self.ensure_one()
        date = date or fields.Date.context_today(self)
        Assignment = self.env['hr.kpi.assignment']
        lines = self.env['hr.kpi.assignment.line'].search([
            ('kpi_id', '=', self.id),
            ('assignment_id.date_from', '<=', date),
        ])
        result = {}
        for company, company_lines in lines.grouped('company_id').items():
            for job in company_lines.job_id:
                assignment = Assignment._get_in_force(job, company, date)
                if self in assignment.line_ids.kpi_id:
                    result.setdefault(company, self.env['hr.job'])
                    result[company] |= job
        return result

    def _get_assigned_employees(self, jobs_by_company=None, date_from=None, date_to=None):
        """Employees who hold a job position that has this KPI on at least one
        day of [date_from, date_to] (today by default), according to the
        version history as on the KPI map."""
        self.ensure_one()
        today = fields.Date.context_today(self)
        date_from = date_from or today
        date_to = date_to or date_from
        if jobs_by_company is None:
            jobs_by_company = self._get_assigned_jobs(date_from)
        Scorecard = self.env['hr.scorecard']
        employee_ids = set()
        for company, jobs in jobs_by_company.items():
            for job in jobs:
                employee_ids.update(
                    Scorecard._get_job_employee_intervals_between(job, company, date_from, date_to)
                )
        return self.env['hr.employee'].browse(sorted(employee_ids))

    def action_confirm(self):
        for kpi in self:
            if kpi.state != 'draft':
                raise UserError(_('Only draft KPIs can be confirmed.'))
        self.write({'state': 'confirmed'})

    def action_draft(self):
        for kpi in self:
            if kpi.state != 'confirmed':
                raise UserError(_('Only confirmed KPIs can be reset to draft.'))
        self.write({'state': 'draft'})

    def action_open_targets(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('KPI Targets of %s', self.name),
            'res_model': 'hr.kpi.target',
            'view_mode': 'list,form',
            'domain': [('kpi_id', '=', self.id)],
            'context': {'create': False},
        }

    def action_open_jobs(self):
        self.ensure_one()
        jobs = self.env['hr.job'].union(*self._get_assigned_jobs().values())
        return {
            'type': 'ir.actions.act_window',
            'name': _('Job Positions with %s', self.name),
            'res_model': 'hr.job',
            'view_mode': 'list,form',
            'domain': [('id', 'in', jobs.ids)],
            'context': {'create': False},
        }

    def action_open_employees(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Employees with %s', self.name),
            'res_model': 'hr.employee',
            'view_mode': 'list,kanban,form',
            'domain': [('id', 'in', self._get_assigned_employees().ids)],
            'context': {'create': False},
        }

    @api.depends('use_formula', 'formula', 'variable_ids.code')
    def _compute_formula_error(self):
        for kpi in self:
            kpi.formula_error = kpi.use_formula and kpi._get_formula_error() or False

    @api.depends('data_source', 'system_field', 'use_formula', 'variable_ids.source_model')
    def _compute_source_models(self):
        for kpi in self:
            kpi.source_models = ','.join(kpi._get_source_models())

    def _get_source_models(self):
        """Models of the reports the targets of this KPI read from, in order."""
        self.ensure_one()
        if self.data_source != 'system':
            return []
        if self.use_formula:
            models_ = self.variable_ids.mapped('source_model')
        else:
            models_ = [self.system_source_model]
        return list(dict.fromkeys(model for model in models_ if model))

    def _get_formula_error(self):
        """Translated reason why the formula is not usable, or ``False``."""
        self.ensure_one()
        try:
            used = formula_variables(self.formula)
        except FormulaError as error:
            return {
                'empty': _('Enter the formula.'),
                'syntax': _('The formula is not a valid arithmetic expression.'),
                'unsupported': _('Only numbers, variable codes, + - * / and parentheses are allowed '
                                 'in the formula.'),
            }[error.args[0]]
        unknown = sorted(used - set(self.variable_ids.mapped('code')))
        if unknown:
            return _('Unknown variables in the formula: %s.', ', '.join(unknown))
        return False

    @api.constrains('use_formula', 'formula', 'variable_ids')
    def _check_formula(self):
        for kpi in self:
            if not kpi.use_formula:
                continue
            if not kpi.variable_ids:
                raise ValidationError(_('Add at least one variable to the formula of KPI %s.', kpi.name))
            error = kpi._get_formula_error()
            if error:
                raise ValidationError(_('KPI %(kpi)s: %(error)s', kpi=kpi.name, error=error))

    @api.constrains('data_source', 'use_formula')
    def _check_formula_data_source(self):
        for kpi in self:
            if kpi.use_formula and kpi.data_source != 'system':
                raise ValidationError(_(
                    'The formula builder of KPI %s works with Odoo data: select Odoo data as its '
                    'data source.', kpi.name,
                ))

    @api.constrains('data_source', 'system_field', 'use_formula')
    def _check_system_field(self):
        for kpi in self:
            if kpi.data_source == 'system' and not kpi.use_formula and not kpi.system_field:
                raise ValidationError(_('Select the Odoo parameter of KPI %s.') % kpi.name)

    @api.onchange('data_source')
    def _onchange_data_source(self):
        if self.data_source != 'system':
            self.system_field = False
            self.use_formula = False

    @api.onchange('variable_ids')
    def _onchange_variable_codes(self):
        """Give new variables the first free letter as code."""
        used = set()
        for variable in self.variable_ids:
            if variable.code and variable.code not in used:
                used.add(variable.code)
                continue
            variable.code = next(
                (letter for letter in string.ascii_uppercase if letter not in used), False,
            )
            used.add(variable.code)

    @api.model_create_multi
    def create(self, vals_list):
        kpis = super().create(vals_list)
        kpis._sync_target_inputs()
        return kpis

    def write(self, vals):
        res = super().write(vals)
        if {'use_formula', 'variable_ids', 'data_source', 'system_field'} & set(vals):
            self._sync_target_inputs()
        return res

    def _sync_target_inputs(self):
        """Give the draft targets of these KPIs one input per variable and one
        source line per report model; confirmed targets keep what they have."""
        targets = self.env['hr.kpi.target'].search([
            ('kpi_id', 'in', self.ids), ('state', '=', 'draft'),
        ])
        targets._sync_formula_lines()
