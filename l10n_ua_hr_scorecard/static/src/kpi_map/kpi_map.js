import { Component, onWillStart, onWillUpdateProps, useRef, useState, useSubEnv } from "@odoo/owl";
import { DropdownItem } from "@web/core/dropdown/dropdown_item";
import { _t } from "@web/core/l10n/translation";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { STATIC_ACTIONS_GROUP_NUMBER } from "@web/search/action_menus/action_menus";
import { CogMenu } from "@web/search/cog_menu/cog_menu";
import { Layout } from "@web/search/layout";
import { formatFloat } from "@web/views/fields/formatters";
import { refreshSearchPanel } from "../views/search_panel_refresh";

/**
 * KPI Map: every employee with the KPIs of the job positions they held in the
 * periods matching the search (search panel included). Periods are columns
 * with weight, planned, actual and achievement; the employee cell spans all
 * their rows and the job position cell spans its KPIs and weighted result.
 *
 * Registered as a "list" view on hr.kpi.target so that it gets the control
 * panel and the search panel of the KPI targets search view.
 */
export class KpiMapController extends Component {
    static template = "l10n_ua_hr_scorecard.KpiMap";
    static components = { Layout, CogMenu };
    static props = ["*"];

    setup() {
        // Standard items of the cog menu for list views (e.g. "Export All")
        // read the selection of the view model; this view has no records.
        useSubEnv({ model: { root: { selection: [] } } });
        this.orm = useService("orm");
        this.action = useService("action");
        this.printableRef = useRef("printable");
        useSubEnv({ kpiMapPrint: () => this.print() });
        this.state = useState({ loading: true, periods: [], employees: [] });
        // Coming back through the breadcrumbs restores the search panel as it
        // was: its counters may be stale if targets were edited meanwhile.
        this.skipNextLoad = false;
        onWillStart(async () => {
            await this.load(this.props.domain);
            if (this.props.globalState) {
                refreshSearchPanel(this.env.searchModel, () => {
                    this.skipNextLoad = true;
                });
            }
        });
        onWillUpdateProps(async (nextProps) => {
            if (this.skipNextLoad) {
                this.skipNextLoad = false;
                return;
            }
            await this.load(nextProps.domain);
        });
    }

    async load(domain) {
        this.state.loading = true;
        const data = await this.orm.call("hr.kpi.map", "get_map_data", [domain]);
        this.state.periods = data.periods;
        this.state.employees = data.employees;
        this.state.loading = false;
    }

    /**
     * Flatten employees > job positions > KPIs into table rows; each job
     * position ends with its weighted result row. Periods are columns.
     */
    get rows() {
        const rows = [];
        for (const employee of this.state.employees) {
            employee.jobs.forEach((job, jobIndex) => {
                const jobRowCount = job.kpis.length + 1;
                job.kpis.forEach((kpi, kpiIndex) => {
                    rows.push({
                        key: `${employee.id}-${job.key}-${kpi.id}`,
                        type: "kpi",
                        employee: jobIndex === 0 && kpiIndex === 0 ? employee : null,
                        job: kpiIndex === 0 ? job : null,
                        jobRowCount,
                        kpi,
                    });
                });
                rows.push({
                    key: `${employee.id}-${job.key}-total`,
                    type: "total",
                    employee: jobIndex === 0 && !job.kpis.length ? employee : null,
                    job,
                });
            });
        }
        return rows;
    }

    /**
     * Row classes drawing the line hierarchy of the table: a strong line
     * before each employee, a medium one before each further job position of
     * the same employee, and a line above each weighted result.
     */
    rowClass(row) {
        const classes = [];
        if (row.employee) {
            classes.push("o_kpi_map_employee_start");
        } else if (row.type === "kpi" && row.job) {
            classes.push("o_kpi_map_job_start");
        }
        if (row.type === "total") {
            classes.push("o_kpi_map_total");
        }
        return classes.join(" ");
    }

    cell(kpi, period) {
        return kpi.cells[String(period.id)];
    }

    total(job, period) {
        return job.totals[String(period.id)];
    }

    /**
     * Print the title and the table only. Rather than hiding every part of the
     * web client around them, a copy of the table is put in a container of its
     * own at the end of the body and the print stylesheet hides its siblings:
     * what the page looks like then does not depend on the web client markup.
     */
    print() {
        const printable = this.printableRef.el;
        if (!printable) {
            return;
        }
        const root = document.createElement("div");
        root.className = "o_kpi_map_print_root";
        const title = document.createElement("h4");
        title.textContent = this.printTitle;
        root.append(title, printable.cloneNode(true));
        document.body.append(root);
        document.body.classList.add(PRINTING_CLASS);
        const cleanUp = () => {
            document.body.classList.remove(PRINTING_CLASS);
            root.remove();
            window.removeEventListener("afterprint", cleanUp);
        };
        window.addEventListener("afterprint", cleanUp);
        window.print();
        // Browsers that print synchronously never fire "afterprint" late.
        setTimeout(cleanUp);
    }

    get printTitle() {
        const periods = this.state.periods.map((period) => period.name).join(", ");
        return periods ? `${_t("KPI Map")}: ${periods}` : _t("KPI Map");
    }

    formatNumber(value) {
        // The map gives the overall picture: whole numbers are enough.
        return formatFloat(value, { digits: [16, 0] });
    }

    achievementClass(value) {
        if (value >= 100) {
            return "text-success";
        }
        return value > 0 ? "text-warning" : "text-danger";
    }

    partialTitle(total) {
        return _t("In the position %(days)s of %(period_days)s days of the period", {
            days: total.days,
            period_days: total.period_days,
        });
    }

    openTarget(cell) {
        this.action.doAction({
            type: "ir.actions.act_window",
            res_model: "hr.kpi.target",
            res_id: cell.target_id,
            views: [[false, "form"]],
            target: "current",
        });
    }
}

const KPI_MAP_JS_CLASS = "l10n_ua_hr_scorecard_kpi_map";
const PRINTING_CLASS = "o_kpi_map_printing";

/**
 * "Print" item of the cog menu of the KPI map. While printing, a class on the
 * body lets the print stylesheet keep only the table on paper.
 */
export class KpiMapPrintItem extends Component {
    static template = "l10n_ua_hr_scorecard.KpiMapPrintItem";
    static components = { DropdownItem };
    static props = {};

    onPrint() {
        this.env.kpiMapPrint();
    }
}

registry.category("cogMenu").add(
    "l10n_ua_hr_scorecard.kpi_map_print",
    {
        Component: KpiMapPrintItem,
        groupNumber: STATIC_ACTIONS_GROUP_NUMBER,
        isDisplayed: ({ config }) => config.viewArch?.getAttribute("js_class") === KPI_MAP_JS_CLASS,
    },
    { sequence: 5 }
);

registry.category("views").add(KPI_MAP_JS_CLASS, {
    type: "list",
    Controller: KpiMapController,
    searchMenuTypes: ["filter", "groupBy", "favorite"],
});
