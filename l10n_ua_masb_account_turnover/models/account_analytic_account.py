"""Person accountable for a subdivision.

The paper statement heads every subdivision block with the name of the person
materially accountable for it ("Shop ABV, Sahaydak M.V."). Odoo has nowhere to
put that, so the analytic account - which is what represents a subdivision here -
gets the field.

It is deliberately not the ``partner_id`` that already exists on the analytic
account: that one is the customer of a project and shows up in the display name
of the account all over the accounting screens.
"""
from odoo import fields, models


class AccountAnalyticAccount(models.Model):
    _inherit = 'account.analytic.account'

    masb_responsible_id = fields.Many2one(
        'hr.employee',
        string='Accountable Person',
        help='Materially accountable person of the subdivision, printed in the '
             'production cost statement.',
    )
