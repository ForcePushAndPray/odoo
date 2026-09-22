import calendar
from datetime import date

from dateutil.relativedelta import relativedelta
from odoo import models, fields, api, _
from odoo.exceptions import ValidationError
from odoo.tools.misc import format_date

PERIOD_TYPES = [
    ('month', 'Month'),
    ('quarter', 'Quarter'),
    ('year', 'Year'),
]
QUARTERS = [
    ('1', 'Q1'),
    ('2', 'Q2'),
    ('3', 'Q3'),
    ('4', 'Q4'),
]
MONTHS = [
    ('1', 'January'),
    ('2', 'February'),
    ('3', 'March'),
    ('4', 'April'),
    ('5', 'May'),
    ('6', 'June'),
    ('7', 'July'),
    ('8', 'August'),
    ('9', 'September'),
    ('10', 'October'),
    ('11', 'November'),
    ('12', 'December'),
]
MIN_YEAR = 2000
MAX_YEAR = 2100


class HrKpiPeriod(models.Model):
    """A calendar month, quarter or year.

    A period is defined only by its type, year and quarter/month; the name and
    the dates are derived from them, so there are no free-form periods.

    Periods form a hierarchy (month -> quarter -> year) through ``parent_id``,
    which the search panels use to nest them. Missing parents are generated.
    """
    _name = 'hr.kpi.period'
    _description = 'KPI Period'
    _order = 'year desc, date_from, period_type desc, id'
    _parent_name = 'parent_id'

    name = fields.Char(
        string='Code',
        compute='_compute_name',
        store=True,
        readonly=True,
        help='Language-independent code of the period, e.g. 2026-Q1, 2026-01 or 2026.',
    )
    period_type = fields.Selection(
        PERIOD_TYPES, string='Period Type', required=True, default='quarter',
    )
    year = fields.Integer(
        string='Year',
        required=True,
        default=lambda self: fields.Date.context_today(self).year,
    )
    quarter = fields.Selection(QUARTERS, string='Quarter')
    month = fields.Selection(MONTHS, string='Month')
    date_from = fields.Date(
        string='Start Date', compute='_compute_dates', store=True, readonly=True,
    )
    date_to = fields.Date(
        string='End Date', compute='_compute_dates', store=True, readonly=True,
    )
    state = fields.Selection([
        ('open', 'Open'),
        ('closed', 'Closed'),
    ], string='Status', required=True, default='open', tracking=False)
    company_id = fields.Many2one(
        'res.company',
        string='Company',
        default=lambda self: self.env.company,
        domain=lambda self: [('id', 'in', self.env.companies.ids)],
    )
    parent_id = fields.Many2one(
        'hr.kpi.period',
        string='Parent Period',
        readonly=True,
        index=True,
        ondelete='restrict',
        help='The quarter of a month, or the year of a quarter.',
    )
    child_ids = fields.One2many('hr.kpi.period', 'parent_id', string='Sub-periods')
    target_ids = fields.One2many(
        'hr.kpi.target',
        'period_id',
        string='KPI Targets',
    )
    target_count = fields.Integer(
        string='KPI Targets Count',
        compute='_compute_target_count',
        store=True,
        help='Number of KPI targets of this very period (not of the periods inside it).',
    )

    _name_company_uniq = models.UniqueIndex(
        '(name, COALESCE(company_id, 0))',
        'This KPI period already exists.',
    )

    @api.depends('target_ids')
    def _compute_target_count(self):
        counts = dict(self.env['hr.kpi.target'].with_context(active_test=False)._read_group(
            [('period_id', 'in', self.ids)], ['period_id'], ['__count'],
        )) if self.ids else {}
        for period in self:
            period.target_count = counts.get(period._origin, 0)

    def action_open_targets(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('KPI Targets of %s', self.display_name),
            'res_model': 'hr.kpi.target',
            'view_mode': 'list,form',
            'domain': [('period_id', '=', self.id)],
            'context': {'create': False},
        }

    @api.depends('period_type', 'year', 'quarter', 'month')
    def _compute_name(self):
        for period in self:
            if not period.year:
                period.name = False
            elif period.period_type == 'quarter' and period.quarter:
                period.name = f'{period.year}-Q{period.quarter}'
            elif period.period_type == 'month' and period.month:
                period.name = f'{period.year}-{int(period.month):02d}'
            elif period.period_type == 'year':
                period.name = str(period.year)
            else:
                period.name = False

    @api.depends('period_type', 'year', 'quarter', 'month')
    def _compute_dates(self):
        for period in self:
            period.date_from, period.date_to = self._get_period_dates(
                period.period_type, period.year, period.quarter, period.month,
            )

    @api.depends('period_type', 'year', 'quarter', 'month')
    @api.depends_context('lang')
    def _compute_display_name(self):
        for period in self:
            period.display_name = period._get_label()

    def _get_label(self):
        """Human-readable period label in the user's language."""
        self.ensure_one()
        if not self.year:
            return ''
        if self.period_type == 'quarter' and self.quarter:
            return _('Q%(quarter)s %(year)s', quarter=self.quarter, year=self.year)
        if self.period_type == 'month' and self.month:
            label = format_date(
                self.env, date(self.year, int(self.month), 1), date_format='LLLL yyyy',
            )
            return label[:1].upper() + label[1:]
        return str(self.year)

    @api.model
    def _get_period_dates(self, period_type, year, quarter, month):
        """Return ``(date_from, date_to)`` of a period, or ``(False, False)``
        when the definition is incomplete."""
        if not year or not MIN_YEAR <= year <= MAX_YEAR:
            return False, False
        if period_type == 'year':
            return date(year, 1, 1), date(year, 12, 31)
        if period_type == 'quarter' and quarter:
            first_month = (int(quarter) - 1) * 3 + 1
            last_month = first_month + 2
            return (date(year, first_month, 1),
                    date(year, last_month, calendar.monthrange(year, last_month)[1]))
        if period_type == 'month' and month:
            month = int(month)
            return date(year, month, 1), date(year, month, calendar.monthrange(year, month)[1])
        return False, False

    @api.model
    def _normalize_vals(self, vals):
        """Drop the quarter/month that the period type does not use, so a
        period never carries a stale value from another type."""
        period_type = vals.get('period_type')
        if period_type:
            if period_type != 'quarter':
                vals['quarter'] = False
            if period_type != 'month':
                vals['month'] = False
        return vals

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            vals.setdefault('period_type', 'quarter')
            self._normalize_vals(vals)
        periods = super().create(vals_list)
        periods._sync_parent()
        return periods

    def write(self, vals):
        res = super().write(self._normalize_vals(dict(vals)))
        if {'period_type', 'year', 'quarter', 'month', 'company_id'} & set(vals):
            self._sync_parent()
        return res

    def _parent_definition(self):
        """Return ``(period_type, year, quarter, month)`` of the parent
        period, or ``None`` for a year."""
        self.ensure_one()
        if self.period_type == 'month' and self.month:
            return ('quarter', self.year, str((int(self.month) - 1) // 3 + 1), False)
        if self.period_type == 'quarter':
            return ('year', self.year, False, False)
        return None

    def _sync_parent(self):
        """Link each period to its parent within the same company (or among
        shared periods), generating the parent when it does not exist."""
        for period in self:
            definition = period._parent_definition()
            parent = self.browse()
            if definition:
                period_type, year, quarter, month = definition
                values = {
                    'period_type': period_type,
                    'year': year,
                    'quarter': quarter,
                    'month': month,
                    'company_id': period.company_id.id,
                }
                parent = self.search([
                    (fname, '=', value) for fname, value in values.items()
                ], limit=1) or self.create(values)
            if period.parent_id != parent:
                super(HrKpiPeriod, period).write({'parent_id': parent.id})

    @api.model
    def _sync_all_parents(self):
        """Link every period to its parent; called on module update so that
        periods created before the hierarchy existed are nested too."""
        self.with_context(active_test=False).sudo().search([])._sync_parent()

    @api.constrains('period_type', 'year', 'quarter', 'month')
    def _check_definition(self):
        for period in self:
            if not MIN_YEAR <= period.year <= MAX_YEAR:
                raise ValidationError(_(
                    'The year of a KPI period must be between %(min)s and %(max)s.',
                    min=MIN_YEAR, max=MAX_YEAR,
                ))
            if period.period_type == 'quarter' and not period.quarter:
                raise ValidationError(_('Select the quarter of the KPI period.'))
            if period.period_type == 'month' and not period.month:
                raise ValidationError(_('Select the month of the KPI period.'))

    @api.model
    def _selection_years(self):
        """Years offered in period dropdowns: a window around the current
        year, widened to every year that already has a KPI period."""
        today_year = fields.Date.context_today(self).year
        years = set(range(today_year - 5, today_year + 3))
        groups = self.sudo()._read_group([], ['year'])
        years.update(year for (year,) in groups if year)
        return [(str(year), str(year)) for year in sorted(years, reverse=True)]

    @api.model
    def _definition_from_selection(self, period_type, year, quarter, month):
        """Return ``(period_type, year, quarter, month)`` for ``_find`` from
        dropdown values, or ``None`` when the selection is incomplete."""
        if not period_type or not year:
            return None
        if period_type == 'quarter' and not quarter:
            return None
        if period_type == 'month' and not month:
            return None
        return (
            period_type,
            int(year),
            quarter if period_type == 'quarter' else False,
            month if period_type == 'month' else False,
        )

    @api.model
    def _find(self, period_type, year, quarter=False, month=False, company=None):
        """Return the period matching the definition, preferring one of
        ``company`` over a shared one (no company)."""
        company = company or self.env.company
        periods = self.search([
            ('period_type', '=', period_type),
            ('year', '=', year),
            ('quarter', '=', quarter if period_type == 'quarter' else False),
            ('month', '=', month if period_type == 'month' else False),
            ('company_id', 'in', [company.id, False]),
        ])
        return periods.filtered('company_id')[:1] or periods[:1]

    @api.model
    def _find_or_create(self, period_type, year, quarter=False, month=False, company=None):
        company = company or self.env.company
        period = self._find(period_type, year, quarter, month, company)
        if not period:
            period = self.create({
                'period_type': period_type,
                'year': year,
                'quarter': quarter,
                'month': month,
                'company_id': company.id,
            })
        return period

    def action_close(self):
        self.write({'state': 'closed'})

    def action_reopen(self):
        self.write({'state': 'open'})

    def action_accrue_bonuses(self):
        """Auto-accrue hr.bonus records for every confirmed/closed scorecard
        in the period across the active companies. Each employee is accrued
        what their bonus model allows at the scorecard's current state.
        """
        Scorecard = self.env['hr.scorecard']
        for period in self:
            scorecards = Scorecard.search([
                ('period_id', '=', period.id),
                ('state', 'in', ('confirmed', 'closed')),
                ('company_id', 'in', self.env.companies.ids),
            ])
            for sc in scorecards:
                sc._accrue_bonus()
        return True

    def months_in_period(self):
        """Return list of (year, month) tuples covered by the period."""
        self.ensure_one()
        months = []
        cursor = self.date_from.replace(day=1)
        end = self.date_to
        while cursor <= end:
            months.append((cursor.year, cursor.month))
            cursor = cursor + relativedelta(months=1)
        return months
