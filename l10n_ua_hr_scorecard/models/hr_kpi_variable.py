import string

from odoo import models, fields, api, _
from odoo.exceptions import ValidationError

from .hr_kpi import SYSTEM_PARAMETER_MODELS, SYSTEM_PARAMETERS
from .kpi_formula import VARIABLE_CODE_RE


class HrKpiVariable(models.Model):
    """A variable of the formula of a KPI: an Odoo parameter read from a
    report of the period of the target. Constants are written in the formula."""
    _name = 'hr.kpi.variable'
    _description = 'KPI Formula Variable'
    _order = 'kpi_id, sequence, id'

    kpi_id = fields.Many2one('hr.kpi', string='KPI', required=True, ondelete='cascade', index=True)
    sequence = fields.Integer(default=10)
    code = fields.Char(
        string='Code',
        required=True,
        default=lambda self: self._default_code(),
        help='Name of the variable in the formula: a letter followed by letters, digits or '
             'underscores, e.g. A, B or Revenue.',
    )
    name = fields.Char(string='Description', translate=True)
    system_field = fields.Selection(SYSTEM_PARAMETERS, string='Odoo Parameter', required=True)
    source_model = fields.Char(
        string='Source Report Model',
        compute='_compute_source_model',
        help='Technical name of the model of the reports the Odoo parameter is read from.',
    )

    _kpi_code_uniq = models.Constraint(
        'unique(kpi_id, code)',
        'Each variable of a KPI formula must have its own code.',
    )

    @api.model
    def _default_code(self):
        """The first letter not used yet by the variables of the KPI."""
        used = set()
        kpi_id = self.env.context.get('default_kpi_id')
        if kpi_id:
            used = set(self.search([('kpi_id', '=', kpi_id)]).mapped('code'))
        return next((letter for letter in string.ascii_uppercase if letter not in used), False)

    @api.depends('system_field')
    def _compute_source_model(self):
        for variable in self:
            variable.source_model = SYSTEM_PARAMETER_MODELS.get(variable.system_field) or False

    @api.constrains('code', 'system_field', 'kpi_id')
    def _check_variable(self):
        for variable in self:
            if not VARIABLE_CODE_RE.match(variable.code or ''):
                raise ValidationError(_(
                    'The code %s of a KPI formula variable must start with a letter and contain '
                    'only letters, digits and underscores.', variable.code,
                ))
            if not variable.system_field:
                raise ValidationError(_(
                    'Select the Odoo parameter of the variable %s.', variable.code,
                ))
