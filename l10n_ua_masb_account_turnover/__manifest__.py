{
    'name': 'Ukraine - MASB - Journal-Orders and Ledgers by Account',
    'version': '19.0.1.0.0',
    'category': 'Accounting/Localizations/Reporting',
    'summary': 'Turnover of an account by analytic dimension and corresponding '
               'account: production (23), suppliers (631) and more',
    'description': """
Ukraine - MASB - Journal-Orders and Ledgers by Account
======================================================

The register Ukrainian accountants know from 1C as "Journal-order and ledger by
account", laid out the way the journals
and ledgers approved by Ministry of Finance order No. 356 of 29.12.2000 expect
it:

* opening balance;
* debit turnover split by corresponding credit account;
* credit turnover split by corresponding debit account;
* closing balance,

per value of an analytic dimension of the account.

Statement types
---------------

What a statement covers is a record of ``masb.account.turnover.type``, not code:

* the accounts (code prefixes);
* the rows - an analytic plan, or a subconto of ``l10n_ua_account_base``
  (partner, department, ...) falling back to the matching field of the journal
  item when no subconto was entered;
* the blank - its columns, balances in one signed column or on the debit and
  the credit side, cost element rows, empty rows skipped or kept.

Two types come with the module:

* account 23 - rows are subdivisions (analytic plan) broken down by cost
  element, the layout of Journal 5 section III expanded by subdivision;
* account 631 - rows are suppliers (subconto "Partners", falling back to the
  partner of the journal item reduced to its commercial entity), balances on
  both sides.

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
        'security/masb_account_turnover_security.xml',
        'data/masb_account_turnover_type_data.xml',
        'data/masb_account_turnover_column_data.xml',
        'views/account_analytic_account_views.xml',
        'views/masb_account_turnover_type_views.xml',
        'views/masb_account_turnover_cell_views.xml',
        'views/masb_account_turnover_views.xml',
        'views/menu_views.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'l10n_ua_masb_account_turnover/static/src/account_turnover_matrix/matrix.js',
            'l10n_ua_masb_account_turnover/static/src/account_turnover_matrix/matrix.xml',
            'l10n_ua_masb_account_turnover/static/src/account_turnover_matrix/matrix.scss',
        ],
    },
    'installable': True,
    'application': False,
    'auto_install': False,
}
