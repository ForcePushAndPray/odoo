{
    'name': 'Ukraine - MASB - HR Documents',
    'version': '19.0.1.0.1',
    'category': 'Human Resources/Localization',
    'summary': 'MASB - Ukrainian HR document templates and orders',
    'description': """
Ukraine HR Documents Module
===========================

HR document management for Ukrainian localization:

* HR orders (Накази) - hiring, transfer, termination, vacation, bonus, etc.
* HR order templates with placeholders
* Document numbering sequences
* Employee personal file management
* Document templates with Ukrainian formatting
* Order printing (Накази)
* Personal card (Особова картка П-2)
* Employment history book entries

Requires l10n_ua_hr_base module.
    """,
    'author': 'Vlad Patenko',
    'license': 'LGPL-3',
    'depends': [
        'l10n_ua_hr_base',
        'l10n_ua_hr_contract',
        'mail',
    ],
    'data': [
        'data/hr_order_template_data.xml',
    ],
    'demo': [
    ],
    'images': ['static/description/banner.png'],
    'installable': True,
    'application': False,
    'auto_install': False,
    'price': 0,
    'currency': 'EUR',
}
