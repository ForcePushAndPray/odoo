{
    'name': 'Ukraine - HR KPI Scorecard',
    'version': '19.0.1.0.0',
    'category': 'Human Resources/Localization',
    'summary': 'KPI directory and balanced scorecards with bonus calculation',
    'description': """
Ukraine - HR KPI Scorecard
==========================

KPI management and balanced scorecards for Ukrainian HR operations.

Features
--------

* KPI directory with planned targets and two calculation methods:

  - Binary completion: 100% if achieved, 0% otherwise
  - Fulfillment coefficient: (actual / planned) x 100%, may exceed
    or fall below 100%

* KPI periods (quarterly or annual) with historical tracking
* Balanced scorecards per employee where weighted KPIs total 100%
* Auto-calculation of weighted result:
  KPI1 x weight1 + KPI2 x weight2 + ...
* Bonus calculation proportional to weighted result with two models:

  - Period-based: bonus paid after the period closes
  - Monthly advance with reconciliation: regular advances during
    the period, reconciled at period close

* Per-employee compensation split (e.g. salary 80% / bonus 20%) stored
  as an independent directory (`hr.scorecard.employee.config`); existing
  HR/payroll modules are not modified
* Automatic bonus accrual into `hr.bonus` (from
  `l10n_ua_hr_salary_bonus`) on demand from the scorecard or period
* Period-level KPI targets (`hr.kpi.target`) with confirm/draft lifecycle:
  planned and actual values are shared across every employee scorecard
  that uses the KPI in that period, and become read-only after confirmation
* "KPI Targets" master-detail UI for maintaining values by period
* Optional link between a KPI and one or more staffing positions (`hr.job`)
* Additional "KPI Scorecard" form view focused on per-employee weights
    """,
    'author': 'NDEV',
    'website': 'https://ndev.online',
    'license': 'LGPL-3',
    'depends': [
        'l10n_ua_hr_base',
        'l10n_ua_hr_salary_bonus',
    ],
    'data': [
        'security/hr_scorecard_security.xml',
        'security/ir.model.access.csv',
        'data/ir_sequence_data.xml',
        'views/hr_kpi_views.xml',
        'views/hr_kpi_period_views.xml',
        'views/hr_kpi_target_views.xml',
        'views/hr_kpi_assign_wizard_views.xml',
        'views/hr_scorecard_employee_config_views.xml',
        'views/hr_scorecard_views.xml',
        'views/hr_scorecard_kpi_layout_views.xml',
        'views/menu_views.xml',
    ],
    'demo': [
        'demo/hr_scorecard_demo.xml',
    ],
    'installable': True,
    'application': False,
    'auto_install': False,
}
