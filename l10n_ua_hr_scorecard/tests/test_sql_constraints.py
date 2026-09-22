"""SQL uniqueness constraints of the KPI scorecard models."""

from psycopg2 import IntegrityError

from odoo.tests import TransactionCase, tagged
from odoo.tools import mute_logger


@tagged('post_install', '-at_install')
class TestScorecardSqlConstraints(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.other_company = cls.env['res.company'].create({'name': 'KPI Other Company'})
        cls.employee = cls.env['hr.employee'].create({
            'name': 'KPI Employee',
            'company_id': cls.company.id,
        })
        cls.job = cls.env['hr.job'].create({
            'name': 'KPI Job Position',
            'company_id': cls.company.id,
        })
        cls.kpi = cls.env['hr.kpi'].create({
            'name': 'Constraint KPI',
            'company_id': cls.company.id,
        })
        cls.period = cls.env['hr.kpi.period']._find_or_create(
            'quarter', 2026, quarter='1', company=cls.company,
        )
        cls.bonus_type = cls.env['hr.bonus.type'].search([], limit=1) or \
            cls.env['hr.bonus.type'].create({'name': 'KPI Bonus', 'code': 'KPI_TEST'})

    def assertDuplicateRejected(self, model, vals):
        with self.assertRaises(IntegrityError), mute_logger('odoo.sql_db'):
            self.env[model].create(vals)
            self.env.flush_all()

    def test_kpi_target_unique_per_kpi_period_company(self):
        vals = {
            'kpi_id': self.kpi.id,
            'period_id': self.period.id,
            'company_id': self.company.id,
        }
        self.env['hr.kpi.target'].create(vals)
        self.env.flush_all()
        self.assertDuplicateRejected('hr.kpi.target', vals)

    def test_scorecard_unique_per_job_period_company(self):
        vals = {
            'job_id': self.job.id,
            'period_id': self.period.id,
            'company_id': self.company.id,
        }
        self.env['hr.scorecard'].create(vals)
        self.env.flush_all()
        self.assertDuplicateRejected('hr.scorecard', vals)

    def test_employee_config_unique_per_employee_company(self):
        vals = {
            'employee_id': self.employee.id,
            'company_id': self.company.id,
            'bonus_type_id': self.bonus_type.id,
        }
        self.env['hr.scorecard.employee.config'].create(vals)
        self.env.flush_all()
        self.assertDuplicateRejected('hr.scorecard.employee.config', vals)
