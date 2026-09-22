"""Job position scorecards: employees derived from version history, prorated bonuses."""

from datetime import date

from odoo import fields
from odoo.exceptions import AccessError, UserError
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestJobScorecard(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.job_a = cls.env['hr.job'].create({'name': 'Sales Manager', 'company_id': cls.company.id})
        cls.job_b = cls.env['hr.job'].create({'name': 'Sales Director', 'company_id': cls.company.id})
        # Q1 2026: 90 days
        cls.period = cls.env['hr.kpi.period']._find_or_create(
            'quarter', 2026, quarter='1', company=cls.company,
        )
        cls.kpi = cls.env['hr.kpi'].create({
            'name': 'Revenue (test)',
            'calculation_method': 'coefficient',
            'company_id': cls.company.id,
        })
        cls.bonus_type = cls.env['hr.bonus.type'].search([], limit=1) or \
            cls.env['hr.bonus.type'].create({'name': 'KPI Bonus', 'code': 'KPI_TEST'})

        # Held job A for the whole period
        cls.emp_full = cls._create_employee('Full Period', cls.job_a, date(2025, 1, 1))
        # Transferred from job A to job B on 2026-02-15
        cls.emp_transfer = cls._create_employee('Transferred', cls.job_a, date(2025, 1, 1))
        cls.env['hr.version'].create({
            'employee_id': cls.emp_transfer.id,
            'company_id': cls.company.id,
            'date_version': date(2026, 2, 15),
            'contract_date_start': date(2025, 1, 1),
            'job_id': cls.job_b.id,
        })
        # Hired on 2026-03-02
        cls.emp_hired = cls._create_employee('Hired', cls.job_a, date(2026, 3, 2))
        # Contract ended on 2026-01-31
        cls.emp_left = cls._create_employee('Left', cls.job_a, date(2025, 1, 1), date(2026, 1, 31))
        # Left before the period
        cls.emp_gone = cls._create_employee('Gone', cls.job_a, date(2024, 1, 1), date(2025, 12, 31))
        # Hired after the period
        cls.emp_future = cls._create_employee('Future', cls.job_a, date(2026, 4, 1))
        # Other job position
        cls.emp_other = cls._create_employee('Other Job', cls.job_b, date(2025, 1, 1))

        Config = cls.env['hr.scorecard.employee.config']
        for employee, model in (
            (cls.emp_full, 'period'),
            (cls.emp_transfer, 'period'),
            (cls.emp_hired, 'monthly_advance'),
        ):
            Config.create({
                'employee_id': employee.id,
                'company_id': cls.company.id,
                'salary_pct': 80.0,
                'bonus_pct': 20.0,
                'bonus_base': 9000.0,
                'bonus_model': model,
                'bonus_type_id': cls.bonus_type.id,
            })

        cls.scorecard = cls.env['hr.scorecard'].create({
            'job_id': cls.job_a.id,
            'period_id': cls.period.id,
            'company_id': cls.company.id,
            'line_ids': [(0, 0, {'kpi_id': cls.kpi.id, 'weight': 100.0})],
        })
        cls.scorecard.line_ids.target_id.write({'planned_value': 100.0, 'actual_value': 120.0})

    @classmethod
    def _create_employee(cls, name, job, contract_start, contract_end=False):
        employee = cls.env['hr.employee'].create({
            'name': name,
            'company_id': cls.company.id,
            'job_id': job.id,
            'bonus_system_enabled': True,
        })
        # A single version takes the contract start as its date_version.
        employee.version_ids[:1].write({
            'contract_date_start': contract_start,
            'contract_date_end': contract_end,
        })
        return employee

    def _days(self, scorecard=None):
        scorecard = scorecard or self.scorecard
        period = scorecard.period_id
        return {
            employee_id: scorecard._days_in_range(intervals, period.date_from, period.date_to)
            for employee_id, intervals in scorecard._get_employee_intervals().items()
        }

    def test_employees_derived_from_version_history(self):
        self.assertEqual(self._days(), {
            self.emp_full.id: 90,
            self.emp_transfer.id: 45,   # 2026-01-01 .. 2026-02-14
            self.emp_hired.id: 30,      # 2026-03-02 .. 2026-03-31
            self.emp_left.id: 31,       # 2026-01-01 .. 2026-01-31
        })
        self.assertEqual(self.scorecard.employee_count, 4)

    def test_transferred_employee_counted_on_new_position(self):
        scorecard_b = self.env['hr.scorecard'].create({
            'job_id': self.job_b.id,
            'period_id': self.period.id,
            'company_id': self.company.id,
        })
        self.assertEqual(self._days(scorecard_b), {
            self.emp_transfer.id: 45,   # 2026-02-15 .. 2026-03-31
            self.emp_other.id: 90,
        })

    def test_departure_date_ends_open_contract(self):
        self.emp_full.version_ids[:1].departure_date = date(2026, 2, 28)
        self.assertEqual(self._days()[self.emp_full.id], 59)

    def test_archived_employee_without_end_date_is_dropped(self):
        self.emp_full.with_context(no_wizard=True).action_archive()
        self.assertNotIn(self.emp_full.id, self._days())

    def test_employee_results_prorate_bonus(self):
        self.assertAlmostEqual(self.scorecard.weighted_result, 120.0)
        results = {r['employee']: r for r in self.scorecard._get_employee_results()}
        self.assertAlmostEqual(results[self.emp_full]['bonus_amount'], 10800.0)
        self.assertAlmostEqual(results[self.emp_transfer]['bonus_base'], 4500.0)
        self.assertAlmostEqual(results[self.emp_transfer]['bonus_amount'], 5400.0)
        self.assertAlmostEqual(results[self.emp_hired]['bonus_amount'], 3600.0)
        self.assertFalse(results[self.emp_left]['config'])

    def test_accrue_bonuses(self):
        card = self.scorecard
        card.action_confirm()
        card.action_accrue_bonus()
        # Only the monthly-advance employee is accrued before closing: no
        # advance for January and February, March prorated 30/31.
        self.assertFalse(card.final_bonus_ids)
        self.assertEqual(card.advance_bonus_ids.employee_id, self.emp_hired)
        self.assertEqual(len(card.advance_bonus_ids), 1)
        self.assertAlmostEqual(card.advance_bonus_ids.amount, 2903.23)
        self.assertEqual(card.advance_bonus_ids.date, date(2026, 3, 31))

        card.action_close()
        card.action_accrue_bonus()
        finals = {bonus.employee_id: bonus.amount for bonus in card.final_bonus_ids}
        self.assertEqual(len(card.final_bonus_ids), 3)
        self.assertAlmostEqual(finals[self.emp_full], 10800.0)
        self.assertAlmostEqual(finals[self.emp_transfer], 5400.0)
        self.assertAlmostEqual(finals[self.emp_hired], 3600.0 - 2903.23)
        self.assertNotIn(self.emp_left, card.bonus_ids.employee_id)

        # Idempotent
        card.action_accrue_bonus()
        self.assertEqual(card.bonus_count, 4)

    def test_reset_to_draft_blocked_by_accrued_bonuses(self):
        self.scorecard.action_confirm()
        self.scorecard.action_accrue_bonus()
        with self.assertRaises(UserError):
            self.scorecard.action_draft()

    def test_employee_result_rows(self):
        action = self.scorecard.action_open_employees()
        rows = self.env['hr.scorecard.employee.result'].search(action['domain'])
        self.assertEqual(len(rows), 4)
        row = rows.filtered(lambda r: r.employee_id == self.emp_transfer)
        self.assertEqual((row.date_from, row.date_to), (date(2026, 1, 1), date(2026, 2, 14)))
        self.assertEqual(row.days_in_position, 45)
        self.assertAlmostEqual(row.bonus_amount, 5400.0)

    def _assign(self, job, weight=100.0, date_from=date(2026, 1, 1)):
        return self.env['hr.kpi.assignment'].create({
            'job_id': job.id,
            'company_id': self.company.id,
            'date_from': date_from,
            'line_ids': [(0, 0, {'kpi_id': self.kpi.id, 'weight': weight})],
        })

    def test_kpi_map_data(self):
        target = self.scorecard.line_ids.target_id
        self._assign(self.job_a)
        data = self.env['hr.kpi.map'].get_map_data([('period_id', '=', self.period.id)])
        self.assertEqual(data['periods'], [{'id': self.period.id, 'name': self.period.display_name}])
        key = str(self.period.id)

        employees = {employee['id']: employee for employee in data['employees']}
        # Holders of job A during the period; job B has no assignment
        self.assertEqual(
            set(employees),
            {self.emp_full.id, self.emp_transfer.id, self.emp_hired.id, self.emp_left.id},
        )
        names = [employee['name'] for employee in data['employees']]
        self.assertEqual(names, sorted(names))

        full = employees[self.emp_full.id]
        # One KPI row and the weighted result row
        self.assertEqual(full['row_count'], 2)
        job = full['jobs'][0]
        self.assertEqual(job['id'], self.job_a.id)
        cell = job['kpis'][0]['cells'][key]
        self.assertEqual(job['kpis'][0]['id'], self.kpi.id)
        self.assertEqual(cell['target_id'], target.id)
        self.assertEqual(cell['weight'], 100.0)
        self.assertEqual((cell['planned'], cell['actual']), (100.0, 120.0))
        self.assertAlmostEqual(cell['achievement'], 120.0)
        total = job['totals'][key]
        self.assertAlmostEqual(total['weighted_result'], 120.0)
        self.assertAlmostEqual(total['total_weight'], 100.0)
        self.assertFalse(total['partial'])

        transfer_total = employees[self.emp_transfer.id]['jobs'][0]['totals'][key]
        self.assertTrue(transfer_total['partial'])
        self.assertEqual((transfer_total['days'], transfer_total['period_days']), (45, 90))

    def test_kpi_map_periods_are_columns(self):
        self._assign(self.job_a, date_from=date(2025, 1, 1))
        Period = self.env['hr.kpi.period']
        q2 = Period._find_or_create('quarter', 2026, quarter='2', company=self.company)
        q2_target = self.env['hr.kpi.target'].create({
            'kpi_id': self.kpi.id, 'period_id': q2.id, 'company_id': self.company.id,
            'planned_value': 100.0, 'actual_value': 50.0,
        })
        data = self.env['hr.kpi.map'].get_map_data([('period_id', 'in', (self.period | q2).ids)])
        self.assertEqual([period['id'] for period in data['periods']], [self.period.id, q2.id])
        full = next(e for e in data['employees'] if e['id'] == self.emp_full.id)
        # Same KPI row for both periods
        self.assertEqual(len(full['jobs'][0]['kpis']), 1)
        cells = full['jobs'][0]['kpis'][0]['cells']
        self.assertEqual(cells[str(q2.id)]['target_id'], q2_target.id)
        self.assertAlmostEqual(full['jobs'][0]['totals'][str(q2.id)]['weighted_result'], 50.0)
        # The employee who left in January has no cell for the second quarter
        left = next(e for e in data['employees'] if e['id'] == self.emp_left.id)
        self.assertNotIn(str(q2.id), left['jobs'][0]['kpis'][0]['cells'])

    def test_kpi_map_uses_assignment_in_force_at_period_start(self):
        key = str(self.period.id)
        self._assign(self.job_a, weight=40.0, date_from=date(2025, 1, 1))
        # Starts after the beginning of the period: not in force for it
        self._assign(self.job_a, weight=90.0, date_from=date(2026, 2, 1))
        data = self.env['hr.kpi.map'].get_map_data([('period_id', '=', self.period.id)])
        job = data['employees'][0]['jobs'][0]
        self.assertEqual(job['kpis'][0]['cells'][key]['weight'], 40.0)
        # Shared target of the KPI, job B with its own assignment
        self._assign(self.job_b, weight=60.0)
        data = self.env['hr.kpi.map'].get_map_data([('period_id', '=', self.period.id)])
        employees = {employee['id']: employee for employee in data['employees']}
        self.assertIn(self.emp_other.id, employees)
        self.assertEqual(employees[self.emp_other.id]['jobs'][0]['kpis'][0]['cells'][key]['weight'], 60.0)
        self.assertEqual(len(employees[self.emp_transfer.id]['jobs']), 2)
        self.assertEqual(employees[self.emp_transfer.id]['row_count'], 4)

    def test_kpi_map_follows_search_domain(self):
        self._assign(self.job_a)
        data = self.env['hr.kpi.map'].get_map_data([('kpi_id', '!=', self.kpi.id)])
        self.assertEqual(data['employees'], [])
        self.assertEqual(data['periods'], [])
        # The parent year of the quarter includes it (search panel child_of)
        data = self.env['hr.kpi.map'].get_map_data([('period_id', 'child_of', self.period.parent_id.id)])
        self.assertEqual(len(data['employees']), 4)

    def test_kpi_smart_buttons(self):
        self._assign(self.job_a)
        kpi = self.kpi
        self.assertEqual(kpi.target_count, 1)
        self.assertEqual(self.env['hr.kpi.target'].search(kpi.action_open_targets()['domain']),
                         self.scorecard.line_ids.target_id)
        self.assertEqual(kpi.job_count, 1)
        self.assertEqual(self.env['hr.job'].search(kpi.action_open_jobs()['domain']), self.job_a)
        # Holders of job A today, from the version history
        employees = self.env['hr.employee'].search(kpi.action_open_employees()['domain'])
        self.assertIn(self.emp_full, employees)
        self.assertIn(self.emp_hired, employees)
        self.assertNotIn(self.emp_transfer, employees)  # moved to job B
        self.assertNotIn(self.emp_left, employees)  # contract ended
        self.assertNotIn(self.emp_other, employees)
        self.assertEqual(kpi.employee_count, len(employees))
        # A newer assignment of job A without the KPI removes the job position
        self.env['hr.kpi.assignment'].create({
            'job_id': self.job_a.id,
            'company_id': self.company.id,
            'date_from': date(2026, 7, 1),
        })
        kpi.invalidate_recordset(['job_count', 'employee_count'])
        in_force = fields.Date.context_today(kpi) < date(2026, 7, 1)
        self.assertEqual(kpi.job_count, 1 if in_force else 0)

    def test_target_smart_buttons(self):
        target = self.scorecard.line_ids.target_id
        self.assertEqual(target.job_count, 0)
        self._assign(self.job_a)
        target.invalidate_recordset(['job_count', 'employee_count'])
        self.assertEqual(target.job_count, 1)
        self.assertEqual(self.env['hr.job'].search(target.action_open_jobs()['domain']), self.job_a)
        # Everyone who held job A during the period of the target
        employees = self.env['hr.employee'].with_context(active_test=False).search(
            target.action_open_employees()['domain'])
        self.assertEqual(employees, self.emp_full | self.emp_transfer | self.emp_hired | self.emp_left)
        self.assertEqual(target.employee_count, 4)
        # An assignment starting after the beginning of the period does not count
        self.env['hr.kpi.assignment'].create({
            'job_id': self.job_b.id,
            'company_id': self.company.id,
            'date_from': date(2026, 2, 1),
            'line_ids': [(0, 0, {'kpi_id': self.kpi.id, 'weight': 50.0})],
        })
        target.invalidate_recordset(['job_count'])
        self.assertEqual(target.job_count, 1)

    def test_kpi_map_action_preselects_period(self):
        action = self.env['hr.kpi.map'].action_open()
        self.assertEqual(action['res_model'], 'hr.kpi.target')
        self.assertEqual(action['views'][0][1], 'list')
        self.assertIn('searchpanel_default_period_id', action['context'])

    def test_kpi_map_without_hr_rights(self):
        user = self.env['res.users'].create({
            'name': 'KPI map outsider',
            'login': 'kpi_map_outsider',
            'group_ids': [(6, 0, [self.env.ref('base.group_user').id])],
        })
        with self.assertRaises(AccessError):
            self.env['hr.kpi.map'].with_user(user).get_map_data()

    def test_assign_wizard_by_job_positions(self):
        other_kpi = self.env['hr.kpi'].create({
            'name': 'Visits (test)', 'company_id': self.company.id,
        })
        wizard = self.env['hr.kpi.assign.wizard'].with_context(
            default_kpi_id=other_kpi.id,
            default_period_id=self.period.id,
            default_company_id=self.company.id,
        ).create({'job_ids': [(6, 0, (self.job_a | self.job_b).ids)]})
        wizard.action_save_assignments()
        lines = self.env['hr.scorecard.line'].search([
            ('kpi_id', '=', other_kpi.id), ('period_id', '=', self.period.id),
        ])
        self.assertEqual(lines.job_id, self.job_a | self.job_b)
        self.assertIn(self.scorecard, lines.scorecard_id)
