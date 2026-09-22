from odoo import models, fields, api, _
from odoo.exceptions import UserError, ValidationError
from odoo.tools.float_utils import float_compare, float_round
from odoo.tools.misc import format_date

from odoo.addons.l10n_ua_accounting.models.l10n_ua_pnl_report import PNL_LINES

from .hr_kpi_period import MONTHS, PERIOD_TYPES, QUARTERS
from .kpi_formula import FormulaError, evaluate_formula

PERIOD_SELECTION_FIELDS = ('period_type', 'period_year', 'period_quarter', 'period_month')


class HrKpiTarget(models.Model):
    _name = 'hr.kpi.target'
    _description = 'KPI Target'
    _order = 'kpi_id, period_date_from, period_date_to desc, id'
    _rec_name = 'display_name'
    _check_company_auto = True

    kpi_id = fields.Many2one(
        'hr.kpi',
        string='KPI',
        required=True,
        ondelete='cascade',
        index=True,
        check_company=True,
    )
    period_id = fields.Many2one(
        'hr.kpi.period',
        string='Period',
        required=True,
        ondelete='cascade',
        index=True,
        check_company=True,
    )
    period_date_from = fields.Date(related='period_id.date_from', store=True, string='Period Start Date')
    period_date_to = fields.Date(related='period_id.date_to', store=True, string='Period End Date')
    # The period is picked as type + year + quarter/month rather than from a
    # list of records; create/write resolve it to `period_id`, generating the
    # period when it does not exist yet.
    period_type = fields.Selection(
        PERIOD_TYPES,
        string='Period Type',
        compute='_compute_period_selection',
        readonly=False,
    )
    period_year = fields.Selection(
        '_selection_years',
        string='Year',
        compute='_compute_period_selection',
        readonly=False,
    )
    period_quarter = fields.Selection(
        QUARTERS,
        string='Quarter',
        compute='_compute_period_selection',
        readonly=False,
    )
    period_month = fields.Selection(
        MONTHS,
        string='Month',
        compute='_compute_period_selection',
        readonly=False,
    )
    period_missing = fields.Boolean(
        string='Period Missing',
        compute='_compute_period_missing',
        help='The selected period does not exist yet and will be generated on save.',
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
    data_source = fields.Selection(related='kpi_id.data_source', readonly=True)
    use_formula = fields.Boolean(related='kpi_id.use_formula')
    system_field_model = fields.Char(related='kpi_id.system_source_model')
    formula = fields.Char(related='kpi_id.formula')
    source_ids = fields.One2many(
        'hr.kpi.target.source', 'target_id', string='Source Reports',
        help='One report per type of report the KPI reads Odoo data from.',
    )
    input_ids = fields.One2many(
        'hr.kpi.target.input', 'target_id', string='Formula Values',
        help='Values of the variables of the KPI formula for this target.',
    )
    selected_date_from = fields.Date(
        string='Period Start', compute='_compute_selected_dates',
        help='First day of the period currently selected on the target.',
    )
    selected_date_to = fields.Date(
        string='Period End', compute='_compute_selected_dates',
        help='Last day of the period currently selected on the target.',
    )
    job_count = fields.Integer(
        string='Job Position Count', compute='_compute_assigned_counts',
        help='Job positions whose KPI assignment in force at the start of the period includes the KPI.',
    )
    employee_count = fields.Integer(
        string='Employee Count', compute='_compute_assigned_counts',
        help='Employees who held such a job position during the period.',
    )
    computed_actual = fields.Boolean(
        string='Computed Actual Value',
        compute='_compute_fetch_state',
        help='The actual value is read from Odoo data or computed by the KPI formula.',
    )
    fetch_ready = fields.Boolean(
        string='Ready to Get Data',
        compute='_compute_fetch_state',
        help='Every source report is selected and covers exactly the period of the target.',
    )
    planned_value = fields.Float(string='Planned Value')
    actual_value = fields.Float(string='Actual Value')
    binary_achieved = fields.Boolean(
        string='Achieved',
        compute='_compute_binary_achieved',
        store=True,
        help='For binary KPIs: whether the actual value reaches the planned value, i.e. is at '
             'least the plan, or at most the plan when "Higher is better" is unchecked.',
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
        domain=lambda self: [('id', 'in', self.env.companies.ids)],
    )
    display_name = fields.Char(compute='_compute_display_name', store=True)

    _kpi_period_company_uniq = models.Constraint(
        'unique(kpi_id, period_id, company_id)',
        'A KPI target already exists for this KPI and period.',
    )

    @api.constrains('kpi_id', 'period_id', 'company_id')
    def _check_nested_periods(self):
        """A KPI has targets either for a period or for the periods inside it,
        never both: otherwise it is unclear whether the achievement is
        measured over the quarter or over its months.

        Periods are calendar months, quarters and years, so two of them
        overlap only when one contains the other.
        """
        for target in self:
            period = target.period_id
            if not (period.date_from and period.date_to):
                continue
            overlapping = self.search([
                ('id', '!=', target.id),
                ('kpi_id', '=', target.kpi_id.id),
                ('company_id', '=', target.company_id.id),
                ('period_id.date_from', '<=', period.date_to),
                ('period_id.date_to', '>=', period.date_from),
            ], limit=1)
            if overlapping:
                raise ValidationError(_(
                    'KPI %(kpi)s already has a target for %(existing)s, which overlaps %(period)s. '
                    'A KPI can have targets either for a period or for the periods inside it, '
                    'not both.',
                    kpi=target.kpi_id.name,
                    existing=overlapping.period_id.display_name,
                    period=period.display_name,
                ))

    @api.model
    def _selection_years(self):
        return self.env['hr.kpi.period']._selection_years()

    @api.depends('period_id')
    def _compute_period_selection(self):
        today = fields.Date.context_today(self)
        for target in self:
            period = target.period_id
            if period:
                target.period_type = period.period_type
                target.period_year = str(period.year)
                target.period_quarter = period.quarter
                target.period_month = period.month
            else:
                target.period_type = 'quarter'
                target.period_year = str(today.year)
                target.period_quarter = str((today.month - 1) // 3 + 1)
                target.period_month = str(today.month)

    @api.depends(*PERIOD_SELECTION_FIELDS, 'company_id')
    def _compute_period_missing(self):
        Period = self.env['hr.kpi.period']
        for target in self:
            definition = Period._definition_from_selection(
                target.period_type, target.period_year,
                target.period_quarter, target.period_month,
            )
            target.period_missing = bool(definition) and not Period._find(
                *definition, company=target.company_id or self.env.company,
            )

    @api.model
    def _resolve_period_vals(self, vals, company, current=None):
        """Turn the period selection fields of ``vals`` into ``period_id``.

        Fields missing from ``vals`` are taken from ``current`` (the record
        being written). The period is generated when it does not exist yet.
        """
        if not any(fname in vals for fname in PERIOD_SELECTION_FIELDS):
            return vals
        vals = dict(vals)
        selection = {
            fname: vals.pop(fname) if fname in vals else (current[fname] if current else False)
            for fname in PERIOD_SELECTION_FIELDS
        }
        Period = self.env['hr.kpi.period']
        definition = Period._definition_from_selection(
            selection['period_type'], selection['period_year'],
            selection['period_quarter'], selection['period_month'],
        )
        if not definition:
            raise UserError(_('Select the period type, year and quarter or month first.'))
        vals['period_id'] = Period._find_or_create(*definition, company=company).id
        return vals

    @api.model_create_multi
    def create(self, vals_list):
        Company = self.env['res.company']
        vals_list = [
            self._resolve_period_vals(
                vals, Company.browse(vals['company_id']) if vals.get('company_id') else self.env.company,
            )
            for vals in vals_list
        ]
        targets = super().create(vals_list)
        targets._sync_formula_lines()
        targets._update_computed_actual_value()
        return targets

    def write(self, vals):
        if not any(fname in vals for fname in PERIOD_SELECTION_FIELDS):
            res = super().write(vals)
        else:
            for target in self:
                company = self.env['res.company'].browse(vals['company_id']) \
                    if vals.get('company_id') else target.company_id
                super(HrKpiTarget, target).write(self._resolve_period_vals(vals, company, current=target))
            res = True
        if 'kpi_id' in vals:
            self._sync_formula_lines()
        if {'kpi_id', 'source_ids', 'input_ids'} & set(vals):
            self._update_computed_actual_value()
        return res

    # ------------------------------------------------------------------
    # Actual value from Odoo data and formulas
    # ------------------------------------------------------------------

    def _sync_formula_lines(self):
        """One input per variable of the KPI formula and one source line per
        report model the KPI reads from; lines of another KPI are dropped.
        Values already entered and reports already chosen are kept."""
        for target in self:
            kpi = target.kpi_id
            variables = kpi.variable_ids if kpi.use_formula else self.env['hr.kpi.variable']
            stale_inputs = target.input_ids.filtered(lambda line: line.variable_id not in variables)
            missing_variables = variables - target.input_ids.variable_id
            models_ = kpi._get_source_models()
            stale_sources = target.source_ids.filtered(lambda line: line.model not in models_)
            missing_models = [model for model in models_ if model not in target.source_ids.mapped('model')]
            commands = {}
            if stale_inputs or missing_variables:
                commands['input_ids'] = [(2, line.id) for line in stale_inputs] + [
                    (0, 0, {'variable_id': variable.id}) for variable in missing_variables
                ]
            if stale_sources or missing_models:
                commands['source_ids'] = [(2, line.id) for line in stale_sources] + [
                    (0, 0, {'model': model}) for model in missing_models
                ]
            if commands:
                super(HrKpiTarget, target).write(commands)

    @api.model
    def _sync_all_formula_lines(self):
        """Called on module update: give existing draft targets the source
        report and formula value lines their KPI needs."""
        self.sudo().search([('state', '=', 'draft')])._sync_formula_lines()

    @api.onchange('kpi_id')
    def _onchange_kpi_id_formula_lines(self):
        """Show the variables and report types of the KPI before saving,
        keeping the values and reports already filled in."""
        kpi = self.kpi_id
        variables = kpi.variable_ids if kpi.use_formula else self.env['hr.kpi.variable']
        values = {line.variable_id.id: line.value for line in self.input_ids}
        self.input_ids = [(5, 0, 0)] + [
            (0, 0, {'variable_id': variable.id, 'value': values.get(variable.id, 0.0)})
            for variable in variables
        ]
        reports = {line.model: line.report_id for line in self.source_ids}
        self.source_ids = [(5, 0, 0)] + [
            (0, 0, {'model': model, 'report_id': reports.get(model, False)})
            for model in (kpi._get_source_models() if kpi else [])
        ]

    @api.depends(*PERIOD_SELECTION_FIELDS)
    def _compute_selected_dates(self):
        Period = self.env['hr.kpi.period']
        for target in self:
            definition = Period._definition_from_selection(
                target.period_type, target.period_year,
                target.period_quarter, target.period_month,
            )
            dates = Period._get_period_dates(*definition) if definition else (False, False)
            target.selected_date_from, target.selected_date_to = dates

    @api.depends(
        'data_source', 'use_formula', 'system_field_model', 'kpi_id.variable_ids.source_model',
        'source_ids.model', 'source_ids.dates_match', 'source_ids.report_id', 'source_ids.report_usable',
        'input_ids.variable_id',
    )
    def _compute_fetch_state(self):
        for target in self:
            target.computed_actual = target.data_source == 'system' or target.use_formula
            target.fetch_ready = target.computed_actual and not target._get_fetch_problems()

    def _get_fetch_problems(self):
        """Translated reasons why the data cannot be got yet: every report
        model and every formula variable of the KPI must have its line, and
        every report must be selected for exactly the selected period."""
        self.ensure_one()
        kpi = self.kpi_id
        problems = []
        unconfirmed = self.source_ids.filtered(lambda source: source.report_id and not source.report_usable)
        if unconfirmed:
            problems.append(_(
                'Confirm the source reports of the KPI target %(target)s first: %(reports)s.',
                target=self.display_name,
                reports=', '.join(source._get_report().display_name for source in unconfirmed),
            ))
        ready_models = set(
            self.source_ids.filtered(
                lambda source: source.report_id and source.report_usable and source.dates_match
            ).mapped('model')
        )
        missing_models = [model for model in kpi._get_source_models() if model not in ready_models]
        if missing_models:
            Source = self.env['hr.kpi.target.source']
            names = [Source._get_report_type_name(model) for model in missing_models]
            problems.append(_(
                'Select the %(types)s report for exactly the period of the KPI target %(target)s.',
                types=', '.join(names), target=self.display_name,
            ))
        if kpi.use_formula:
            missing_variables = kpi.variable_ids - self.input_ids.variable_id
            if missing_variables:
                problems.append(_(
                    'The KPI target %(target)s has no value for the formula variables %(codes)s.',
                    target=self.display_name, codes=', '.join(missing_variables.mapped('code')),
                ))
        return problems

    @api.constrains('source_ids', 'company_id', 'period_id')
    def _check_source_reports(self):
        for target in self:
            period = target.period_id
            for source in target.source_ids.filtered('report_id'):
                report = source._get_report()
                if not report:
                    raise ValidationError(_(
                        'A source report of the KPI target %s does not exist.', target.display_name,
                    ))
                if 'company_id' in report._fields and report.company_id != target.company_id:
                    raise ValidationError(_(
                        'The source report of the KPI target %s belongs to another company.',
                        target.display_name,
                    ))
                if (source.date_from, source.date_to) != (period.date_from, period.date_to):
                    raise ValidationError(_(
                        'The source report %(report)s covers %(report_from)s - %(report_to)s, but the '
                        'period %(period)s of the KPI target covers %(period_from)s - %(period_to)s. '
                        'Select a report for exactly the period of the target.',
                        report=report.display_name,
                        report_from=format_date(self.env, source.date_from),
                        report_to=format_date(self.env, source.date_to),
                        period=period.display_name,
                        period_from=format_date(self.env, period.date_from),
                        period_to=format_date(self.env, period.date_to),
                    ))

    def action_update_from_system(self):
        """Get the data of the source reports and compute the actual value."""
        targets = self.filtered('computed_actual')
        if not targets:
            raise UserError(_(
                'None of the selected KPI targets takes its actual value from Odoo data or a formula.'
            ))
        targets = targets.filtered(lambda target: target.state == 'draft')
        if not targets:
            raise UserError(_('Confirmed KPI targets keep their actual value: reset them to draft first.'))
        # Lines may be missing if the KPI changed while the target was confirmed.
        targets._sync_formula_lines()
        for target in targets:
            target._check_ready_to_fetch()
        targets._update_computed_actual_value(raise_if_not_ready=True)
        return True

    def _check_ready_to_fetch(self):
        self.ensure_one()
        problems = self._get_fetch_problems()
        if problems:
            raise UserError('\n'.join(problems))

    def _update_computed_actual_value(self, raise_if_not_ready=False):
        """Read the Odoo data of draft targets from their source reports and
        compute their actual value (the formula, or the single parameter).

        A confirmed target keeps the value it was confirmed with. Unless asked
        to raise, a target that is not ready (a report missing or for another
        period, a formula that cannot be computed yet) is left as it is.
        """
        for target in self:
            if not target.computed_actual or target.state != 'draft':
                continue
            if not target.fetch_ready:
                if raise_if_not_ready:
                    target._check_ready_to_fetch()
                continue
            reports = {source.model: source._get_report() for source in target.source_ids}
            kpi = target.kpi_id
            if not kpi.use_formula:
                value = target._read_system_value(reports, kpi.system_source_model, kpi.system_field)
            else:
                for line in target.input_ids:
                    line_value = target._read_system_value(
                        reports, line.variable_id.source_model, line.system_field,
                    )
                    if float_compare(line_value, line.value, precision_digits=2):
                        line.value = line_value
                values = {line.code: line.value for line in target.input_ids}
                try:
                    value = evaluate_formula(kpi.formula, values)
                except FormulaError as error:
                    if not raise_if_not_ready:
                        continue
                    if error.args[0] == 'division_by_zero':
                        raise UserError(_(
                            'The formula of KPI %s divides by zero with the values of this target.',
                            kpi.name,
                        )) from error
                    if error.args[0] == 'unknown_variable':
                        reason = _('the target has no value for the variable %s.', error.args[1])
                    else:
                        reason = kpi._get_formula_error() or _('the formula is not valid.')
                    raise UserError(_(
                        'The formula of KPI %(kpi)s cannot be computed: %(error)s',
                        kpi=kpi.name, error=reason,
                    )) from error
            value = float_round(value, precision_digits=2)
            if float_compare(value, target.actual_value, precision_digits=2):
                super(HrKpiTarget, target).write({'actual_value': value})

    def _read_system_value(self, reports, model, parameter):
        self.ensure_one()
        report = reports.get(model)
        reader = getattr(self, '_read_system_value_' + (model or '').replace('.', '_'), None)
        if not report or reader is None:
            raise UserError(_('The Odoo parameter of KPI %s is not supported.', self.kpi_id.name))
        return reader(report, parameter)

    def _read_system_value_l10n_ua_pnl_report(self, report, parameter):
        """Amount of the P&L statement line of ``parameter`` (a PNL_LINES key).

        The report stores its lines when it is calculated; journal items and
        reports are restricted to accountants and only the amount leaves this
        method, hence the superuser.
        """
        self.ensure_one()
        code = next((line[3] for line in PNL_LINES if line[1] == parameter), None)
        if code is None:
            raise UserError(_('The Odoo parameter of KPI %s is not supported.', self.kpi_id.name))
        report = report.sudo()
        if not report.line_ids:
            raise UserError(_(
                'The report %s has not been calculated yet: calculate it first.', report.display_name,
            ))
        line = report.line_ids.filtered(lambda report_line: report_line.code == code)[:1]
        return line.current_amount

    @api.model
    def _recompute_binary_achievement(self):
        """Called on module update: "Achieved" used to be typed in and is now
        derived from the planned and actual values, so existing targets are
        recomputed."""
        targets = self.sudo().with_context(active_test=False).search([])
        self.env.add_to_compute(self._fields['binary_achieved'], targets)
        self.env.add_to_compute(self._fields['achievement'], targets)
        targets.flush_recordset(['binary_achieved', 'achievement'])

    @api.depends('higher_is_better', 'planned_value', 'actual_value')
    def _compute_binary_achieved(self):
        for target in self:
            comparison = float_compare(target.actual_value, target.planned_value, precision_digits=2)
            target.binary_achieved = comparison >= 0 if target.higher_is_better else comparison <= 0

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
        # The KPI may have changed while the targets were confirmed.
        self._sync_formula_lines()

    def _get_assigned_jobs(self):
        """``{company: job positions}`` of the KPI for the period, restricted to
        the company of the target."""
        self.ensure_one()
        if not (self.kpi_id and self.period_id.date_from):
            return {}
        jobs_by_company = self.kpi_id._get_assigned_jobs(self.period_id.date_from)
        return {company: jobs for company, jobs in jobs_by_company.items() if company == self.company_id}

    def _get_assigned_employees(self, jobs_by_company=None):
        self.ensure_one()
        if jobs_by_company is None:
            jobs_by_company = self._get_assigned_jobs()
        if not jobs_by_company:
            return self.env['hr.employee']
        return self.kpi_id._get_assigned_employees(
            jobs_by_company, self.period_id.date_from, self.period_id.date_to,
        )

    @api.depends('kpi_id', 'period_id', 'company_id')
    def _compute_assigned_counts(self):
        for target in self:
            if not target.id:
                target.job_count = target.employee_count = 0
                continue
            jobs_by_company = target._get_assigned_jobs()
            target.job_count = len(self.env['hr.job'].union(*jobs_by_company.values()))
            target.employee_count = len(target._get_assigned_employees(jobs_by_company))

    def action_open_jobs(self):
        self.ensure_one()
        jobs = self.env['hr.job'].union(*self._get_assigned_jobs().values())
        return {
            'type': 'ir.actions.act_window',
            'name': _('Job Positions with %(kpi)s in %(period)s',
                      kpi=self.kpi_id.name, period=self.period_id.display_name),
            'res_model': 'hr.job',
            'view_mode': 'list,form',
            'domain': [('id', 'in', jobs.ids)],
            'context': {'create': False},
        }

    def action_open_employees(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Employees with %(kpi)s in %(period)s',
                      kpi=self.kpi_id.name, period=self.period_id.display_name),
            'res_model': 'hr.employee',
            'view_mode': 'list,kanban,form',
            'domain': [('id', 'in', self._get_assigned_employees().ids)],
            'context': {'create': False, 'active_test': False},
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
