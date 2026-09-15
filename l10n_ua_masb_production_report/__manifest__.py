{
    'name': 'Ukraine - MASB - Production Cost Statement (account 23)',
    'version': '19.0.1.4.1',
    'category': 'Accounting/Localizations/Reporting',
    'summary': 'Analytic statement of account 23 by subdivision, cost element '
               'and corresponding account',
    'description': """
Ukraine - MASB - Production Cost Statement
==========================================

Matrix statement of production costs collected on account 23, laid out the way
Ukrainian production accountants expect it (the layout of Journal 5 section III
from the registers approved by Ministry of Finance order No. 356 of 29.12.2000,
expanded by subdivision).

Rows
----

Three nested levels:

* production sub-account (231, 233, 235, 236, ...);
* subdivision - an analytic account of the configured root plan, taken from the
  analytic distribution of the journal item;
* cost element - materials, other direct costs, prior period costs, production
  overheads - derived from the corresponding account.

Columns
-------

Configurable (``masb.production.column``), split into two blocks:

* debit block - corresponding credit accounts (13, 20x, 22, 39, 471, 65, 66,
  63/68, 91);
* credit block - corresponding debit accounts (26, 901, 39, ...).

Opening balance, debit turnover total, credit turnover total and closing
balance are computed per row.

The statement is drawn on the form by a dedicated widget and exported to XLSX
from the same structure, so the screen and the file cannot disagree. The stored
cells are also open in the standard pivot view for questions the fixed blank
does not answer.

Correspondence
--------------

Odoo does not store debit/credit pairs, so correspondence is restored: within a
journal entry the amount of each line is split over the lines of the opposite
side in proportion to their amounts. The same rule is used by
``l10n_ua.account.analysis`` and ``l10n_ua.correspondence`` in the Ukrainian
localization; see ``_iter_correspondence`` for details.
    """,
    'author': 'NDEV',
    'website': 'https://ndev.online',
    'license': 'LGPL-3',
    'depends': [
        'l10n_ua_account_base',
        'l10n_ua_accounting',
        'analytic',
        'hr',
    ],
    'data': [
        'security/ir.model.access.csv',
        'data/masb_production_column_data.xml',
        'views/account_analytic_account_views.xml',
        'views/masb_production_column_views.xml',
        'views/masb_production_report_cell_views.xml',
        'views/masb_production_report_views.xml',
        'views/menu_views.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'l10n_ua_masb_production_report/static/src/production_matrix/matrix.js',
            'l10n_ua_masb_production_report/static/src/production_matrix/matrix.xml',
            'l10n_ua_masb_production_report/static/src/production_matrix/matrix.scss',
        ],
    },
    'installable': True,
    'application': False,
    'auto_install': False,
}
