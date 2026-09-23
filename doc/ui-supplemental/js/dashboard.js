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
  var HISTORY_URL = './data/history.json';
  var TEST_HISTORY_URL = './data/test-history.json';

  // Bands shared by pass rate and every coverage column.
  var PASS_AT = 95;
  var WARN_AT = 70;

  // Columns mapped from tools/dv/runlib/coverage_model.py CLOSURE_METRICS.
  var COVERAGE_COLUMNS = ['line', 'branch', 'expression', 'user'];

  var GRID_LINE = '#e6e6e6';

  // Chart text is drawn by ECharts, so it does not inherit the stylesheet's
  // link colour and has to be given one.
  var LINK_COLOUR = '#1565c0';

  // Where a cell's CI run is published.
  var RUN_URL = 'https://github.com/tenstorrent/tt-oca-harness/actions/runs/';

  // Per-test outcomes, in legend order.
  var HISTORY_STATES = ['passed', 'flaky', 'failed', 'did not run'];
  var HISTORY_COLOURS = {
    passed: '#3A863D',
    flaky: '#f6c343',
    failed: '#C55050',
    'did not run': '#e6e6e6',
  };

  // Match to dut_status[] flows
  var CHIP_ROWS = ['chip_ocah'];
  var BLOCK_ROWS = ['dtp', 'sep', 'smc', 'aou'];
  var LINKABLE_ROWS = CHIP_ROWS.concat(BLOCK_ROWS);

  /**
   * Read a value from the page theme.
   * @param {string} name CSS custom property, e.g. "--oca-text".
   * @param {string} fallback Value used when the property is unset.
   * @return {string} The resolved value.
   */
  function themeValue(name, fallback) {
    var value = getComputedStyle(document.documentElement).getPropertyValue(name);
    return value.trim() || fallback;
  }

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

    var historyEl = document.getElementById('dashboard-block-history');
    if (historyEl) {
      var historyUrl = new URL('dashboard-test-history.html', window.location.href);
      historyUrl.searchParams.set('flow', flow);
      var historyLink = document.createElement('a');
      historyLink.href = historyUrl.href;
      historyLink.textContent = 'Per-test history for ' + flow + ' \u2192';
      historyEl.appendChild(historyLink);
    }

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

  /**
   * Draw a line chart with ECharts, one series per named entry.
   * @param {!HTMLElement} host Element the chart replaces the contents of.
   * @param {!Array<string>} labels x-axis labels, one per point.
   * @param {!Array<{name: string, colour: string, values: !Array<?number>}>} series
   *     Series to plot; a null value breaks the line rather than plotting zero.
   * @param {number} max Upper bound of the y axis.
   * @param {string} unit Suffix shown on y-axis labels and in tooltips.
   */
  function lineChart(host, labels, series, max, unit) {
    // Changing the window redraws, and an instance outlives the nodes it drew,
    // so the old one is disposed before the host is cleared.
    var previous = echarts.getInstanceByDom(host);
    if (previous) previous.dispose();

    host.textContent = '';
    // ECharts sizes to its container, so the box needs a height of its own.
    host.style.height = '280px';

    // 'svg' rather than the default canvas renderer, so each mark is a DOM
    // node and the chart stays reachable by assistive technology.
    var chart = echarts.init(host, null, { renderer: 'svg' });

    chart.setOption({
      // Generates a screen-reader description of the chart from the series.
      aria: { enabled: true },
      animation: false,
      // ECharts styles its text inline, which a stylesheet cannot override,
      // so the theme is read here instead.
      textStyle: {
        fontFamily: themeValue('--oca-font-body', 'sans-serif'),
        color: themeValue('--oca-text', '#484848'),
        fontSize: 11,
      },
      legend: {
        bottom: 0,
        itemWidth: 12,
        itemHeight: 12,
        textStyle: { color: themeValue('--oca-text', '#484848'), fontSize: 11 },
      },
      // 'grid' is the plot rectangle, not the gridlines. These margins
      // reserve room around it for the axis labels and legend.
      grid: { left: 56, right: 20, top: 16, bottom: 56 },
      tooltip: {
        trigger: 'axis',
        backgroundColor: themeValue('--oca-cream-light', '#f8f4eb'),
        borderColor: themeValue('--oca-green', '#103525'),
        textStyle: {
          color: themeValue('--oca-text', '#484848'),
          fontFamily: themeValue('--oca-font-body', 'sans-serif'),
        },
      },
      // Ticks are labelled month-day. The full range is named in the status
      // line above the charts.
      xAxis: {
        type: 'category',
        // Without this a category axis leaves a gap at each end, holding
        // the first and last run away from the edges.
        boundaryGap: false,
        data: labels.map(function (label) {
          return label.slice(5);
        }),
        axisLine: { lineStyle: { color: GRID_LINE } },
        axisTick: { show: false },
        axisLabel: { color: themeValue('--oca-text', '#484848'), fontSize: 11 },
      },
      yAxis: {
        type: 'value',
        min: 0,
        max: max,
        axisLabel: {
          formatter: '{value}' + unit,
          color: themeValue('--oca-text', '#484848'),
          fontSize: 11,
        },
        axisLine: { show: false },
        // splitLine is ECharts' name for the gridlines across the plot.
        splitLine: { lineStyle: { color: GRID_LINE } },
      },
      series: series.map(function (s) {
        return {
          name: s.name,
          type: 'line',
          data: s.values,
          itemStyle: { color: s.colour },
          lineStyle: { width: 2 },
          symbolSize: 5,
          // A null value breaks the line rather than joining across it.
          connectNulls: false,
        };
      }),
    });

    if (window.ResizeObserver) {
      new ResizeObserver(function () {
        chart.resize();
      }).observe(host);
    }
  }

  /**
   * Render the trend charts from the published history.
   * @param {!HTMLElement} statusEl Element carrying the range, or the reason
   *     the charts are empty.
   * @param {!HTMLElement} trendsEl Wrapper revealed once the charts are drawn.
   * @param {!HTMLSelectElement} windowEl Control selecting how many runs to show.
   */
  function renderTrends(statusEl, trendsEl, windowEl) {
    var fail = failWith(statusEl);

    fetchJson(HISTORY_URL)
      .then(function (history) {
        var all = history.points || [];
        if (!all.length) {
          fail('the published history contains no points');
          return;
        }

        function draw() {
          // A hidden element has no size for the charts to measure, so the
          // wrapper is shown before they are drawn.
          trendsEl.hidden = false;
          var count = parseInt(windowEl.value, 10) || 0;
          var pts = count > 0 ? all.slice(-count) : all;
          var labels = pts.map(function (p) {
            return (p.generated_at || '').slice(0, 10);
          });

          lineChart(
            document.getElementById('dashboard-trend-tests'),
            labels,
            [
              {
                name: 'Test pass rate',
                colour: '#3A863D',
                values: pts.map(function (p) {
                  return round1(p.test_pass_rate);
                }),
              },
              {
                name: 'Flow pass rate',
                colour: '#C55050',
                values: pts.map(function (p) {
                  return round1(p.flow_pass_rate);
                }),
              },
            ],
            100,
            ' %'
          );

          var palette = ['#103525', '#F6931E', '#937027', '#3A863D', '#C55050', '#f6c343'];
          lineChart(
            document.getElementById('dashboard-trend-coverage'),
            labels,
            COVERAGE_COLUMNS.map(function (family, i) {
              return {
                name: family,
                colour: palette[i % palette.length],
                values: pts.map(function (p) {
                  var dut = (p.per_dut || [])[0] || {};
                  var metrics = dut.effective_metrics || {};
                  return round1(metrics[family]);
                }),
              };
            }),
            100,
            ' %'
          );

          var counts = pts.map(function (p) {
            return Math.max(p.failed_tests || 0, p.flaky_tests || 0);
          });
          lineChart(
            document.getElementById('dashboard-trend-failures'),
            labels,
            [
              {
                name: 'Failing',
                colour: '#C55050',
                values: pts.map(function (p) {
                  return p.failed_tests || 0;
                }),
              },
              {
                name: 'Flaky',
                colour: '#f6c343',
                values: pts.map(function (p) {
                  return p.flaky_tests || 0;
                }),
              },
            ],
            Math.max.apply(null, counts.concat([4])),
            ''
          );

          statusEl.className = 'dashboard-status';
          statusEl.textContent =
            pts.length + ' runs, ' + labels[0] + ' to ' + labels[labels.length - 1] + '.';
        }

        windowEl.addEventListener('change', draw);
        draw();
      })
      .catch(function (error) {
        fail(error.message);
      });
  }

  /**
   * Classify one aggregated cell.
   * @param {?{pass: number, total: number}} cell Seeds passed out of seeds
   *     run, or null when the test did not run.
   * @return {string} One of the status names used by the heatmap legend.
   */
  function historyState(cell) {
    if (!cell) return 'did not run';
    if (cell.pass === cell.total) return 'passed';
    return cell.pass === 0 ? 'failed' : 'flaky';
  }

  /**
   * A seed, as text.
   * @param {!{seed: ?number}} seed One entry from a cell's seeds.
   * @return {string} The seed, or an empty string when the run did not record one.
   */
  function seedOf(seed) {
    return seed.seed === null || seed.seed === undefined ? '' : String(seed.seed);
  }

  /**
   * Build the cell naming a run, linking to the CI run that produced it.
   * @param {!{date: string, id: string}} run The run the row describes.
   * @return {!HTMLTableCellElement} The populated cell.
   */
  function runCell(run) {
    var td = document.createElement('td');
    // Anything but a run identifier leaves the date as plain text.
    if (!/^[0-9]+$/.test(run.id || '')) {
      td.textContent = run.date;
      return td;
    }
    var link = document.createElement('a');
    link.href = RUN_URL + encodeURIComponent(run.id);
    link.textContent = run.date;
    link.rel = 'noreferrer';
    td.appendChild(link);
    return td;
  }

  /**
   * Build the cell showing how a run went, banded by the same colours as the
   * history grid.
   * @param {?{pass: number, total: number}} counts The cell, or null when the
   *     test did not run.
   * @param {string} state The cell's status name.
   * @return {!HTMLTableCellElement} The populated cell.
   */
  function outcomeCell(counts, state) {
    var td = document.createElement('td');
    td.className = 'dashboard-outcome';
    td.style.backgroundColor = HISTORY_COLOURS[state];
    td.textContent = counts ? round1((counts.pass / counts.total) * 100) + ' %' : state;
    return td;
  }

  /**
   * Add the seed and reason columns for one seed, or empty ones when the run
   * recorded none. A seed that passed leaves the reason blank.
   * @param {!HTMLTableRowElement} row Row to append the two cells to.
   * @param {?{seed: ?number, reason: (string|undefined)}} seed The seed, if any.
   */
  function seedCells(row, seed) {
    cell(row, seed ? seedOf(seed) : '');
    cell(row, (seed && seed.reason) || '', 'dashboard-detail-reason');
  }

  /**
   * Match a name asked for in the query string against the names the data
   * holds. Own keys only, so a built-in like "toString" matches nothing.
   * @param {!Object} owner Object whose keys are the names that exist.
   * @param {?string} requested Name taken from the query string.
   * @return {string} The matching name from the data, or an empty string when
   *     there is none.
   */
  function knownName(owner, requested) {
    var names = Object.keys(owner || {});
    var index = names.indexOf(requested || '');
    return index >= 0 ? names[index] : '';
  }

  /**
   * Fill in the back link, pointing at the given page for a block, or at the
   * dashboard when no block was resolved.
   * @param {?HTMLElement} backEl Paragraph holding the link, if the page has one.
   * @param {string} page Page to return to when a block was resolved.
   * @param {string} flow The resolved block, or an empty string.
   * @param {string} label What to call the destination in the link text.
   */
  function backTo(backEl, page, flow, label) {
    if (!backEl) return;
    var link = document.createElement('a');
    if (flow) {
      var url = new URL(page, window.location.href);
      url.searchParams.set('flow', flow);
      link.href = url.href;
      link.textContent = '← Back to ' + label;
    } else {
      link.href = 'dashboard.html';
      link.textContent = '← Back to the verification dashboard';
    }
    backEl.appendChild(link);
  }

  /**
   * Render every published run of one test.
   * @param {!HTMLElement} statusEl Element carrying the summary, or the reason
   *     the table is empty.
   * @param {!HTMLElement} nameEl Heading showing which test is displayed.
   * @param {!HTMLElement} wrapEl Wrapper revealed once the table is drawn.
   * @param {!HTMLTableSectionElement} headEl Header row host.
   * @param {!HTMLTableSectionElement} rowsEl Body the rows are appended to.
   */
  function renderTestDetail(statusEl, nameEl, wrapEl, headEl, rowsEl) {
    var fail = failWith(statusEl);
    var params = new URLSearchParams(window.location.search);
    var backEl = document.getElementById('dashboard-detail-back');

    fetchJson(TEST_HISTORY_URL)
      .then(function (history) {
        var runs = history.runs || [];
        var flows = history.flows || {};
        var flow = knownName(flows, params.get('flow'));
        var tests = flow ? flows[flow] : {};
        var test = knownName(tests, params.get('test'));
        backTo(backEl, 'dashboard-test-history.html', flow, flow + ' test history');
        if (!test) {
          fail('no such test in the published archives; reach this page from a block’s test history');
          return;
        }
        nameEl.textContent = test;
        document.title = test + ' — Test Detail';

        var cells = tests[test];
        fillHead(headEl, ['Run', 'Outcome', 'Seeds', 'Failure reason(s)']);

        var tally = { passed: 0, flaky: 0, failed: 0, 'did not run': 0 };
        // Newest first
        for (var i = runs.length - 1; i >= 0; i--) {
          var counts = cells[i];
          var state = historyState(counts);
          var seeds = (counts && counts.seeds) || [];
          tally[state] += 1;

          // A run spans one sub-row per seed, so each seed sits beside the
          // reason it gave.
          var span = Math.max(1, seeds.length);
          var row = document.createElement('tr');
          var runTd = runCell(runs[i]);
          var outcomeTd = outcomeCell(counts, state);
          runTd.rowSpan = span;
          outcomeTd.rowSpan = span;
          row.appendChild(runTd);
          row.appendChild(outcomeTd);
          seedCells(row, seeds[0] || null);
          rowsEl.appendChild(row);

          for (var s = 1; s < seeds.length; s++) {
            var extra = document.createElement('tr');
            seedCells(extra, seeds[s]);
            rowsEl.appendChild(extra);
          }
        }

        statusEl.className = 'dashboard-status';
        statusEl.textContent =
          flow +
          ' — ' +
          tally.passed +
          ' passed, ' +
          tally.flaky +
          ' flaky, ' +
          tally.failed +
          ' failed, ' +
          tally['did not run'] +
          ' did not run, across ' +
          runs.length +
          ' runs.';
        wrapEl.hidden = false;
      })
      .catch(function (error) {
        backTo(backEl, 'dashboard-test-history.html', '', '');
        fail(error.message);
      });
  }

  /**
   * Render the per-test history for one block as a heatmap.
   * @param {!HTMLElement} statusEl Element carrying the range, or the reason
   *     the grid is empty.
   * @param {!HTMLElement} nameEl Heading showing which block is displayed.
   * @param {!HTMLElement} wrapEl Wrapper revealed once the grid is drawn.
   * @param {!HTMLElement} chartEl Element the heatmap is drawn into.
   */
  function renderTestHistory(statusEl, nameEl, wrapEl, chartEl) {
    var fail = failWith(statusEl);
    var requested = new URLSearchParams(window.location.search).get('flow');
    var backEl = document.getElementById('dashboard-history-back');

    fetchJson(TEST_HISTORY_URL)
      .then(function (history) {
        var runs = history.runs || [];
        var flows = history.flows || {};
        var flow = knownName(flows, requested);
        backTo(backEl, 'dashboard-block.html', flow, flow);
        if (!flow) {
          fail('no such block in the published archives; reach this page from the dashboard');
          return;
        }
        nameEl.textContent = flow;
        document.title = flow + ' — Test History';

        var tests = flows[flow];
        var names = Object.keys(tests).sort();
        if (!runs.length || !names.length) {
          fail('the published archives contain no test results');
          return;
        }

        // One record per cell, carrying the seed counts for the tooltip.
        var cells = [];
        names.forEach(function (name, y) {
          (tests[name] || []).forEach(function (counts, x) {
            var state = historyState(counts);
            cells.push({
              value: [x, y, 1],
              counts: counts,
              state: state,
              itemStyle: { color: HISTORY_COLOURS[state] },
            });
          });
        });

        wrapEl.hidden = false;
        chartEl.style.height = Math.max(400, names.length * 15 + 140) + 'px';

        var chart = echarts.init(chartEl, null, { renderer: 'svg' });
        chart.setOption({
          aria: { enabled: true },
          animation: false,
          // ECharts writes its text and axis styling inline, which a
          // stylesheet cannot override, so both are taken from the theme here.
          textStyle: {
            fontFamily: themeValue('--oca-font-body', 'sans-serif'),
            color: themeValue('--oca-text', '#484848'),
          },
          grid: { left: 270, right: 24, top: 56, bottom: 64 },
          tooltip: {
            backgroundColor: themeValue('--oca-cream-light', '#f8f4eb'),
            borderColor: themeValue('--oca-green', '#103525'),
            textStyle: {
              color: themeValue('--oca-text', '#484848'),
              fontFamily: themeValue('--oca-font-body', 'sans-serif'),
            },
            formatter: function (params) {
              var cell = cells[params.dataIndex];
              return (
                names[cell.value[1]] +
                '<br>' +
                runs[cell.value[0]].date +
                ': ' +
                cell.state +
                (cell.counts ? ' (' + cell.counts.pass + '/' + cell.counts.total + ')' : '')
              );
            },
          },
          // The legend is driven by scatter series carrying no data; a heatmap
          // series has one name and so cannot label four outcomes.
          legend: {
            top: 8,
            data: HISTORY_STATES,
            // The entries label the colours rather than toggling anything, so
            // the series they name stay shown.
            selectedMode: false,
            textStyle: { color: themeValue('--oca-text', '#484848'), fontSize: 11 },
          },
          xAxis: {
            type: 'category',
            data: runs.map(function (run) {
              return run.date.slice(5);
            }),
            axisLabel: {
              rotate: 90,
              fontSize: 10,
              color: themeValue('--oca-text', '#484848'),
            },
            axisLine: { lineStyle: { color: GRID_LINE } },
            axisTick: { show: false },
            splitArea: { show: false },
          },
          yAxis: {
            type: 'category',
            data: names,
            // Lets the test names be clicked, not just the cells.
            triggerEvent: true,
            // Without interval, ECharts drops every other name to avoid
            // collisions, leaving half the rows unlabelled.
            axisLabel: { fontSize: 9, color: LINK_COLOUR, interval: 0 },
            axisLine: { lineStyle: { color: GRID_LINE } },
            axisTick: { show: false },
            splitArea: { show: false },
          },
          series: [
            {
              type: 'heatmap',
              data: cells,
              itemStyle: { borderWidth: 0.5, borderColor: '#ffffff' },
            },
          ].concat(
            HISTORY_STATES.map(function (state) {
              return {
                name: state,
                type: 'scatter',
                data: [],
                itemStyle: { color: HISTORY_COLOURS[state] },
              };
            })
          ),
        });

        chart.on('click', function (params) {
          if (params.componentType !== 'yAxis') return;
          var name = knownName(tests, params.value);
          if (!name) return;
          var url = new URL('dashboard-test-detail.html', window.location.href);
          url.searchParams.set('flow', flow);
          url.searchParams.set('test', name);
          window.location.href = url.href;
        });

        if (window.ResizeObserver) {
          new ResizeObserver(function () {
            chart.resize();
          }).observe(chartEl);
        }

        statusEl.className = 'dashboard-status';
        statusEl.textContent =
          names.length +
          ' tests across ' +
          runs.length +
          ' runs, ' +
          runs[0].date +
          ' to ' +
          runs[runs.length - 1].date +
          '.';
      })
      .catch(function (error) {
        backTo(backEl, 'dashboard-block.html', '', '');
        fail(error.message);
      });
  }

  var statusEl = document.getElementById('dashboard-status');
  if (!statusEl) return;

  var detailRowsEl = document.getElementById('dashboard-detail-rows');
  if (detailRowsEl) {
    renderTestDetail(
      statusEl,
      document.getElementById('dashboard-detail-name'),
      document.getElementById('dashboard-test-detail'),
      document.getElementById('dashboard-detail-head'),
      detailRowsEl
    );
    return;
  }

  var historyChartEl = document.getElementById('dashboard-history-chart');
  if (historyChartEl) {
    renderTestHistory(
      statusEl,
      document.getElementById('dashboard-history-name'),
      document.getElementById('dashboard-test-history'),
      historyChartEl
    );
    return;
  }

  var trendsEl = document.getElementById('dashboard-trends');
  var windowEl = document.getElementById('dashboard-window-select');
  if (trendsEl && windowEl) {
    renderTrends(statusEl, trendsEl, windowEl);
    return;
  }

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
