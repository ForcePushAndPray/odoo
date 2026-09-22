/**
 * The statement as a table, drawn by the form itself.
 *
 * Data comes from ``get_matrix`` on the server rather than from the one2many
 * loaded into the form: the statement is a grid of a few dozen columns by a few
 * dozen rows, and rebuilding it in the browser out of cell records would mean
 * pulling the whole report into the client just to draw a table the server has
 * already assembled.
 *
 * The very same structure feeds the printed form and the spreadsheet, so what
 * is on screen is what comes out of the printer.
 */
import { registry } from "@web/core/registry";
import { standardWidgetProps } from "@web/views/widgets/standard_widget_props";
import { useService } from "@web/core/utils/hooks";
import { formatMonetary } from "@web/views/fields/formatters";
import { _t } from "@web/core/l10n/translation";
import { Component, onWillStart, onWillUpdateProps, useState } from "@odoo/owl";

export class AccountTurnoverMatrix extends Component {
    static props = standardWidgetProps;
    static template = "l10n_ua_masb_account_turnover.AccountTurnoverMatrix";

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.state = useState({ grid: null, loading: false });
        onWillStart(() => this.load(this.props));
        onWillUpdateProps((nextProps) => this.load(nextProps));
    }

    async load(props) {
        const record = props.record;
        const resId = record.resId;
        if (!resId) {
            this.state.grid = null;
            return;
        }
        // Reload key: the statement, the width switch and the totals. The
        // totals change exactly when the cells were recomputed, so they are
        // what tells that the drawn table is stale.
        const key = [
            resId,
            record.data.show_all_columns,
            record.data.total_debit,
            record.data.total_credit,
        ].join("/");
        if (key === this.loadedKey) {
            return;
        }
        this.loadedKey = key;
        this.state.loading = true;
        try {
            this.state.grid = await this.orm.call(
                record.resModel,
                "get_matrix",
                [[resId]]
            );
        } finally {
            this.state.loading = false;
        }
    }

    get grid() {
        return this.state.grid;
    }

    get isEmpty() {
        return !this.grid || !this.grid.rows.length;
    }

    get loadingLabel() {
        return _t("Computing…");
    }

    get drillTitle() {
        return _t("Open the journal items behind this figure");
    }

    get emptyLabel() {
        return _t("The statement is empty. Set the period and press Compute.");
    }

    format(value, column) {
        if (!column.numeric) {
            return value || "";
        }
        if (value === undefined || value === null) {
            return "";
        }
        // No currency symbol: in a dense grid it would repeat in every cell,
        // and the currency is named on the form itself.
        return formatMonetary(value, {
            currencyId: this.grid.currency_id,
            noSymbol: true,
        });
    }

    /**
     * A figure can be opened when journal items actually stand behind it.
     *
     * The closing balance is arithmetic over two other figures, and a credit
     * amount on a cost element row is the write-off spread over the elements -
     * neither is a set of entries. An empty cell has nothing to show either.
     */
    isDrillable(row, column, value) {
        if (!row.line_id || !value) {
            return false;
        }
        if (!["column", "total", "opening"].includes(column.role)) {
            return false;
        }
        return !(column.block === "credit" && row.kind === "element");
    }

    async onCellClick(row, column, value) {
        if (!this.isDrillable(row, column, value)) {
            return;
        }
        const action = await this.orm.call(
            this.props.record.resModel,
            "action_open_entries",
            [[this.props.record.resId], row.line_id, column.key]
        );
        this.action.doAction(action);
    }

    rowClass(row) {
        // Every row is a data row of a list first; the two heavier kinds only
        // add their own weight on top of it.
        const classes = ["o_data_row"];
        if (row.kind === "total") {
            classes.push("o_masb_turnover_total");
        } else if (row.kind === "group") {
            classes.push("o_masb_turnover_group");
        }
        return classes.join(" ");
    }

    cellClass(row, column, index, value) {
        const classes = ["o_data_cell"];
        if (column.numeric) {
            classes.push("o_list_number");
        }
        if (row.kind === "element" && index === 1) {
            classes.push("o_masb_turnover_indent");
        }
        if (this.isDrillable(row, column, value)) {
            classes.push("o_masb_turnover_drillable");
        }
        return classes.join(" ");
    }
}

export const accountTurnoverMatrix = { component: AccountTurnoverMatrix };

registry.category("view_widgets").add("masb_account_turnover_matrix", accountTurnoverMatrix);
