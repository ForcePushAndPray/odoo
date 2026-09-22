from odoo import models, fields, api, _
from odoo.exceptions import UserError

from .hr_kpi_period import MONTHS, PERIOD_TYPES, QUARTERS


class HrKpiTargetCopyWizard(models.TransientModel):
    """Copy KPI targets to another period, picked as on a KPI target: type,
    year and quarter or month. The period is generated when it does not exist."""
    _name = 'hr.kpi.target.copy.wizard'
    _description = 'Copy KPI Targets to Another Period'

    target_ids = fields.Many2many('hr.kpi.target', string='KPI Targets', required=True)
    period_type = fields.Selection(PERIOD_TYPES, string='Period Type', required=True)
    period_year = fields.Selection('_selection_years', string='Year', required=True)
    period_quarter = fields.Selection(QUARTERS, string='Quarter')
    period_month = fields.Selection(MONTHS, string='Month')
    period_missing = fields.Boolean(
        string='Period Missing', compute='_compute_period_missing',
        help='The selected period does not exist yet and will be generated.',
    )
    copy_planned_value = fields.Boolean(string='Copy Planned Value', default=True)

    @api.model
    def _selection_years(self):
        return self.env['hr.kpi.period']._selection_years()

    @api.model
    def default_get(self, fields_list):
        vals = super().default_get(fields_list)
        targets = self.env['hr.kpi.target']
        if self.env.context.get('active_model') == 'hr.kpi.target':
            targets = targets.browse(self.env.context.get('active_ids') or [])
            vals['target_ids'] = [(6, 0, targets.ids)]
        # Suggest the period right after the one of the first target
        source = targets[:1].period_id
        if source:
            vals.update(self._next_period_selection(source))
        else:
            vals.update({'period_type': 'quarter',
                         'period_year': str(fields.Date.context_today(self).year)})
        return vals

    @api.model
    def _next_period_selection(self, period):
        year = period.year
        if period.period_type == 'quarter':
            quarter = int(period.quarter) % 4 + 1
            year += quarter == 1
            return {'period_type': 'quarter', 'period_year': str(year), 'period_quarter': str(quarter)}
        if period.period_type == 'month':
            month = int(period.month) % 12 + 1
            year += month == 1
            return {'period_type': 'month', 'period_year': str(year), 'period_month': str(month)}
        return {'period_type': 'year', 'period_year': str(year + 1)}

    def _period_definition(self):
        self.ensure_one()
        return self.env['hr.kpi.period']._definition_from_selection(
            self.period_type, self.period_year, self.period_quarter, self.period_month,
        )

    @api.depends('period_type', 'period_year', 'period_quarter', 'period_month', 'target_ids')
    def _compute_period_missing(self):
        Period = self.env['hr.kpi.period']
        for wizard in self:
            definition = wizard._period_definition()
            companies = wizard.target_ids.company_id or self.env.company
            wizard.period_missing = bool(definition) and any(
                not Period._find(*definition, company=company) for company in companies
            )

    def action_copy(self):
        self.ensure_one()
        definition = self._period_definition()
        if not definition:
            raise UserError(_('Select the period type, year and quarter or month first.'))
        Period = self.env['hr.kpi.period']
        Target = self.env['hr.kpi.target']
        created = Target
        skipped = []
        for target in self.target_ids:
            period = Period._find_or_create(*definition, company=target.company_id)
            overlapping = Target.search([
                ('kpi_id', '=', target.kpi_id.id),
                ('company_id', '=', target.company_id.id),
                ('period_id.date_from', '<=', period.date_to),
                ('period_id.date_to', '>=', period.date_from),
            ], limit=1)
            if overlapping:
                skipped.append(_(
                    '%(kpi)s: %(period)s (a target for %(existing)s already exists)',
                    kpi=target.kpi_id.name,
                    period=period.display_name,
                    existing=overlapping.period_id.display_name,
                ))
                continue
            created |= Target.create({
                'kpi_id': target.kpi_id.id,
                'period_id': period.id,
                'company_id': target.company_id.id,
                'planned_value': target.planned_value if self.copy_planned_value else 0.0,
            })
        if not created:
            raise UserError(_('No KPI target was copied:\n%s', '\n'.join(skipped)))
        if len(created) == 1 and not skipped:
            action = {
                'type': 'ir.actions.act_window',
                'name': _('Copied KPI Target'),
                'res_model': 'hr.kpi.target',
                'res_id': created.id,
                'view_mode': 'form',
                'views': [(False, 'form')],
            }
        else:
            action = {
                'type': 'ir.actions.act_window',
                'name': _('Copied KPI Targets'),
                'res_model': 'hr.kpi.target',
                'view_mode': 'list,form',
                'views': [(False, 'list'), (False, 'form')],
                'domain': [('id', 'in', created.ids)],
            }
        if not skipped:
            return action
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('%s KPI targets copied', len(created)),
                'message': _('Skipped:\n%s', '\n'.join(skipped)),
                'type': 'warning',
                'sticky': True,
                'next': action,
            },
        }
