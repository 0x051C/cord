// Turns <div data-grid ...> elements into Tabulator grids, on page load and after every htmx swap.
//   data-url                  JSON endpoint
//   data-columns              Tabulator column definitions (JSON)
//   data-remote               paginate / sort / filter on the server ({last_page, last_row, data})
//   data-row-link             navigate on row click, "{id}" is replaced by the row id
//   data-row-detail           htmx GET on row click ("{id}" replaced) ...
//   data-row-detail-target    ... swapped into this selector
(function () {
  "use strict";

  function withId(template, row) {
    return template.replace("{id}", encodeURIComponent(row.getData().id));
  }

  function initGrid(el) {
    if (el._grid) return;
    var remote = "remote" in el.dataset;
    var options = {
      ajaxURL: el.dataset.url,
      columns: JSON.parse(el.dataset.columns),
      layout: "fitDataStretch",
      height: el.dataset.height || "62vh",
      placeholder: "No data",
      movableColumns: true,
      pagination: true,
      paginationSize: 50,
      paginationSizeSelector: [25, 50, 100, 250],
      paginationCounter: "rows",
      columnDefaults: { headerFilterPlaceholder: "filter…", tooltip: true },
    };
    if (remote) {
      options.paginationMode = "remote";
      options.sortMode = "remote";
      options.filterMode = "remote";
    }
    if (el.dataset.rowDetail) options.selectableRows = 1;
    var table = new Tabulator(el, options);

    if (el.dataset.rowLink) {
      table.on("rowClick", function (e, row) {
        window.location.href = withId(el.dataset.rowLink, row);
      });
    }
    if (el.dataset.rowDetail) {
      table.on("rowClick", function (e, row) {
        htmx.ajax("GET", withId(el.dataset.rowDetail, row), { target: el.dataset.rowDetailTarget, swap: "innerHTML" });
      });
    }
    el._grid = table;
  }

  htmx.onLoad(function (root) {
    if (root.matches && root.matches("[data-grid]")) initGrid(root);
    root.querySelectorAll && root.querySelectorAll("[data-grid]").forEach(initGrid);
  });
})();
