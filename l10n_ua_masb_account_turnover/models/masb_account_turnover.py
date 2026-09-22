"""Journal-order and ledger of an account in the cut of an analytic dimension.

The statement reproduces the register Ukrainian accountants know from 1C as the
journal-order and ledger by account: opening balance, debit turnover split by
corresponding credit account, credit turnover split by corresponding debit
account, closing balance - all of it per value of an analytic dimension. What
the dimension is, which accounts are covered and which columns the blank has is
decided by the statement type (``masb.account.turnover.type``): the production
statement of account 23 and the supplier ledger of account 631 are two records
there, not two reports.

Two things it has to reconstruct, because Odoo does not store them.

Correspondence. A journal entry is a set of lines, not a debit/credit pair.
Within one entry the amount of a line is spread over the lines of the opposite
side in proportion to their amounts. For the usual "one debit - several credits"
entry this is exact; for "several debits x several credits" no exact answer
exists at all, and proportional split is the accepted approximation. The same
rule is used by ``l10n_ua.account.analysis`` in the Ukrainian localization.

Dimension. It comes either from the analytic distribution of the journal item -
which may split one item between several rows, so every amount derived from it
is split the same way - or from its subconto value, falling back to the field
Odoo fills by itself (the partner of a bill) when no subconto was entered. What
carries no value lands in a row of its own, which is what makes a gap in the
analytic data visible instead of silently shifting money to the wrong row.
"""
import base64
import io
import re
from collections import defaultdict
from urllib.parse import quote

from odoo import _, api, fields, models
from odoo.exceptions import UserError

from .masb_account_turnover_column import COST_ELEMENTS
from .masb_account_turnover_type import split_prefixes

ELEMENT_SEQUENCE = {code: index for index, (code, _label)
                    in enumerate(COST_ELEMENTS)}

# Characters a spreadsheet does not accept in a sheet name.
SHEET_NAME_FORBIDDEN = re.compile(r'[\[\]:*?/\\]')


class MasbAccountTurnover(models.Model):
    _name = 'masb.account.turnover'
    _description = 'Account Turnover Statement'
    _order = 'date_from desc, id desc'
    _check_company_auto = True

    name = fields.Char(compute='_compute_name', store=True)
    type_id = fields.Many2one(
        'masb.account.turnover.type',
        string='Statement Type',
        required=True,
        ondelete='restrict',
        index=True,
        check_company=True,
    )
    dimension_kind = fields.Selection(related='type_id.dimension_kind')
    use_cost_elements = fields.Boolean(related='type_id.use_cost_elements')
    balance_layout = fields.Selection(related='type_id.balance_layout')
    date_from = fields.Date(string='Period Start', required=True)
    date_to = fields.Date(string='Period End', required=True)
    company_id = fields.Many2one(
        'res.company',
        string='Company',
        required=True,
        default=lambda self: self.env.company,
    )
    currency_id = fields.Many2one(related='company_id.currency_id')
    # The scope is copied from the type when the statement is created rather
    # than read through it: a closed statement has to keep saying what it was
    # computed for, even after the type is reconfigured.
    account_prefix = fields.Char(
        string='Account Prefixes',
        compute='_compute_scope',
        store=True,
        readonly=False,
        precompute=True,
        required=True,
        help='Comma separated prefixes of the accounts covered by the '
             'statement, e.g. "631" or "231, 233, 235, 236".',
    )
    analytic_plan_id = fields.Many2one(
        'account.analytic.plan',
        string='Analytic Plan',
        compute='_compute_scope',
        store=True,
        readonly=False,
        precompute=True,
        domain="[('parent_id', '=', False)]",
        help='Root analytic plan whose accounts are the rows of the statement. '
             'Only accounts of this plan are read from the analytic '
             'distribution.',
    )
    subconto_type_id = fields.Many2one(
        'l10n_ua.subconto.type',
        string='Subconto Type',
        compute='_compute_scope',
        store=True,
        readonly=False,
        precompute=True,
        help='Subconto whose values are the rows of the statement.',
    )
    line_ids = fields.One2many(
        'masb.account.turnover.line', 'sheet_id', string='Lines')
    total_debit = fields.Monetary(
        compute='_compute_totals', store=True, currency_field='currency_id')
    total_credit = fields.Monetary(
        compute='_compute_totals', store=True, currency_field='currency_id')
    control_debit = fields.Monetary(
        string='Control Debit Turnover',
        readonly=True,
        currency_field='currency_id',
        help='Debit turnover of the statement accounts taken straight from the '
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
        string='Without Analytics',
        compute='_compute_totals',
        store=True,
        currency_field='currency_id',
        help='Turnover, debit plus credit, that carries no value of the row '
             'dimension. Anything above zero means journal items were posted '
             'without a subdivision, a partner or whatever the rows are.',
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
        return project_plan

    @api.depends('type_id')
    def _compute_scope(self):
        default_plan = self._default_analytic_plan()
        for sheet in self:
            sheet_type = sheet.type_id
            sheet.account_prefix = sheet_type.account_prefixes
            sheet.subconto_type_id = sheet_type.subconto_type_id
            sheet.analytic_plan_id = (
                (sheet_type.analytic_plan_id or default_plan)
                if sheet_type.dimension_kind == 'analytic' else False)

    @api.depends('type_id.name', 'date_from', 'date_to')
    def _compute_name(self):
        for sheet in self:
            if sheet.type_id and sheet.date_from and sheet.date_to:
                sheet.name = _(
                    '%(type)s, %(date_from)s - %(date_to)s',
                    type=sheet.type_id.name,
                    date_from=sheet.date_from, date_to=sheet.date_to)
            else:
                sheet.name = _('New')

    @api.depends('line_ids.turnover_debit', 'line_ids.turnover_credit',
                 'line_ids.line_type', 'line_ids.dimension_res_id',
                 'control_debit', 'control_credit')
    def _compute_totals(self):
        for sheet in self:
            groups = sheet.line_ids.filtered(
                lambda line: line.line_type == 'group')
            sheet.total_debit = sum(groups.mapped('turnover_debit'))
            sheet.total_credit = sum(groups.mapped('turnover_credit'))
            unassigned = groups.filtered(lambda line: not line.dimension_res_id)
            sheet.unassigned_amount = (
                sum(unassigned.mapped('turnover_debit'))
                + sum(unassigned.mapped('turnover_credit')))
            currency = sheet.company_id.currency_id
            sheet.is_balanced = bool(currency) and (
                currency.is_zero(sheet.total_debit - sheet.control_debit)
                and currency.is_zero(sheet.total_credit - sheet.control_credit)
            )

    # ------------------------------------------------------------------
    # Source data
    # ------------------------------------------------------------------

    def _covered_accounts(self):
        """Accounts covered by the statement."""
        self.ensure_one()
        prefixes = split_prefixes(self.account_prefix)
        if not prefixes:
            raise UserError(_('Set at least one account prefix.'))
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
        """Rows one journal item belongs to, as ``[(dimension_key, fraction)]``.

        A dimension key is ``(model, id)`` of the row value, or ``False`` for
        the unassigned row. Fractions always add up to 1, so no amount
        disappears from the statement.

        The work is done by ``_dimension_shares_<kind>``, one method per kind
        of the statement type. A new kind of rows - a warehouse, a contract -
        is a new selection value on the type and one more method here, the rest
        of the statement does not change.
        """
        self.ensure_one()
        return getattr(
            self, '_dimension_shares_%s' % self.type_id.dimension_kind)(line)

    def _dimension_shares_analytic(self, line):
        """Subdivisions of the analytic distribution of the chosen root plan.

        Whatever the distribution leaves unassigned - or assigns to other plans
        only - goes to the unassigned row.
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
                shares[(Analytic._name, accounts[0].id)] += (
                    (percentage or 0.0) / 100.0)
        assigned = sum(shares.values())
        if assigned < 1.0:
            shares[False] += 1.0 - assigned
        return list(shares.items())

    def _dimension_shares_subconto(self, line):
        """The subconto value of the item, whole - a subconto is never split."""
        self.ensure_one()
        record = self._subconto_value(line)
        return [((record._name, record.id) if record else False, 1.0)]

    def _subconto_value(self, line):
        """Value of the statement subconto on one journal item.

        The subconto entered on the item wins. When there is none, the field
        Odoo fills by itself stands in for it (``_native_dimension_fields``):
        subconto values are typed by hand and mostly are not, while every bill
        and every payment carries its partner anyway.
        """
        self.ensure_one()
        subconto_type = self.subconto_type_id
        Model = self.env[subconto_type.model_name]
        value = line.subconto_ids.filtered(
            lambda sub: sub.subconto_type_id == subconto_type)[:1]
        record = Model.browse(value.res_id).exists() if value.res_id else Model
        if not record:
            native_field = self._native_dimension_fields().get(Model._name)
            if native_field:
                record = line[native_field]
        return self._normalize_dimension(record)

    @api.model
    def _native_dimension_fields(self):
        """Field of a journal item standing in for a subconto of a given model.

        A bridge module adds its own model here the same way it extends
        ``account.move.line._subconto_quick_fields_map``.
        """
        return {
            'res.partner': 'partner_id',
            'product.product': 'product_id',
        }

    @api.model
    def _normalize_dimension(self, record):
        """The record a row is kept for.

        A partner is reduced to its commercial entity. Bills get it from Odoo
        itself (``account.move.line._compute_partner_id``), but a payment or a
        manual entry keeps whatever contact was picked - "Supplier LLC, John
        Smith" - and without this one supplier would fall apart into as many
        rows as it has contacts.
        """
        if record._name == 'res.partner':
            return record.commercial_partner_id
        return record

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

    def _check_scope(self):
        """Refuse to compute a statement whose rows cannot be determined."""
        self.ensure_one()
        kind = self.type_id.dimension_kind
        if kind == 'analytic' and not self.analytic_plan_id:
            raise UserError(_('Set the analytic plan whose accounts are the '
                              'rows of the statement.'))
        if kind == 'subconto' and not self.subconto_type_id:
            raise UserError(_('Set the subconto type whose values are the rows '
                              'of the statement.'))

    def action_compute(self):
        self.ensure_one()
        if self.state == 'confirmed':
            raise UserError(_('Reset the statement to draft before recomputing.'))
        if self.date_to < self.date_from:
            raise UserError(_('Period end cannot be earlier than period start.'))
        self._check_scope()

        self.line_ids.unlink()
        self.xlsx_file = False

        accounts = self._covered_accounts()
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
        period_domain = base_domain + [
            ('date', '>=', self.date_from),
            ('date', '<=', self.date_to),
        ]

        openings = self._collect_openings(AML, base_domain)
        period_lines = AML.search(period_domain)
        Column = self.env['masb.account.turnover.column']
        debit_layout = Column._layout(self.type_id, self.company_id, 'debit')
        credit_layout = Column._layout(self.type_id, self.company_id, 'credit')
        use_elements = self.type_id.use_cost_elements

        # (account_id, dimension_key, element) -> {column_id: amount}
        debit_cells = defaultdict(lambda: defaultdict(float))
        # (account_id, dimension_key) -> {column_id: amount}, spread later
        credit_cells = defaultdict(lambda: defaultdict(float))

        # Control totals come from the journal items themselves, not from the
        # cells: that is what makes them a control. An entry whose opposite side
        # is empty contributes nothing to the matrix, and the difference is then
        # visible instead of silently agreeing with itself.
        totals = AML._read_group(period_domain, [], ['debit:sum', 'credit:sum'])
        self.control_debit = (totals[0][0] or 0.0) if totals else 0.0
        self.control_credit = (totals[0][1] or 0.0) if totals else 0.0

        for line, corr_account, amount, is_debit in self._iter_correspondence(
                period_lines):
            corr_code = corr_account.with_company(self.company_id).code or ''
            layout = debit_layout if is_debit else credit_layout
            column = self._match_column(corr_code, layout)
            for dimension, fraction in self._dimension_shares(line):
                share = amount * fraction
                if is_debit:
                    element = ((column.cost_element if column else 'direct')
                               if use_elements else False)
                    key = (line.account_id.id, dimension, element)
                    debit_cells[key][column.id if column else False] += share
                else:
                    key = (line.account_id.id, dimension)
                    credit_cells[key][column.id if column else False] += share

        self._build_lines(codes, openings, debit_cells, credit_cells)
        return True

    def _collect_openings(self, AML, base_domain):
        """Balance before the period per ``(account_id, dimension_key)``."""
        self.ensure_one()
        openings = defaultdict(float)
        previous = AML.search(base_domain + [('date', '<', self.date_from)])
        for line in previous:
            for dimension, fraction in self._dimension_shares(line):
                openings[(line.account_id.id, dimension)] += (
                    line.balance * fraction)
        return openings

    @api.model
    def _match_column(self, code, layout):
        """First column of the layout whose prefix the code starts with."""
        for column in layout:
            if code.startswith(column._prefix_tuple()):
                return column
        return self.env['masb.account.turnover.column']

    def _dimension_records(self, dimensions):
        """Records behind a set of dimension keys, as ``{key: record}``."""
        ids_by_model = defaultdict(set)
        for dimension in dimensions:
            if dimension:
                ids_by_model[dimension[0]].add(dimension[1])
        records = {}
        for model, ids in ids_by_model.items():
            for record in self.env[model].browse(ids):
                records[(model, record.id)] = record
        return records

    def _build_lines(self, codes, openings, debit_cells, credit_cells):
        """Turn the collected cells into main rows and cost element rows.

        Credit turnover is not attributable to a cost element on its own - the
        write-off of finished goods does not know which part of it was cement
        and which was wages. It is therefore spread over the elements in
        proportion to their debit turnover of the same period, which is what the
        paper statement does. A row with no debit turnover keeps its credit on
        the main row alone.
        """
        self.ensure_one()
        currency = self.currency_id
        use_elements = self.type_id.use_cost_elements
        groups = set(key[:2] for key in debit_cells)
        groups |= set(credit_cells)
        groups |= set(openings)

        records = self._dimension_records(
            dimension for _account_id, dimension in groups)
        names = {key: record.display_name for key, record in records.items()}

        rows = []
        # Unassigned turnover goes last: it is the remainder of the statement,
        # not one of its rows.
        for account_id, dimension in sorted(
                groups,
                key=lambda key: (codes.get(key[0], ''), not key[1],
                                 names.get(key[1], ''), key[1] or ('', 0))):
            element_debits = {
                element: sum(cells.values())
                for (line_account, line_dimension, element), cells
                in debit_cells.items()
                if (line_account, line_dimension) == (account_id, dimension)
            }
            debit_total = sum(element_debits.values())
            group_debit = defaultdict(float)
            for (line_account, line_dimension, _element), cells in \
                    debit_cells.items():
                if (line_account, line_dimension) != (account_id, dimension):
                    continue
                for column_id, amount in cells.items():
                    group_debit[column_id] += amount
            group_credit = credit_cells.get((account_id, dimension), {})
            opening = openings.get((account_id, dimension), 0.0)

            if self.type_id.skip_empty_rows and currency.is_zero(opening) and \
                    currency.is_zero(debit_total) and \
                    currency.is_zero(sum(group_credit.values())):
                continue

            record = records.get(dimension)
            rows.append((
                dict(self._dimension_values(record), **{
                    'line_type': 'group',
                    'account_id': account_id,
                    'opening_balance': opening,
                }),
                dict(group_debit), dict(group_credit)))

            if not use_elements:
                continue
            for element, element_debit in sorted(
                    element_debits.items(),
                    key=lambda item: ELEMENT_SEQUENCE.get(item[0], 99)):
                ratio = (element_debit / debit_total) if debit_total else 0.0
                rows.append((
                    dict(self._dimension_values(record), **{
                        'line_type': 'element',
                        'account_id': account_id,
                        'cost_element': element,
                        'responsible_name': False,
                    }),
                    dict(debit_cells[(account_id, dimension, element)]),
                    {column_id: amount * ratio
                     for column_id, amount in group_credit.items()}))

        lines = self.env['masb.account.turnover.line'].create([
            dict(values, sheet_id=self.id, sequence=index)
            for index, (values, _debit, _credit) in enumerate(rows, start=1)
        ])
        cells = []
        for line, (_values, debit, credit) in zip(lines, rows):
            cells += line._cell_values(debit, credit)
        self.env['masb.account.turnover.cell'].create(cells)

    def _dimension_values(self, record):
        """Line values describing the row value ``record`` (may be empty)."""
        if not record:
            return {'dimension_model': False, 'dimension_res_id': False,
                    'dimension_name': False}
        values = {
            'dimension_model': record._name,
            'dimension_res_id': record.id,
            'dimension_name': record.display_name,
        }
        if record._name == 'account.analytic.account':
            values['analytic_account_id'] = record.id
            values['responsible_name'] = (
                record.masb_responsible_id.name or False)
        elif record._name == 'res.partner':
            values['partner_id'] = record.id
        return values

    # ------------------------------------------------------------------
    # Drill-down
    # ------------------------------------------------------------------

    def action_open_entries(self, line_id, column_key):
        """Open the journal items behind one figure of the statement.

        The correspondence is rebuilt the same way the statement was built, and
        the journal items that fed the cell are collected by id. A domain on
        ``account.move.line`` could not express this on its own: which account
        a line corresponds to is not stored anywhere, it is derived from the
        other side of its entry.
        """
        self.ensure_one()
        line = self.env['masb.account.turnover.line'].browse(line_id).exists()
        if not line or line.sheet_id != self:
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
                'proportion to their debit turnover. Open the main row '
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

        layout = self.env['masb.account.turnover.column']._layout(
            self.type_id, self.company_id, column['block'])
        # An empty recordset stands for the catch-all "Other" column, so it has
        # to be built empty rather than browsed: ``browse(False)`` would hand
        # back a placeholder record that equals nothing.
        Column = self.env['masb.account.turnover.column']
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
        return line._dimension_key() in shares

    def action_open_pivot(self):
        """Open the cells in the standard pivot view.

        The widget on the form draws the statement as the accountant signs it;
        the pivot is for the questions the blank does not answer - one row
        across cost elements, one column across rows. Both read the same cells,
        so the figures cannot disagree.

        Main rows are preselected: the element rows below them break the very
        same turnover down, and summing both would double every figure.
        """
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': self.name,
            'res_model': 'masb.account.turnover.cell',
            'view_mode': 'pivot,list',
            'domain': [('sheet_id', '=', self.id)],
            'context': {
                'create': False,
                'search_default_group_rows': 1,
                'pivot_row_groupby': ['dimension_name'],
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

    def _balance_columns(self, role):
        """Grid columns of the opening or the closing balance.

        One signed column, or one column per side - see ``balance_layout`` on
        the statement type.
        """
        self.ensure_one()
        common = {'numeric': True, 'role': role, 'block': False,
                  'column_id': False}
        if self.type_id.balance_layout == 'expanded':
            labels = {
                'opening': (_('Opening balance, debit'),
                            _('Opening balance, credit')),
                'closing': (_('Closing balance, debit'),
                            _('Closing balance, credit')),
            }[role]
            return [
                dict(common, key='%s_debit' % role, label=labels[0]),
                dict(common, key='%s_credit' % role, label=labels[1]),
            ]
        label = {'opening': _('Opening balance'),
                 'closing': _('Closing balance')}[role]
        return [dict(common, key=role, label=label)]

    def _balance_values(self, balance):
        """A signed balance as the cells of ``_balance_columns``."""
        self.ensure_one()
        if self.type_id.balance_layout == 'expanded':
            return list(
                self.env['masb.account.turnover.line']._split_balance(balance))
        return [balance]

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
            {'key': 'label', 'label': self.type_id.row_label or _('Row'),
             'numeric': False, 'role': 'text'},
        ]
        columns += self._balance_columns('opening')
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
        columns += self._balance_columns('closing')

        rows = []
        for row in matrix['rows']:
            rows.append({
                'kind': ('total' if row['is_total']
                         else 'group' if row['is_group'] else 'element'),
                'line_id': row['line'].id,
                'cells': (
                    [row['account_code'], row['label']] + row['opening']
                    + row['debit'] + [row['turnover_debit']]
                    + row['credit'] + [row['turnover_credit']]
                    + row['closing']),
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
        Column = self.env['masb.account.turnover.column']
        cells = self.line_ids.cell_ids
        used = set(cells.mapped('column_id').ids)
        return {
            block: {
                'columns': [
                    column for column in Column._layout(
                        self.type_id, self.company_id, block)
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
            self.env['masb.account.turnover.line']._fields['cost_element']
            ._description_selection(self.env))
        rows = []
        for line in self.line_ids.sorted('sequence'):
            amounts = defaultdict(float)
            for cell in line.cell_ids:
                amounts[(cell.column_id.id, cell.block)] = cell.amount
            is_group = line.line_type == 'group'
            label = line._row_label() if is_group \
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
                'opening': self._balance_values(line.opening_balance),
                'closing': self._balance_values(line.closing_balance),
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

        Only main rows are summed: the element rows below them break the very
        same turnover down, so adding both would double every figure. Balances
        are summed cell by cell, so with debit and credit columns the total
        keeps the debit and the credit balances apart instead of netting them.
        """
        self.ensure_one()
        groups = [row for row in rows if row['is_group']]
        width = {block: len(layout[block]['columns'])
                 + (1 if layout[block]['other'] else 0)
                 for block in ('debit', 'credit')}

        def column_sums(key, size):
            return [sum(row[key][index] for row in groups)
                    for index in range(size)]

        balance_width = len(self._balance_values(0.0))
        return {
            'line': self.env['masb.account.turnover.line'],
            'is_group': False,
            'is_total': True,
            'label': _('TOTAL'),
            'account_code': '',
            'opening': column_sums('opening', balance_width),
            'closing': column_sums('closing', balance_width),
            'turnover_debit': sum(row['turnover_debit'] for row in groups),
            'turnover_credit': sum(row['turnover_credit'] for row in groups),
            'debit': column_sums('debit', width['debit']),
            'credit': column_sums('credit', width['credit']),
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
        self.xlsx_filename = '%s.xlsx' % (self.name or 'account-turnover')
        return {
            'type': 'ir.actions.act_url',
            'url': '/web/content/%s/%s/xlsx_file/%s?download=true' % (
                self._name, self.id, quote(self.xlsx_filename)),
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
        import xlsxwriter

        self.ensure_one()
        grid = self._report_grid()
        stream = io.BytesIO()
        workbook = xlsxwriter.Workbook(stream, {'in_memory': True})
        sheet_name = SHEET_NAME_FORBIDDEN.sub(' ', self.type_id.name or '')
        sheet = workbook.add_worksheet(sheet_name.strip()[:31] or None)
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
