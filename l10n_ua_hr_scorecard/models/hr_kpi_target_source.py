from odoo import models, fields, api, _
from odoo.exceptions import ValidationError

# Form field used to pick the report, per model of the Odoo parameters (see
# SYSTEM_PARAMETER_MODELS in hr_kpi.py). The choice is stored generically in
# `report_id`; each of these Many2one fields reads and writes it, so the form
# offers a regular dropdown with a domain for every report model.
SOURCE_REPORT_FIELDS = {
    'l10n_ua.pnl.report': 'pnl_report_id',
}

# Only reports matching this domain can be a source of actual values: a report
# still being prepared may change.
SOURCE_REPORT_DOMAINS = {
    'l10n_ua.pnl.report': [('state', '=', 'confirmed')],
}

# Menu each report model is opened from: the report type is shown under the
# name users know it by in the menu, rather than the technical model name.
SOURCE_REPORT_MENUS = {
    'l10n_ua.pnl.report': 'l10n_ua_accounting.menu_ua_reports_pnl',
}


class HrKpiTargetSource(models.Model):
    """The report a KPI target reads its Odoo parameters of one report model
    from. A target has one line per report model its KPI needs."""
    _name = 'hr.kpi.target.source'
    _description = 'KPI Target Source Report'
    _order = 'target_id, id'

    target_id = fields.Many2one('hr.kpi.target', string='KPI Target', required=True,
                                ondelete='cascade', index=True)
    company_id = fields.Many2one(related='target_id.company_id')
    model = fields.Char(string='Report Model', required=True)
    model_name = fields.Char(string='Report Type', compute='_compute_model_name')
    report_id = fields.Many2oneReference(string='Report ID', model_field='model')
    pnl_report_id = fields.Many2one(
        'l10n_ua.pnl.report',
        string='Report',
        compute='_compute_report_fields',
        inverse='_inverse_pnl_report_id',
        help='Its dates must be exactly the dates of the period of the target.',
    )
    date_from = fields.Date(string='Report Start', compute='_compute_report_dates')
    date_to = fields.Date(string='Report End', compute='_compute_report_dates')
    report_usable = fields.Boolean(
        string='Report Confirmed',
        compute='_compute_report_usable',
        help='The report is confirmed and can be used as a source of actual values.',
    )
    dates_match = fields.Boolean(
        string='Dates Match',
        compute='_compute_dates_match',
        help='The report covers exactly the period selected on the target.',
    )

    _target_model_uniq = models.Constraint(
        'unique(target_id, model)',
        'A KPI target has one source report per report type.',
    )

    def _get_report(self):
        """The report record (as superuser: only dates and amounts are read)."""
        self.ensure_one()
        if not self.report_id or self.model not in self.env:
            return self.env['hr.kpi.target.source'].browse()
        return self.env[self.model].sudo().browse(self.report_id).exists()

    @api.depends('model')
    @api.depends_context('lang')
    def _compute_model_name(self):
        for source in self:
            source.model_name = self._get_report_type_name(source.model) if source.model else False

    @api.model
    def _get_report_type_name(self, model):
        """Name of a report model as in the menu it is opened from, falling
        back to the model description."""
        menu = self.env.ref(SOURCE_REPORT_MENUS.get(model, ''), raise_if_not_found=False) \
            if model in SOURCE_REPORT_MENUS else None
        if menu:
            return menu.sudo().name
        return self.env['ir.model']._get(model).name

    @api.depends('model', 'report_id')
    def _compute_report_fields(self):
        for source in self:
            for model, fname in SOURCE_REPORT_FIELDS.items():
                source[fname] = self.env[model].browse(source.report_id) \
                    if source.model == model and source.report_id else False

    def _inverse_pnl_report_id(self):
        for source in self:
            if source.model == 'l10n_ua.pnl.report':
                source.report_id = source.pnl_report_id.id

    @api.depends('model', 'report_id')
    def _compute_report_usable(self):
        for source in self:
            report = source._get_report()
            source.report_usable = bool(report) and bool(
                report.filtered_domain(SOURCE_REPORT_DOMAINS.get(source.model, []))
            )

    @api.depends('model', 'report_id')
    def _compute_report_dates(self):
        for source in self:
            report = source._get_report()
            has_dates = report and 'date_from' in report._fields and 'date_to' in report._fields
            source.date_from = report.date_from if has_dates else False
            source.date_to = report.date_to if has_dates else False

    @api.depends('date_from', 'date_to', 'target_id.selected_date_from', 'target_id.selected_date_to')
    def _compute_dates_match(self):
        for source in self:
            target = source.target_id
            source.dates_match = bool(
                source.date_from and target.selected_date_from
                and (source.date_from, source.date_to)
                == (target.selected_date_from, target.selected_date_to)
            )

    @api.constrains('report_id')
    def _check_report(self):
        for source in self.filtered('report_id'):
            if source._get_report() and not source.report_usable:
                raise ValidationError(_(
                    'The report %(report)s is not confirmed: only confirmed %(type)s reports can be '
                    'a source of actual values.',
                    report=source._get_report().display_name, type=source.model_name,
                ))
        self.target_id._check_source_reports()

    def write(self, vals):
        res = super().write(vals)
        if 'report_id' in vals:
            self.target_id._update_computed_actual_value()
        return res
