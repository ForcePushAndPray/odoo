import { Component, useRef } from "@odoo/owl";
import { _t } from "@web/core/l10n/translation";
import { registry } from "@web/core/registry";
import { standardFieldProps } from "@web/views/fields/standard_field_props";

/**
 * Formula of a KPI: a text input with buttons that insert the variable codes
 * of the KPI and the arithmetic operators at the cursor. The formula is
 * validated on the server (hr.kpi.formula_error).
 */
export class KpiFormulaField extends Component {
    static template = "l10n_ua_hr_scorecard.KpiFormulaField";
    static props = {
        ...standardFieldProps,
        variablesField: { type: String, optional: true },
        placeholder: { type: String, optional: true },
    };
    static defaultProps = {
        variablesField: "variable_ids",
    };

    setup() {
        this.inputRef = useRef("input");
        this.operators = ["+", "-", "*", "/", "(", ")"];
    }

    get value() {
        return this.props.record.data[this.props.name] || "";
    }

    get variables() {
        const list = this.props.record.data[this.props.variablesField];
        if (!list) {
            return [];
        }
        return list.records
            .map((record) => ({
                id: record.id,
                code: record.data.code,
                name: record.data.name || "",
            }))
            .filter((variable) => variable.code);
    }

    onChange(ev) {
        this.props.record.update({ [this.props.name]: ev.target.value });
    }

    async insert(token) {
        const input = this.inputRef.el;
        const value = input ? input.value : this.value;
        const start = input ? input.selectionStart : value.length;
        const end = input ? input.selectionEnd : value.length;
        const before = value.slice(0, start);
        const after = value.slice(end);
        const needsSpaceBefore = before && !before.endsWith(" ") && !before.endsWith("(");
        const needsSpaceAfter = after && !after.startsWith(" ") && !after.startsWith(")");
        const inserted = `${needsSpaceBefore ? " " : ""}${token}${needsSpaceAfter ? " " : ""}`;
        await this.props.record.update({ [this.props.name]: before + inserted + after });
        if (input) {
            const cursor = before.length + inserted.length;
            input.focus();
            input.setSelectionRange(cursor, cursor);
        }
    }

    variableTitle(variable) {
        return variable.name || _t("Variable %s", variable.code);
    }
}

registry.category("fields").add("kpi_formula", {
    component: KpiFormulaField,
    displayName: _t("KPI Formula"),
    supportedTypes: ["char"],
    extractProps: ({ options, placeholder }) => ({
        variablesField: options.variables_field,
        placeholder,
    }),
});
