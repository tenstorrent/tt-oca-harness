// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

// Renders the verification dashboard and its per-block drill-down pages from
// the DV data staged into the site at deploy time.
(function () {
  'use strict';

  // Generate the headings rather than defining literally in the html
  var SUMMARY_HEADINGS = [
    'Block',
    'Tests',
    'Passing',
    'Code Coverage',
    'Branch Coverage',
    'Expression Coverage',
    'User Coverage',
  ];
  var TEST_HEADINGS = ['Test', 'Category', 'Seed', 'Status', 'Duration'];

  // Files baked in during build, or public URLs
  var SUMMARY_URL = './data/summary.json';
  var TESTS_URL = './data/tests.json';

  // Bands shared by pass rate and every coverage column.
  var PASS_AT = 95;
  var WARN_AT = 70;

  // Columns mapped from tools/dv/runlib/coverage_model.py CLOSURE_METRICS.
  var COVERAGE_COLUMNS = ['line', 'branch', 'expression', 'user'];

  // Match to dut_status[] flows
  var CHIP_ROWS = ['chip_ocah'];
  var BLOCK_ROWS = ['dtp', 'sep', 'smc', 'aou'];
  var LINKABLE_ROWS = CHIP_ROWS.concat(BLOCK_ROWS);

  /**
   * Return the CSS style given a pass percentage.
   * @param {?number} value Percentage between 0 and 100, or null when unmeasured.
   * @return {string} The className, or an empty string if no valid value given.
   */
  function band(value) {
    if (value === null || value === undefined) return '';
    if (value >= PASS_AT) return 'dash-pass';
    if (value >= WARN_AT) return 'dash-warn';
    return 'dash-fail';
  }

  /**
   * Round a given number to 1 decimal place. Makes cells easier to parse.
   * @param {?number} value Decimal number to round.
   * @return {?number} Rounded value, or null if no valid value given.
   */
  function round1(value) {
    if (value === null || value === undefined) return null;
    return Math.round(value * 10) / 10;
  }

  /**
   * Produce and append a table cell.
   * @param {!HTMLTableRowElement} row The table row to append the new cell to.
   * @param {string} text The text to insert into the new cell.
   * @param {string=} className Optional CSS class to apply to the cell.
   */
  function cell(row, text, className) {
    var td = document.createElement('td');
    td.textContent = text;
    if (className) td.className = className;
    row.appendChild(td);
  }

  /**
   * Produce a cell with a rounded percentage and appropriate colour coding.
   * @param {!HTMLTableRowElement} row The row to append the cell to.
   * @param {?number} value The cell's percentage value, or null when unmeasured.
   */
  function metricCell(row, value) {
    var pct = round1(value);
    // An unmeasured metric is not a failing one, so it stays uncoloured.
    if (pct === null) {
      cell(row, 'n/a', 'dashboard-na');
      return;
    }
    cell(row, pct + ' %', band(pct));
  }

  /**
   * Format a date as a minute-resolution UTC stamp, e.g. "2026-08-31 20:11 UTC".
   * @param {!Date} date The date to format.
   * @return {string} The formatted stamp.
   */
  function utcStamp(date) {
    return date.toISOString().replace('T', ' ').slice(0, 16) + ' UTC';
  }

  /**
   * Generate a table header from a list of headings.
   * @param {?HTMLTableSectionElement} thead Table header to fill in; ignored when absent.
   * @param {!Array<string>} headings List of headings to use.
   */
  function fillHead(thead, headings) {
    if (!thead) return;
    var row = document.createElement('tr');
    headings.forEach(function (label) {
      var th = document.createElement('th');
      th.textContent = label;
      th.scope = 'col';
      row.appendChild(th);
    });
    thead.appendChild(row);
  }

  /**
   * Produce a coverage object containing coverage data per flow.
   * @param {!Object} summary Parsed summary.json.
   * @return {!Object} Coverage entries keyed by flow name.
   */
  function coverageByFlow(summary) {
    var coverage = Object.create(null);
    (summary.results || []).forEach(function (result) {
      if (result && result.flow) coverage[result.flow] = result.coverage;
    });
    return coverage;
  }

  /**
   * Bind an error reporter to a status element, so both pages report failures
   * the same way.
   * @param {!HTMLElement} statusEl The element to write the error message to.
   * @return {function(string)} A function which writes a given reason to statusEl.
   */
  function failWith(statusEl) {
    return function (reason) {
      statusEl.className = 'dashboard-status dashboard-status-error';
      statusEl.textContent = 'Dashboard data unavailable: ' + reason + '.';
    };
  }

  /**
   * Fetch the summary or per-test JSON file.
   * @param {string} url The URL of the JSON file to fetch.
   * @return {!Promise<!Object>} Resolves to the parsed JSON; rejects on a non-2xx response.
   */
  function fetchJson(url) {
    return fetch(url, { cache: 'no-cache' }).then(function (response) {
      if (!response.ok) throw new Error('HTTP ' + response.status);
      return response.json();
    });
  }

  /**
   * Build one row of a summary table: the block name followed by the columns
   * named in SUMMARY_HEADINGS. Both the overview tables and the single-row
   * table on a block page use this, so the two cannot drift apart.
   * @param {string} name Block name rendered in the first cell.
   * @param {?Object} dut The block's dut_status entry, or undefined when the
   *     published data has none; every metric then reads n/a.
   * @param {?Object} coverage The block's results[].coverage entry, if any.
   * @param {boolean} linked Render the name as a link to its block page.
   * @return {!HTMLTableRowElement} The populated row.
   */
  function summaryRow(name, dut, coverage, linked) {
    var row = document.createElement('tr');
    var td = document.createElement('td');

    if (linked && dut && LINKABLE_ROWS.indexOf(name) !== -1) {
      var url = new URL('dashboard-block.html', window.location.href);
      url.searchParams.set('flow', name);
      var link = document.createElement('a');
      link.href = url.href;
      link.textContent = name;
      td.appendChild(link);
    } else {
      td.textContent = name;
    }
    row.appendChild(td);

    if (!dut) {
      for (var i = 1; i < SUMMARY_HEADINGS.length; i++) {
        cell(row, 'n/a', 'dashboard-na');
      }
      return row;
    }

    cell(row, String(dut.tests_total));
    metricCell(row, dut.pass_rate);

    var metrics = (coverage && coverage.effective_metrics) || {};
    COVERAGE_COLUMNS.forEach(function (family) {
      metricCell(row, metrics[family]);
    });

    return row;
  }

  /**
   * Render the overview dashboard split into chip and block tables, with a
   * timestamp of when the data was published.
   * @param {!HTMLElement} statusEl Element carrying the timestamp, or the
   *     reason the tables are empty.
   * @param {!HTMLTableSectionElement} chipRowsEl Body of the chip-level table.
   * @param {!HTMLTableSectionElement} blockRowsEl Body of the block-level table.
   */
  function renderDashboard(statusEl, chipRowsEl, blockRowsEl) {
    var fail = failWith(statusEl);

    fillHead(document.getElementById('dashboard-chip-head'), SUMMARY_HEADINGS);
    fillHead(document.getElementById('dashboard-block-head'), SUMMARY_HEADINGS);

    fetchJson(SUMMARY_URL)
      .then(function (summary) {
        var duts = Object.create(null);
        (summary.dut_status || []).forEach(function (dut) {
          duts[dut.flow] = dut;
        });

        var coverage = coverageByFlow(summary);

        CHIP_ROWS.forEach(function (name) {
          chipRowsEl.appendChild(summaryRow(name, duts[name], coverage[name], true));
        });
        BLOCK_ROWS.forEach(function (name) {
          blockRowsEl.appendChild(summaryRow(name, duts[name], coverage[name], true));
        });

        statusEl.className = 'dashboard-status';
        statusEl.textContent = 'Data as of ' + utcStamp(new Date(summary.generated_at));
      })
      .catch(function (error) {
        fail(error.message);
      });
  }

  /**
   * Render one block's page: its summary row plus a table of every test in the
   * published run. The block is chosen by the `flow` query parameter.
   * @param {!HTMLElement} statusEl Element carrying the timestamp, or the
   *     reason the page is empty.
   * @param {!HTMLElement} nameEl Heading naming the block.
   * @param {!HTMLElement} summaryEl Wrapper around the summary table, hidden
   *     until the block is found.
   * @param {!HTMLElement} testsEl Wrapper around the tests table, hidden until
   *     per-test detail is available.
   * @param {!HTMLTableSectionElement} rowEl Body of the summary table.
   * @param {!HTMLTableSectionElement} testRowsEl Body of the tests table.
   */
  function renderBlock(statusEl, nameEl, summaryEl, testsEl, rowEl, testRowsEl) {
    var fail = failWith(statusEl);
    var flow = new URLSearchParams(window.location.search).get('flow') || '';

    /**
     * Round, and format seconds to more readable format.
     * @param {?number} seconds Total duration in seconds.
     * @return {string} Formatted duration, or an em dash when unknown.
     */
    function duration(seconds) {
      if (seconds === null || seconds === undefined) return '—';
      if (seconds < 60) return Math.round(seconds) + ' s';
      return Math.floor(seconds / 60) + ' m ' + Math.round(seconds % 60) + ' s';
    }

    /**
     * Render the same row the overview shows for this block, unlinked because
     * the link would point at this page.
     * @param {!Object} summary Parsed summary.json.
     * @return {boolean} True when the block was found and its row rendered.
     */
    function renderSummary(summary) {
      var dut = (summary.dut_status || []).filter(function (entry) {
        return entry.flow === flow;
      })[0];
      if (!dut) return false;

      rowEl.appendChild(summaryRow(dut.flow, dut, coverageByFlow(summary)[flow], false));
      summaryEl.hidden = false;

      statusEl.textContent = 'Data as of ' + utcStamp(new Date(summary.generated_at));
      return true;
    }

    /**
     * Render the per-block drill-down table containing each individual test.
     * @param {!Object} detail Parsed tests.json.
     */
    function renderTests(detail) {
      var flows = detail.flows || {};
      var tests = Object.prototype.hasOwnProperty.call(flows, flow) ? flows[flow] : [];
      if (!tests.length) return;

      // failures first, then sort by slowest
      tests
        .slice()
        .sort(function (a, b) {
          var aFail = a.status !== 'PASS',
            bFail = b.status !== 'PASS';
          if (aFail !== bFail) return aFail ? -1 : 1;
          return (b.duration_sec || 0) - (a.duration_sec || 0);
        })
        .forEach(function (test) {
          var row = document.createElement('tr');
          cell(row, test.name);
          cell(row, test.category || '—');
          cell(row, test.seed === undefined ? '—' : String(test.seed));
          cell(row, test.status, test.status === 'PASS' ? 'dash-pass' : 'dash-fail');
          cell(row, duration(test.duration_sec));
          testRowsEl.appendChild(row);
        });

      testsEl.hidden = false;
    }

    fillHead(document.getElementById('dashboard-block-summary-head'), SUMMARY_HEADINGS);
    fillHead(document.getElementById('dashboard-test-head'), TEST_HEADINGS);

    if (!flow) {
      fail('no block selected; reach this page from the verification dashboard');
      return;
    }
    nameEl.textContent = flow;
    document.title = flow + ' — Block Verification Detail';

    fetchJson(SUMMARY_URL)
      .then(function (summary) {
        if (!renderSummary(summary)) {
          fail('the published data contains no flow named "' + flow + '"');
          return null;
        }
        return fetch(TESTS_URL, { cache: 'no-cache' })
          .then(function (response) {
            return response.ok ? response.json() : null;
          })
          .then(function (detail) {
            if (detail) renderTests(detail);
          });
      })
      .catch(function (error) {
        fail(error.message);
      });
  }

  // Both pages share this script, and it is loaded only by them; the element
  // lookups below decide which renderer runs.
  var statusEl = document.getElementById('dashboard-status');
  if (!statusEl) return;

  var chipRowsEl = document.getElementById('dashboard-chip-rows');
  var blockRowsEl = document.getElementById('dashboard-block-rows');
  if (chipRowsEl && blockRowsEl) {
    renderDashboard(statusEl, chipRowsEl, blockRowsEl);
    return;
  }

  var rowEl = document.getElementById('dashboard-block-row');
  if (rowEl) {
    renderBlock(
      statusEl,
      document.getElementById('dashboard-block-name'),
      document.getElementById('dashboard-block-summary'),
      document.getElementById('dashboard-block-tests'),
      rowEl,
      document.getElementById('dashboard-test-rows')
    );
  }
})();
