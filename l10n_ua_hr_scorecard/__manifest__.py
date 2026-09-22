{
    'name': 'Ukraine - HR KPI Scorecard',
    'version': '19.0.1.1.0',
    'category': 'Human Resources/Localization',
    'summary': 'KPI directory and balanced scorecards with bonus calculation',
    'description': """
Ukraine - HR KPI Scorecard
==========================

KPI management and balanced scorecards for Ukrainian HR operations.

Features
--------

* KPI directory with planned targets, a data source for actual values (manual
  input or Odoo data: any line of the P&L statement, Form No. 2) and two
  calculation methods:

  - Binary completion: 100% if achieved, 0% otherwise
  - Fulfillment coefficient: (actual / planned) x 100%, may exceed
    or fall below 100%

* KPI periods (monthly, quarterly or annual) defined by type, year and
  quarter/month only; name and dates are derived, no free-form periods
* KPI assignment per job position from a date on: KPIs and weights (at most
  100% in total)
* Balanced scorecards per job position where weighted KPIs total 100%;
  the employees of a scorecard are derived from the employee version
  history (everyone who held the position during the period)
* Auto-calculation of weighted result:
  KPI1 x weight1 + KPI2 x weight2 + ...
* Per-employee bonus proportional to the weighted result and to the days
  spent in the job position during the period, with two models:

  - Period-based: bonus paid after the period closes
  - Monthly advance with reconciliation: regular advances during
    the period, reconciled at period close

* Per-employee compensation split (e.g. salary 80% / bonus 20%) stored
  as an independent directory (`hr.scorecard.employee.config`); existing
  HR/payroll modules are not modified
* Automatic bonus accrual into `hr.bonus` (from
  `l10n_ua_hr_salary_bonus`) on demand from the scorecard or period
* Period-level KPI targets (`hr.kpi.target`) with confirm/draft lifecycle:
  planned and actual values are shared across every job position scorecard
  that uses the KPI in that period, and become read-only after confirmation
* "KPI Targets" master-detail UI for maintaining values by period
* "KPI Map" report: employees with the KPIs of their job positions for a period,
  weights, achievement and weighted result
* KPI targets pick their period as type + year + quarter/month, both when
  created (dialog) and edited; a missing period is generated on save
    """,
    'author': 'NDEV',
    'website': 'https://ndev.online',
    'license': 'LGPL-3',
    'depends': [
        'l10n_ua_hr_base',
        'l10n_ua_hr_salary_bonus',
        'l10n_ua_accounting',
    ],
    'data': [
        'security/hr_scorecard_security.xml',
        'security/ir.model.access.csv',
        'data/ir_sequence_data.xml',
        'data/hr_kpi_period_data.xml',
        'views/hr_kpi_views.xml',
        'views/hr_kpi_period_views.xml',
        'views/hr_kpi_target_copy_wizard_views.xml',
        'views/hr_kpi_target_views.xml',
        'views/hr_kpi_map_views.xml',
        'views/hr_kpi_assignment_views.xml',
        'views/hr_kpi_assign_wizard_views.xml',
        'views/hr_scorecard_employee_config_views.xml',
        'views/hr_scorecard_views.xml',
        'views/menu_views.xml',
    ],    
    'assets': {
        'web.assets_backend': [
            'l10n_ua_hr_scorecard/static/src/**/*',
        ],
    },
    'demo': [
        'demo/hr_scorecard_demo.xml',
    ],
    'installable': True,
    'application': False,
    'auto_install': False,
}
