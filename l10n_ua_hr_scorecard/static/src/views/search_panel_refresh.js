import { onWillUpdateProps } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { KanbanController } from "@web/views/kanban/kanban_controller";
import { kanbanView } from "@web/views/kanban/kanban_view";
import { ListController } from "@web/views/list/list_controller";
import { listView } from "@web/views/list/list_view";

/**
 * The search panel only refetches its sections when the search changes, and
 * restores them as they were when coming back through the breadcrumbs. Its
 * counters and computed values (e.g. employees) therefore go stale after the
 * records themselves are edited or confirmed.
 *
 * These controllers refetch the sections whenever the records are reloaded
 * for another reason than a search update: an action button, a dialog being
 * closed, or a return from the form view.
 */
function sectionsSnapshot(searchModel) {
    return JSON.stringify(
        searchModel.getSections().map((section) => [
            section.id,
            [...(section.values?.values() || [])].map((value) => [
                value.id,
                value.display_name,
                value.__count,
            ]),
        ])
    );
}

function setupSearchPanelRefresh(controller) {
    // A props update means the search changed: the search model has already
    // refetched the sections. Only a restored controller (breadcrumbs) starts
    // with stale sections.
    controller.skipSearchPanelRefresh = !controller.props.state;
    onWillUpdateProps(() => {
        controller.skipSearchPanelRefresh = true;
    });
}

/**
 * Refetch the search panel sections and re-render the panel when they
 * changed. `beforeUpdate` runs right before the re-render, which updates the
 * props of the view: callers use it to ignore that update.
 */
export async function refreshSearchPanel(searchModel, beforeUpdate = () => {}) {
    if (!searchModel?.display?.searchPanel || !searchModel.getSections().length) {
        return;
    }
    const before = sectionsSnapshot(searchModel);
    searchModel.sectionsPromise = searchModel._fetchSections(
        searchModel.categories,
        searchModel.filters
    );
    await searchModel.sectionsPromise;
    if (sectionsSnapshot(searchModel) !== before) {
        beforeUpdate();
        searchModel._reset();
        searchModel.trigger("update");
    }
}

function withSearchPanelRefresh(controller, modelParams) {
    const onRootLoaded = modelParams.hooks.onRootLoaded;
    modelParams.hooks.onRootLoaded = async (...args) => {
        if (onRootLoaded) {
            await onRootLoaded(...args);
        }
        if (controller.skipSearchPanelRefresh) {
            controller.skipSearchPanelRefresh = false;
            return;
        }
        await refreshSearchPanel(controller.env.searchModel, () => {
            controller.skipSearchPanelRefresh = true;
        });
    };
    return modelParams;
}

export class SearchPanelRefreshListController extends ListController {
    setup() {
        super.setup();
        setupSearchPanelRefresh(this);
    }

    get modelParams() {
        return withSearchPanelRefresh(this, super.modelParams);
    }
}

export class SearchPanelRefreshKanbanController extends KanbanController {
    setup() {
        super.setup();
        setupSearchPanelRefresh(this);
    }

    get modelParams() {
        return withSearchPanelRefresh(this, super.modelParams);
    }
}

registry.category("views").add("l10n_ua_hr_scorecard_search_panel_refresh_list", {
    ...listView,
    Controller: SearchPanelRefreshListController,
});

registry.category("views").add("l10n_ua_hr_scorecard_search_panel_refresh_kanban", {
    ...kanbanView,
    Controller: SearchPanelRefreshKanbanController,
});
