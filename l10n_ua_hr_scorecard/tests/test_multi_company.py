"""Multi-company consistency of the KPI scorecard models."""

from odoo.exceptions import UserError
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestScorecardMultiCompany(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company_a = cls.env.company
        cls.company_b = cls.env['res.company'].create({'name': 'KPI Company B'})
        cls.job_b = cls.env['hr.job'].create({'name': 'Job B', 'company_id': cls.company_b.id})
        cls.job_shared = cls.env['hr.job'].create({'name': 'Shared Job', 'company_id': False})
        cls.kpi_a = cls.env['hr.kpi'].create({'name': 'KPI A', 'company_id': cls.company_a.id})
        cls.kpi_b = cls.env['hr.kpi'].create({'name': 'KPI B', 'company_id': cls.company_b.id})
        cls.period_a = cls.env['hr.kpi.period']._find_or_create(
            'quarter', 2026, quarter='1', company=cls.company_a,
        )
        cls.employee_b = cls.env['hr.employee'].create({
            'name': 'Employee B', 'company_id': cls.company_b.id,
        })
        cls.bonus_type = cls.env['hr.bonus.type'].create({
            'name': 'KPI Bonus A', 'code': 'KPI_MC_A', 'company_id': cls.company_a.id,
        })

    def test_company_fields_limited_to_selected_companies(self):
        env = self.env(context={'allowed_company_ids': [self.company_a.id]})
        for model in ('hr.kpi', 'hr.kpi.period', 'hr.kpi.target', 'hr.scorecard',
                      'hr.scorecard.employee.config', 'hr.kpi.assign.wizard',
                      'hr.kpi.assignment'):
            domain = env[model]._fields['company_id']._description_domain(env)
            self.assertEqual(domain, [('id', 'in', [self.company_a.id])], model)

    def test_target_rejects_kpi_of_other_company(self):
        with self.assertRaises(UserError):
            self.env['hr.kpi.target'].create({
                'kpi_id': self.kpi_b.id,
                'period_id': self.period_a.id,
                'company_id': self.company_a.id,
            })

    def test_assignment_rejects_job_or_kpi_of_other_company(self):
        Assignment = self.env['hr.kpi.assignment']
        with self.assertRaises(UserError):
            Assignment.create({'job_id': self.job_b.id, 'company_id': self.company_a.id})
        with self.assertRaises(UserError):
            Assignment.create({
                'job_id': self.job_shared.id,
                'company_id': self.company_a.id,
                'line_ids': [(0, 0, {'kpi_id': self.kpi_b.id, 'weight': 10})],
            })

    def test_scorecard_rejects_job_of_other_company(self):
        with self.assertRaises(UserError):
            self.env['hr.scorecard'].create({
                'job_id': self.job_b.id,
                'period_id': self.period_a.id,
                'company_id': self.company_a.id,
            })

    def test_scorecard_line_rejects_kpi_of_other_company(self):
        scorecard = self.env['hr.scorecard'].create({
            'job_id': self.job_shared.id,
            'period_id': self.period_a.id,
            'company_id': self.company_a.id,
        })
        with self.assertRaises(UserError):
            self.env['hr.scorecard.line'].create({
                'scorecard_id': scorecard.id,
                'kpi_id': self.kpi_b.id,
            })

    def test_employee_config_rejects_employee_of_other_company(self):
        with self.assertRaises(UserError):
            self.env['hr.scorecard.employee.config'].create({
                'employee_id': self.employee_b.id,
                'company_id': self.company_a.id,
                'bonus_type_id': self.bonus_type.id,
            })
