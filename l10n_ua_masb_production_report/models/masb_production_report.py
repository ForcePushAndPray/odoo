"""Analytic statement of production costs collected on account 23.

The report reproduces the layout Ukrainian production accountants work with:
opening balance, debit turnover split by corresponding credit account, credit
turnover split by corresponding debit account, closing balance - all of it in
the cut of production sub-account x subdivision x cost element.

Two things it has to reconstruct, because Odoo does not store them.

Correspondence. A journal entry is a set of lines, not a debit/credit pair.
Within one entry the amount of a line is spread over the lines of the opposite
side in proportion to their amounts. For the usual "one debit - several credits"
entry this is exact; for "several debits x several credits" no exact answer
exists at all, and proportional split is the accepted approximation. The same
rule is used by ``l10n_ua.account.analysis`` in the Ukrainian localization.

Subdivision. It comes from the analytic distribution of the journal item, from
the root plan chosen on the report. A line may be split between several
subdivisions, so every amount derived from it is split the same way. What the
distribution leaves unassigned lands in a row with no subdivision, which is what
makes a gap in the analytic data visible instead of silently shifting money to
the wrong workshop.
"""
import io
from collections import defaultdict

from odoo import _, api, fields, models
from odoo.exceptions import UserError

from .masb_production_column import COST_ELEMENTS

ELEMENT_SEQUENCE = {code: index for index, (code, _label)
                    in enumerate(COST_ELEMENTS)}


class MasbProductionReport(models.Model):
    _name = 'masb.production.report'
    _description = 'Production Cost Statement (account 23)'
    _order = 'date_from desc, id desc'

    name = fields.Char(compute='_compute_name', store=True)
    date_from = fields.Date(string='Period Start', required=True)
    date_to = fields.Date(string='Period End', required=True)
    company_id = fields.Many2one(
        'res.company',
        string='Company',
        required=True,
        default=lambda self: self.env.company,
    )
    currency_id = fields.Many2one(related='company_id.currency_id')
    analytic_plan_id = fields.Many2one(
        'account.analytic.plan',
        string='Subdivision Plan',
        required=True,
        default=lambda self: self._default_analytic_plan(),
        domain="[('parent_id', '=', False)]",
        help='Root analytic plan whose accounts are used as subdivisions. Only '
             'accounts of this plan are read from the analytic distribution.',
    )
    account_prefix = fields.Char(
        string='Account Prefixes',
        required=True,
        default='23',
        help='Comma separated prefixes of the production accounts covered by '
             'the statement, e.g. "23" or "231, 233, 235, 236".',
    )
    line_ids = fields.One2many(
        'masb.production.report.line', 'report_id', string='Lines')
    total_debit = fields.Monetary(
        compute='_compute_totals', store=True, currency_field='currency_id')
    total_credit = fields.Monetary(
        compute='_compute_totals', store=True, currency_field='currency_id')
    control_debit = fields.Monetary(
        string='Control Debit Turnover',
        readonly=True,
        currency_field='currency_id',
        help='Debit turnover of the production accounts taken straight from the '
             'journal items, without correspondence. The statement is only '
             'trustworthy while it equals the debit total.',
    )
    control_credit = fields.Monetary(
        string='Control Credit Turnover',
        readonly=True,
        currency_field='currency_id',
    )
    is_balanced = fields.Boolean(compute='_compute_totals', store=True)
    unassigned_amount = fields.Monetary(
        string='Without Subdivision',
        compute='_compute_totals',
        store=True,
        currency_field='currency_id',
        help='Debit turnover that carries no analytic account of the chosen '
             'plan. Anything above zero means journal items were posted without '
             'analytics.',
    )
    show_all_columns = fields.Boolean(
        string='Show All Columns',
        default=True,
        help='Keep every configured column in the statement, even the ones with '
             'no turnover. The accountant reads the form as a fixed blank, '
             'where a column stays in its place even when it is empty; turn it '
             'off to get a narrow statement of what actually moved.',
    )
    state = fields.Selection(
        selection=[('draft', 'Draft'), ('confirmed', 'Confirmed')],
        default='draft',
        required=True,
    )
    xlsx_file = fields.Binary(string='XLSX', readonly=True, attachment=True)
    xlsx_filename = fields.Char(readonly=True)

    @api.model
    def _default_analytic_plan(self):
        project_plan, _other = self.env['account.analytic.plan']._get_all_plans()
        return project_plan.id

    @api.depends('date_from', 'date_to')
    def _compute_name(self):
        for report in self:
            if report.date_from and report.date_to:
                report.name = _(
                    'Production statement %(date_from)s - %(date_to)s',
                    date_from=report.date_from, date_to=report.date_to)
            else:
                report.name = _('New')

    @api.depends('line_ids.turnover_debit', 'line_ids.turnover_credit',
                 'line_ids.line_type', 'line_ids.analytic_account_id',
                 'control_debit', 'control_credit')
    def _compute_totals(self):
        for report in self:
            groups = report.line_ids.filtered(
                lambda line: line.line_type == 'group')
            report.total_debit = sum(groups.mapped('turnover_debit'))
            report.total_credit = sum(groups.mapped('turnover_credit'))
            report.unassigned_amount = sum(groups.filtered(
                lambda line: not line.analytic_account_id
            ).mapped('turnover_debit'))
            currency = report.company_id.currency_id
            report.is_balanced = bool(currency) and (
                currency.is_zero(report.total_debit - report.control_debit)
                and currency.is_zero(report.total_credit - report.control_credit)
            )

    # ------------------------------------------------------------------
    # Source data
    # ------------------------------------------------------------------

    def _prefix_tuple(self):
        self.ensure_one()
        return tuple(
            prefix for prefix in
            (part.strip() for part in (self.account_prefix or '').split(','))
            if prefix
        )

    def _production_accounts(self):
        """Production accounts covered by the statement."""
        self.ensure_one()
        prefixes = self._prefix_tuple()
        if not prefixes:
            raise UserError(_('Set at least one production account prefix.'))
        Account = self.env['account.account'].with_company(self.company_id)
        accounts = Account.browse()
        for prefix in prefixes:
            accounts |= Account.search([('code', '=like', '%s%%' % prefix)])
        if not accounts:
            raise UserError(_(
                'No account of company %(company)s starts with %(prefixes)s.',
                company=self.company_id.display_name,
                prefixes=self.account_prefix))
        return accounts

    def _dimension_shares(self, line):
        """Subdivisions of one journal item as ``[(analytic_id, fraction)]``.

        Fractions always add up to 1: whatever the analytic distribution leaves
        unassigned - or assigns to other plans only - is returned under
        ``False`` so that no amount disappears from the statement.
        """
        self.ensure_one()
        plan = self.analytic_plan_id
        Analytic = self.env['account.analytic.account']
        shares = defaultdict(float)
        for key, percentage in (line.analytic_distribution or {}).items():
            ids = [int(part) for part in str(key).split(',') if part.isdigit()]
            accounts = Analytic.browse(ids).exists().filtered(
                lambda account: account.root_plan_id == plan)
            if accounts:
                shares[accounts[0].id] += (percentage or 0.0) / 100.0
        assigned = sum(shares.values())
        if assigned < 1.0:
            shares[False] += 1.0 - assigned
        return list(shares.items())

    def _iter_correspondence(self, lines):
        """Yield ``(line, corresponding_account, amount, is_debit)`` tuples.

        The amount of every journal item is spread over the opposite side of its
        own entry in proportion to the amounts there. Section and note lines
        have no debit and no credit, so the same filter drops them.
        """
        for line in lines:
            is_debit = bool(line.debit)
            amount = line.debit if is_debit else line.credit
            if not amount:
                continue
            opposite = line.move_id.line_ids.filtered(
                lambda other: bool(other.credit) if is_debit
                else bool(other.debit))
            opposite_total = sum(
                other.credit if is_debit else other.debit
                for other in opposite)
            if not opposite_total:
                continue
            for other in opposite:
                other_amount = other.credit if is_debit else other.debit
                yield (line, other.account_id,
                       amount * other_amount / opposite_total, is_debit)

    # ------------------------------------------------------------------
    # Computation
    # ------------------------------------------------------------------

    def action_compute(self):
        self.ensure_one()
        if self.state == 'confirmed':
            raise UserError(_('Reset the statement to draft before recomputing.'))
        if self.date_to < self.date_from:
            raise UserError(_('Period end cannot be earlier than period start.'))

        self.line_ids.unlink()
        self.xlsx_file = False

        accounts = self._production_accounts()
        codes = {
            account.id: account.with_company(self.company_id).code or ''
            for account in accounts
        }
        AML = self.env['account.move.line']
        base_domain = [
            ('parent_state', '=', 'posted'),
            ('company_id', '=', self.company_id.id),
            ('account_id', 'in', accounts.ids),
        ]

        openings = self._collect_openings(AML, base_domain)
        period_lines = AML.search(base_domain + [
            ('date', '>=', self.date_from),
            ('date', '<=', self.date_to),
        ])
        debit_layout = self.env['masb.production.column']._layout(
            self.company_id, 'debit')
        credit_layout = self.env['masb.production.column']._layout(
            self.company_id, 'credit')

        # (account_id, analytic_id, element) -> {column_id: amount}
        debit_cells = defaultdict(lambda: defaultdict(float))
        # (account_id, analytic_id) -> {column_id: amount}, spread later
        credit_cells = defaultdict(lambda: defaultdict(float))

        # Control totals come from the journal items themselves, not from the
        # cells: that is what makes them a control. An entry whose opposite side
        # is empty contributes nothing to the matrix, and the difference is then
        # visible instead of silently agreeing with itself.
        totals = AML._read_group(
            base_domain + [('date', '>=', self.date_from),
                           ('date', '<=', self.date_to)],
            [], ['debit:sum', 'credit:sum'])
        self.control_debit = (totals[0][0] or 0.0) if totals else 0.0
        self.control_credit = (totals[0][1] or 0.0) if totals else 0.0

        for line, corr_account, amount, is_debit in self._iter_correspondence(
                period_lines):
            corr_code = corr_account.with_company(self.company_id).code or ''
            layout = debit_layout if is_debit else credit_layout
            column = self._match_column(corr_code, layout)
            for analytic_id, fraction in self._dimension_shares(line):
                share = amount * fraction
                if is_debit:
                    key = (line.account_id.id, analytic_id,
                           column.cost_element if column else 'direct')
                    debit_cells[key][column.id if column else False] += share
                else:
                    key = (line.account_id.id, analytic_id)
                    credit_cells[key][column.id if column else False] += share

        self._build_lines(codes, openings, debit_cells, credit_cells)
        return True

    def _collect_openings(self, AML, base_domain):
        """Balance before the period per ``(account_id, analytic_id)``."""
        self.ensure_one()
        openings = defaultdict(float)
        previous = AML.search(
            base_domain + [('date', '<', self.date_from)])
        for line in previous:
            for analytic_id, fraction in self._dimension_shares(line):
                openings[(line.account_id.id, analytic_id)] += (
                    line.balance * fraction)
        return openings

    @api.model
    def _match_column(self, code, layout):
        """First column of the layout whose prefix the code starts with."""
        for column in layout:
            if code.startswith(column._prefix_tuple()):
                return column
        return self.env['masb.production.column']

    def _build_lines(self, codes, openings, debit_cells, credit_cells):
        """Turn the collected cells into group and element rows.

        Credit turnover is not attributable to a cost element on its own - the
        write-off of finished goods does not know which part of it was cement
        and which was wages. It is therefore spread over the elements in
        proportion to their debit turnover of the same period, which is what the
        paper statement does. A group with no debit turnover keeps its credit on
        the group row alone.
        """
        self.ensure_one()
        groups = set(key[:2] for key in debit_cells)
        groups |= set(credit_cells)
        groups |= set(openings)

        Line = self.env['masb.production.report.line']
        analytics = self.env['account.analytic.account'].browse(
            [analytic_id for _account_id, analytic_id in groups if analytic_id])
        analytic_names = {
            account.id: account.display_name for account in analytics}
        responsibles = {
            account.id: account.masb_responsible_id.name
            for account in analytics}
        sequence = 0
        for account_id, analytic_id in sorted(
                groups,
                key=lambda key: (codes.get(key[0], ''),
                                 analytic_names.get(key[1], ''))):
            element_debits = {
                element: sum(cells.values())
                for (line_account, line_analytic, element), cells
                in debit_cells.items()
                if (line_account, line_analytic) == (account_id, analytic_id)
            }
            debit_total = sum(element_debits.values())
            group_credit = credit_cells.get((account_id, analytic_id), {})
            opening = openings.get((account_id, analytic_id), 0.0)

            group_debit = defaultdict(float)
            for (line_account, line_analytic, _element), cells in \
                    debit_cells.items():
                if (line_account, line_analytic) != (account_id, analytic_id):
                    continue
                for column_id, amount in cells.items():
                    group_debit[column_id] += amount

            sequence += 10
            group_line = Line.create({
                'report_id': self.id,
                'sequence': sequence,
                'line_type': 'group',
                'account_id': account_id,
                'analytic_account_id': analytic_id or False,
                'responsible_name': responsibles.get(analytic_id) or False,
                'opening_balance': opening,
            })
            group_line._write_cells(group_debit, group_credit)

            for element, element_debit in sorted(
                    element_debits.items(),
                    key=lambda item: ELEMENT_SEQUENCE.get(item[0], 99)):
                sequence += 1
                element_line = Line.create({
                    'report_id': self.id,
                    'sequence': sequence,
                    'line_type': 'element',
                    'account_id': account_id,
                    'analytic_account_id': analytic_id or False,
                    'cost_element': element,
                })
                ratio = (element_debit / debit_total) if debit_total else 0.0
                element_line._write_cells(
                    dict(debit_cells[(account_id, analytic_id, element)]),
                    {column_id: amount * ratio
                     for column_id, amount in group_credit.items()})

    def action_open_entries(self, line_id, column_key):
        """Open the journal items behind one figure of the statement.

        The correspondence is rebuilt the same way the statement was built, and
        the journal items that fed the cell are collected by id. A domain on
        ``account.move.line`` could not express this on its own: which account
        a line corresponds to is not stored anywhere, it is derived from the
        other side of its entry.
        """
        self.ensure_one()
        line = self.env['masb.production.report.line'].browse(line_id).exists()
        if not line or line.report_id != self:
            raise UserError(_('This figure does not belong to the statement.'))
        column = next((column for column in self._report_grid()['columns']
                       if column['key'] == column_key), None)
        if not column or column['role'] in ('text', 'closing'):
            raise UserError(_(
                'The closing balance is not a set of entries: it is the '
                'opening balance plus the turnover of the period.'))
        if (line.line_type == 'element' and column['block'] == 'credit'
                and column['role'] != 'opening'):
            raise UserError(_(
                'Credit turnover is not attributable to a single cost element: '
                'the figure is the write-off spread over the elements in '
                'proportion to their debit turnover. Open the subdivision row '
                'instead.'))

        move_lines = self._entries_behind(line, column)
        return {
            'type': 'ir.actions.act_window',
            'name': _('%(row)s - %(column)s',
                      row=line.display_name, column=column['label']),
            'res_model': 'account.move.line',
            'view_mode': 'list,form',
            # ``views`` has to be spelled out. An action returned from a button
            # is completed by the web controller (``clean_action`` fills the
            # views from ``view_mode``), but this one is fetched by the widget
            # through a plain ORM call, which goes nowhere near that controller
            # - and the client then reads ``action.views`` of undefined.
            'views': [(False, 'list'), (False, 'form')],
            'domain': [('id', 'in', move_lines.ids)],
            'context': {'create': False, 'search_default_group_by_move': 1},
        }

    def _entries_behind(self, line, column):
        """Journal items that produced one cell of the statement."""
        self.ensure_one()
        AML = self.env['account.move.line']
        base = [
            ('parent_state', '=', 'posted'),
            ('company_id', '=', self.company_id.id),
            ('account_id', '=', line.account_id.id),
        ]
        if column['role'] == 'opening':
            candidates = AML.search(base + [('date', '<', self.date_from)])
            return candidates.filtered(lambda aml: self._line_belongs(aml, line))

        candidates = AML.search(base + [
            ('date', '>=', self.date_from),
            ('date', '<=', self.date_to),
        ]).filtered(lambda aml: self._line_belongs(aml, line))

        layout = self.env['masb.production.column']._layout(
            self.company_id, column['block'])
        # An empty recordset stands for the catch-all "Other" column, so it has
        # to be built empty rather than browsed: ``browse(False)`` would hand
        # back a placeholder record that equals nothing.
        Column = self.env['masb.production.column']
        wanted = Column.browse(column['column_id']) if column['column_id'] \
            else Column
        elements = None
        if line.line_type == 'element' and column['role'] == 'total':
            elements = line.cost_element

        found = AML.browse()
        for aml, corr_account, _amount, is_debit in self._iter_correspondence(
                candidates):
            if is_debit != (column['block'] == 'debit'):
                continue
            matched = self._match_column(
                corr_account.with_company(self.company_id).code or '', layout)
            if column['role'] == 'column' and matched != wanted:
                continue
            # Turnover against an account no column covers is reported under
            # other direct costs, exactly as ``action_compute`` files it.
            if elements and (matched.cost_element or 'direct') != elements:
                continue
            found |= aml
        return found

    def _line_belongs(self, move_line, line):
        """Does a journal item feed the row of the statement?"""
        self.ensure_one()
        shares = dict(self._dimension_shares(move_line))
        return (line.analytic_account_id.id or False) in shares

    def action_open_pivot(self):
        """Open the cells in the standard pivot view.

        The widget on the form draws the statement as the accountant signs it;
        the pivot is for the questions the blank does not answer - one
        subdivision across cost elements, one column across subdivisions. Both
        read the same cells, so the figures cannot disagree.

        Subdivision rows are preselected: the element rows below them break the
        very same turnover down, and summing both would double every figure.
        """
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': self.name,
            'res_model': 'masb.production.report.cell',
            'view_mode': 'pivot,list',
            'domain': [('report_id', '=', self.id)],
            'context': {
                'create': False,
                'search_default_group_rows': 1,
                'pivot_row_groupby': ['analytic_account_id'],
                'pivot_column_groupby': ['column_id'],
                'pivot_measures': ['amount'],
            },
        }

    def action_confirm(self):
        self.state = 'confirmed'

    def action_draft(self):
        self.state = 'draft'

    # ------------------------------------------------------------------
    # Rendering
    # ------------------------------------------------------------------

    def get_matrix(self):
        """The statement as a flat grid, for the form widget.

        Called from the browser, so it returns plain JSON-able data rather than
        records: the widget only draws, it does not need to know the models
        behind the numbers.
        """
        self.ensure_one()
        return self._report_grid()

    def _report_grid(self):
        """Columns and rows of the statement, in one flat structure.

        Three renderers consume this: the form widget, the printed form and the
        spreadsheet. Giving them one structure - instead of each assembling the
        columns in its own order - is what keeps the screen, the paper and the
        file literally identical.
        """
        self.ensure_one()
        matrix = self._report_matrix()
        layout = matrix['layout']
        columns = [
            {'key': 'account', 'label': _('Account'), 'numeric': False,
             'role': 'text'},
            {'key': 'label', 'label': _('Subdivision / cost element'),
             'numeric': False, 'role': 'text'},
            {'key': 'opening', 'label': _('Opening balance'), 'numeric': True,
             'role': 'opening', 'block': False, 'column_id': False},
        ]
        for block, prefix, total_key, total_label in (
                ('debit', 'd', 'total_debit', _('Total debit')),
                ('credit', 'c', 'total_credit', _('Total credit'))):
            ids = [column.id for column in layout[block]['columns']]
            if layout[block]['other']:
                ids.append(False)
            for index, title in enumerate(self._column_titles(layout[block])):
                columns.append({
                    'key': '%s%s' % (prefix, index), 'label': title,
                    'numeric': True, 'role': 'column', 'block': block,
                    'column_id': ids[index],
                })
            columns.append({'key': total_key, 'label': total_label,
                            'numeric': True, 'strong': True, 'role': 'total',
                            'block': block, 'column_id': False})
        columns.append({'key': 'closing', 'label': _('Closing balance'),
                        'numeric': True, 'role': 'closing', 'block': False,
                        'column_id': False})

        rows = []
        for row in matrix['rows']:
            rows.append({
                'kind': ('total' if row['is_total']
                         else 'group' if row['is_group'] else 'element'),
                'line_id': row['line'].id,
                'cells': (
                    [row['account_code'], row['label'], row['opening_balance']]
                    + row['debit'] + [row['turnover_debit']]
                    + row['credit']
                    + [row['turnover_credit'], row['closing_balance']]),
            })
        return {
            'columns': columns,
            'rows': rows,
            'currency_id': self.currency_id.id,
            'control_debit': self.control_debit,
            'control_credit': self.control_credit,
            'is_balanced': self.is_balanced,
            'control_label': _('Control'),
            'control_credit_label': _('Control, credit'),
            'mismatch_label': _(
                'The statement does not match the journal items.'),
        }

    def _report_layout(self):
        """Columns actually used by this statement, per block.

        ``other`` tells whether the block also needs the trailing catch-all
        column: turnover against a corresponding account that no configured
        column matches is real money and has to stay visible, otherwise the row
        total would stop matching the cells next to it.
        """
        self.ensure_one()
        Column = self.env['masb.production.column']
        cells = self.line_ids.cell_ids
        used = set(cells.mapped('column_id').ids)
        return {
            block: {
                'columns': [
                    column for column in Column._layout(self.company_id, block)
                    if self.show_all_columns or column.id in used
                ],
                'other': any(
                    not cell.column_id for cell in cells
                    if cell.block == block),
            }
            for block in ('debit', 'credit')
        }

    def _report_matrix(self):
        """Rows of the statement ready for rendering.

        Returns a list of dicts with the row label, the balances and one amount
        per column of each block, in the order of ``_report_layout``.
        """
        self.ensure_one()
        layout = self._report_layout()
        # Labels come from the field, not from the raw selection list: the list
        # holds the English source terms, while the field hands over whatever
        # the .po says for the user's language.
        element_labels = dict(
            self.env['masb.production.report.line']._fields['cost_element']
            ._description_selection(self.env))
        rows = []
        for line in self.line_ids.sorted('sequence'):
            amounts = defaultdict(float)
            for cell in line.cell_ids:
                amounts[(cell.column_id.id, cell.block)] = cell.amount
            is_group = line.line_type == 'group'
            label = (line.analytic_account_id.display_name
                     or _('No subdivision')) if is_group \
                else element_labels.get(line.cost_element, '')
            if is_group and line.responsible_name:
                label = '%s, %s' % (label, line.responsible_name)
            rows.append({
                'line': line,
                'is_group': is_group,
                'is_total': False,
                'label': label,
                'account_code': (
                    line.account_id.with_company(self.company_id).code
                    if is_group else ''),
                'opening_balance': line.opening_balance,
                'closing_balance': line.closing_balance,
                'turnover_debit': line.turnover_debit,
                'turnover_credit': line.turnover_credit,
                'debit': self._row_values(amounts, layout['debit'], 'debit'),
                'credit': self._row_values(
                    amounts, layout['credit'], 'credit'),
            })
        rows.append(self._total_row(layout, rows))
        return {'layout': layout, 'rows': rows}

    def _total_row(self, layout, rows):
        """The closing "TOTAL" row of the statement.

        Only group rows are summed: the element rows below them break the very
        same turnover down, so adding both would double every figure.
        """
        self.ensure_one()
        groups = [row for row in rows if row['is_group']]
        width = {block: len(layout[block]['columns'])
                 + (1 if layout[block]['other'] else 0)
                 for block in ('debit', 'credit')}
        return {
            'line': self.env['masb.production.report.line'],
            'is_group': False,
            'is_total': True,
            'label': _('TOTAL'),
            'account_code': '',
            'opening_balance': sum(row['opening_balance'] for row in groups),
            'closing_balance': sum(row['closing_balance'] for row in groups),
            'turnover_debit': sum(row['turnover_debit'] for row in groups),
            'turnover_credit': sum(row['turnover_credit'] for row in groups),
            'debit': [sum(row['debit'][index] for row in groups)
                      for index in range(width['debit'])],
            'credit': [sum(row['credit'][index] for row in groups)
                       for index in range(width['credit'])],
        }

    @api.model
    def _row_values(self, amounts, block_layout, block):
        """Amounts of one row in the column order of the block."""
        values = [amounts[(column.id, block)]
                  for column in block_layout['columns']]
        if block_layout['other']:
            values.append(amounts[(False, block)])
        return values

    def action_export_xlsx(self):
        """Build the matrix as a spreadsheet and hand it over for download."""
        self.ensure_one()
        if not self.line_ids:
            raise UserError(_('Compute the statement before exporting it.'))
        self.xlsx_file = self._render_xlsx()
        self.xlsx_filename = '%s.xlsx' % (self.name or 'production-statement')
        return {
            'type': 'ir.actions.act_url',
            'url': '/web/content/%s/%s/xlsx_file/%s?download=true' % (
                self._name, self.id, self.xlsx_filename),
            'target': 'self',
        }

    @api.model
    def _column_titles(self, block_layout):
        """Header captions of one block, catch-all column included."""
        titles = [column.name for column in block_layout['columns']]
        if block_layout['other']:
            titles.append(_('Other'))
        return titles

    def _render_xlsx(self):
        """Write the shared grid into a spreadsheet.

        The sheet follows ``_report_grid`` column for column, so the file the
        accountant opens in Excel is the same table the form shows and the
        printer prints.
        """
        import base64

        import xlsxwriter

        self.ensure_one()
        grid = self._report_grid()
        stream = io.BytesIO()
        workbook = xlsxwriter.Workbook(stream, {'in_memory': True})
        sheet = workbook.add_worksheet(_('Account 23'))
        header = workbook.add_format({
            'bold': True, 'text_wrap': True, 'valign': 'bottom',
            'align': 'center', 'border': 1})
        strong_number = workbook.add_format({
            'bold': True, 'num_format': '#,##0.00'})
        strong_text = workbook.add_format({'bold': True})
        number = workbook.add_format({'num_format': '#,##0.00'})
        indent = workbook.add_format({'indent': 2})

        sheet.write_row(0, 0, [column['label'] for column in grid['columns']],
                        header)
        sheet.set_row(0, 34)
        sheet.set_column(0, 0, 12)
        sheet.set_column(1, 1, 34)
        sheet.set_column(2, len(grid['columns']) - 1, 14)
        sheet.freeze_panes(1, 2)

        index = 0
        for index, row in enumerate(grid['rows'], start=1):
            strong = row['kind'] in ('group', 'total')
            for position, value in enumerate(row['cells']):
                if grid['columns'][position]['numeric']:
                    style = strong_number if strong else number
                else:
                    style = strong_text if strong else indent
                sheet.write(index, position, value, style)

        # The control line repeats the turnover taken straight from the journal
        # items. On paper it is what the accountant signs the statement against.
        control = index + 2
        sheet.write(control, 1, grid['control_label'], strong_text)
        sheet.write(control, 2, grid['control_debit'], strong_number)
        sheet.write(control + 1, 1, grid['control_credit_label'], strong_text)
        sheet.write(control + 1, 2, grid['control_credit'], strong_number)
        if not grid['is_balanced']:
            sheet.write(control + 2, 1, grid['mismatch_label'], strong_text)

        workbook.close()
        return base64.b64encode(stream.getvalue())
