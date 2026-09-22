"""KPI assignment: the KPIs of a job position and their weights, from a date on."""

from datetime import date

from psycopg2 import IntegrityError

from odoo.exceptions import ValidationError
from odoo.tests import TransactionCase, tagged
from odoo.tools import mute_logger


@tagged('post_install', '-at_install')
class TestKpiAssignment(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.job = cls.env['hr.job'].create({'name': 'Assignment Job', 'company_id': cls.company.id})
        cls.other_job = cls.env['hr.job'].create({'name': 'Other Assignment Job', 'company_id': cls.company.id})
        cls.kpis = cls.env['hr.kpi'].create([
            {'name': f'Assignment KPI {index}', 'company_id': cls.company.id} for index in range(3)
        ])
        cls.Assignment = cls.env['hr.kpi.assignment']

    def _assign(self, weights, job=None, date_from=date(2026, 1, 1)):
        return self.Assignment.create({
            'job_id': (job or self.job).id,
            'company_id': self.company.id,
            'date_from': date_from,
            'line_ids': [
                (0, 0, {'kpi_id': kpi.id, 'weight': weight})
                for kpi, weight in zip(self.kpis, weights)
            ],
        })

    def test_weights_up_to_100_are_accepted(self):
        assignment = self._assign([60.0, 30.0, 10.0])
        self.assertEqual(assignment.total_weight, 100.0)
        self.assertEqual(assignment.kpi_count, 3)

    def test_total_above_100_is_rejected(self):
        with self.assertRaises(ValidationError):
            self._assign([60.0, 30.0, 10.01])
        assignment = self._assign([60.0, 40.0])
        with self.assertRaises(ValidationError):
            assignment.line_ids[1].weight = 41.0
        with self.assertRaises(ValidationError):
            assignment.write({'line_ids': [(0, 0, {'kpi_id': self.kpis[2].id, 'weight': 1.0})]})

    def test_rebalancing_in_one_save(self):
        assignment = self._assign([60.0, 40.0])
        first, second = assignment.line_ids
        assignment.write({'line_ids': [(1, second.id, {'weight': 60.0}), (1, first.id, {'weight': 40.0})]})
        self.assertEqual((first.weight, second.weight), (40.0, 60.0))

    def test_weight_out_of_range_is_rejected(self):
        with self.assertRaises(ValidationError):
            self._assign([-1.0])

    def test_kpi_once_per_assignment(self):
        assignment = self._assign([10.0])
        with self.assertRaises(IntegrityError), mute_logger('odoo.sql_db'):
            assignment.write({'line_ids': [(0, 0, {'kpi_id': self.kpis[0].id, 'weight': 5.0})]})
            self.env.flush_all()

    def test_one_assignment_per_job_and_date(self):
        self._assign([10.0])
        with self.assertRaises(IntegrityError), mute_logger('odoo.sql_db'):
            self._assign([20.0])
            self.env.flush_all()

    def test_assignment_in_force(self):
        first = self._assign([100.0], date_from=date(2025, 1, 1))
        second = self._assign([50.0, 50.0], date_from=date(2026, 1, 1))
        self.assertEqual(first.date_to, date(2025, 12, 31))
        self.assertFalse(second.date_to)
        get = self.Assignment._get_in_force
        self.assertEqual(get(self.job, self.company, date(2025, 6, 1)), first)
        self.assertEqual(get(self.job, self.company, date(2026, 1, 1)), second)
        self.assertFalse(get(self.job, self.company, date(2024, 12, 31)))
        self.assertFalse(get(self.other_job, self.company, date(2026, 6, 1)))

    def test_smart_buttons(self):
        period = self.env['hr.kpi.period']._find_or_create('quarter', 2026, quarter='2', company=self.company)
        old_period = self.env['hr.kpi.period']._find_or_create('quarter', 2025, quarter='4', company=self.company)
        Target = self.env['hr.kpi.target']
        target = Target.create({'kpi_id': self.kpis[0].id, 'period_id': period.id, 'company_id': self.company.id})
        # Before the assignment is in force
        Target.create({'kpi_id': self.kpis[0].id, 'period_id': old_period.id, 'company_id': self.company.id})
        # A KPI that is not assigned
        Target.create({'kpi_id': self.kpis[2].id, 'period_id': period.id, 'company_id': self.company.id})
        assignment = self._assign([60.0, 40.0])
        self.assertEqual(assignment.target_count, 1)
        action = assignment.action_open_targets()
        self.assertEqual(Target.search(action['domain']), target)
        action = assignment.action_open_kpis()
        self.assertEqual(self.env['hr.kpi'].search(action['domain']), self.kpis[:2])
        # The next assignment ends the validity of this one
        self._assign([100.0], date_from=date(2026, 4, 1))
        assignment.invalidate_recordset(['date_to', 'target_count'])
        self.assertEqual(assignment.target_count, 0)

    def test_employees_smart_button(self):
        employee = self.env['hr.employee'].create({
            'name': 'Assignment Employee', 'company_id': self.company.id, 'job_id': self.job.id,
        })
        employee.version_ids[:1].write({'contract_date_start': date(2025, 3, 1)})
        other = self.env['hr.employee'].create({
            'name': 'Other Assignment Employee', 'company_id': self.company.id, 'job_id': self.other_job.id,
        })
        other.version_ids[:1].write({'contract_date_start': date(2025, 3, 1)})
        assignment = self._assign([100.0])
        self.assertEqual(assignment.employee_count, 1)
        employees = self.env['hr.employee'].with_context(active_test=False).search(
            assignment.action_open_employees()['domain'])
        self.assertEqual(employees, employee)
