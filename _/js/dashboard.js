// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

// Renders the verification dashboard and its per-block drill-down pages from
// the DV data staged into the site at deploy time.
(function () {
  'use strict';

  // Generate the headings rather than defining literally in the html
  var METRIC_HEADINGS = ['Tests', 'Passing'];
  var SUMMARY_HEADINGS = ['Block (framework, simulator)'].concat(METRIC_HEADINGS);
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

  // The fields that together name one series, and the query parameters a page
  // selects one with.
  var IDENTITY = ['flow', 'framework', 'tool'];

  // The blocks each table declares. A block publishing nothing still gets a
  // row, so what is in scope but unverified stays visible.
  var CHIP_ROWS = ['chip_ocah'];
  var BLOCK_ROWS = ['dtp', 'sep', 'smc', 'smu', 'aou'];
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
   * The series a page asked for, read from the query string.
   *
   * "?flow=dtp&framework=uvm" gives {flow: 'dtp', framework: 'uvm'}, matching
   * that block under uvm on any simulator.
   * @return {!Object} The dimensions given; an absent one matches every value.
   */
  function selector() {
    var params = new URLSearchParams(window.location.search);
    var wanted = {};
    IDENTITY.forEach(function (field) {
      var value = params.get(field);
      if (value) wanted[field] = value;
    });
    return wanted;
  }

  /**
   * Whether an entry matches every dimension a selector names.
   * @param {!Object} entry Any entry carrying the identity fields.
   * @param {!Object} wanted The dimensions to match.
   * @return {boolean} True when every named dimension agrees.
   */
  function matches(entry, wanted) {
    return IDENTITY.every(function (field) {
      return wanted[field] === undefined || entry[field] === wanted[field];
    });
  }

  /**
   * Name one series for a heading, e.g. "dtp (uvm, vcs)".
   *
   * Where the framework and simulator are absent, the block name stands alone.
   * @param {!Object} entry Any entry carrying the identity fields.
   * @return {string} The block, with the framework and simulator that ran it.
   */
  function seriesLabel(entry) {
    var ran = ['framework', 'tool']
      .filter(function (field) {
        return entry[field];
      })
      .map(function (field) {
        return entry[field];
      });
    return entry.flow + (ran.length ? ' (' + ran.join(', ') + ')' : '');
  }

  /**
   * Add a series' identity to a URL, so a link narrows to exactly that series.
   * @param {!URL} url The URL to add them to.
   * @param {!Object} entry Any entry carrying the identity fields.
   */
  function addIdentity(url, entry) {
    IDENTITY.forEach(function (field) {
      if (entry[field]) url.searchParams.set(field, entry[field]);
    });
  }

  /**
   * The coverage families the given series report between them. Which families
   * exist depends on the simulator, so a page asks only about what it shows.
   * @param {!Object} summary Parsed summary.json.
   * @param {!Array<!Object>} entries The dut_status entries being shown.
   * @return {!Array<string>} The family names, sorted.
   */
  function coverageFamilies(summary, entries) {
    var seen = Object.create(null);
    entries.forEach(function (entry) {
      var metrics = (coverageFor(summary, entry) || {}).effective_metrics || {};
      Object.keys(metrics).forEach(function (family) {
        seen[family] = true;
      });
    });
    return Object.keys(seen).sort();
  }

  /**
   * A coverage family as a column heading, e.g. "fsm_state" to "Fsm state".
   * @param {string} family The family as the publisher names it.
   * @return {string} The heading.
   */
  function familyHeading(family) {
    return (family.charAt(0).toUpperCase() + family.slice(1)).replace(/_/g, ' ');
  }

  /**
   * The coverage a summary published for one series.
   * @param {!Object} summary Parsed summary.json.
   * @param {!Object} entry The dut_status entry to match.
   * @return {?Object} Its results[].coverage, or null when it has none.
   */
  function coverageFor(summary, entry) {
    var result = (summary.results || []).filter(function (candidate) {
      return matches(candidate, {
        flow: entry.flow,
        framework: entry.framework,
        tool: entry.tool,
      });
    })[0];
    return (result && result.coverage) || null;
  }

  /**
   * Bind an error reporter to a status element, so both pages report failures
   * the same way.
   * @param {!HTMLElement} statusEl The element to write the error message to.
   * @return {function(string)} A function which writes a given reason to statusEl.
   */
  function failWith(statusEl) {
    return function (reason) {
      statusEl.hidden = false;
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
   * Build one row of an overview table, naming the series and linking to its
   * block page.
   * @param {string} name Block name, used when nothing was published for it.
   * @param {?Object} dut The series' dut_status entry, or null when the block
   *     published none; every measurement then reads n/a.
   * @return {!HTMLTableRowElement} The populated row.
   */
  function summaryRow(name, dut) {
    var row = document.createElement('tr');
    var td = document.createElement('td');

    // The block and what ran it name one series, so they share a cell rather
    // than a column each.
    if (dut && LINKABLE_ROWS.indexOf(name) !== -1) {
      var url = new URL('dashboard-block.html', window.location.href);
      addIdentity(url, dut);
      var link = document.createElement('a');
      link.href = url.href;
      link.textContent = seriesLabel(dut);
      td.appendChild(link);
    } else {
      td.textContent = dut ? seriesLabel(dut) : name;
    }
    row.appendChild(td);

    if (!dut) {
      for (var i = 1; i < SUMMARY_HEADINGS.length + 1; i++) {
        cell(row, 'n/a', 'dashboard-na');
      }
      return row;
    }

    metricCells(row, dut, null, null);
    return row;
  }

  /**
   * Add the measurement cells one series reports.
   * @param {!HTMLTableRowElement} row The row to append them to.
   * @param {!Object} dut The series' dut_status entry.
   * @param {?Object} coverage Its results[].coverage entry, if any.
   * @param {?Array<string>} families One cell per coverage family, or null for
   *     the single total the publisher reports.
   */
  function metricCells(row, dut, coverage, families) {
    var total = dut.tests_total;
    if (total === null || total === undefined) {
      cell(row, 'n/a', 'dashboard-na');
    } else {
      cell(row, String(total));
    }
    metricCell(row, dut.pass_rate);

    if (!families) {
      metricCell(row, dut.coverage_total_percent);
      return;
    }

    var metrics = (coverage && coverage.effective_metrics) || {};
    families.forEach(function (family) {
      metricCell(row, metrics[family]);
    });
  }

  /**
   * Add a row naming a series, so one table can carry several.
   * @param {!HTMLTableSectionElement} body The body to append the row to.
   * @param {string} label The series name.
   * @param {number} span The columns the table carries.
   */
  function headingRow(body, label, span) {
    var row = document.createElement('tr');
    var th = document.createElement('th');
    th.colSpan = span;
    th.scope = 'colgroup';
    th.textContent = label;
    row.appendChild(th);
    body.appendChild(row);
  }

  /**
   * Render the overview dashboard split into chip and block tables.
   * @param {!HTMLElement} statusEl Element carrying the reason the tables are
   *     empty.
   * @param {!HTMLTableSectionElement} chipRowsEl Body of the chip-level table.
   * @param {!HTMLTableSectionElement} blockRowsEl Body of the block-level table.
   */
  function renderDashboard(statusEl, chipRowsEl, blockRowsEl) {
    var fail = failWith(statusEl);

    // One coverage figure here, as the publisher reports it; the block page
    // breaks it down by family.
    var headings = SUMMARY_HEADINGS.concat(['Coverage']);
    fillHead(document.getElementById('dashboard-chip-head'), headings);
    fillHead(document.getElementById('dashboard-block-head'), headings);

    fetchJson(SUMMARY_URL)
      .then(function (summary) {
        /**
         * Fill a table, giving a block one row per series it published. A
         * block that published none still gets a row, reading n/a.
         * @param {!HTMLTableSectionElement} body The table body to fill.
         * @param {!Array<string>} names The blocks that table declares.
         */
        function fill(body, names) {
          names.forEach(function (name) {
            var series = (summary.dut_status || []).filter(function (dut) {
              return dut.flow === name;
            });
            if (!series.length) {
              body.appendChild(summaryRow(name, null));
              return;
            }
            series.forEach(function (dut) {
              body.appendChild(summaryRow(name, dut));
            });
          });
        }

        fill(chipRowsEl, CHIP_ROWS);
        fill(blockRowsEl, BLOCK_ROWS);

        // Hide the now-empty banner.
        statusEl.hidden = true;
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
    var wanted = selector();
    var flow = wanted.flow || '';

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
      var series = (summary.dut_status || []).filter(function (entry) {
        return matches(entry, wanted);
      });
      if (!series.length) return false;

      var families = coverageFamilies(summary, series);
      var headings = METRIC_HEADINGS.concat(families.map(familyHeading));
      fillHead(document.getElementById('dashboard-block-summary-head'), headings);
      series.forEach(function (dut) {
        // The page heading names the series; only several need telling apart.
        if (series.length > 1) headingRow(rowEl, seriesLabel(dut), headings.length);
        var row = document.createElement('tr');
        metricCells(row, dut, coverageFor(summary, dut), families);
        rowEl.appendChild(row);
      });
      summaryEl.hidden = false;

      statusEl.hidden = true;
      return true;
    }

    /**
     * Render the per-block drill-down table containing each individual test.
     * @param {!Object} detail Parsed tests.json.
     */
    function renderTests(detail) {
      var series = (detail.results || []).filter(function (entry) {
        return matches(entry, wanted);
      });
      if (!series.length) return;

      series.forEach(function (entry) {
        var tests = entry.tests || [];
        if (!tests.length) return;

        if (series.length > 1) headingRow(testRowsEl, seriesLabel(entry), TEST_HEADINGS.length);

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
      });

      testsEl.hidden = false;
    }

    fillHead(document.getElementById('dashboard-test-head'), TEST_HEADINGS);

    if (!flow) {
      fail('no block selected; reach this page from the verification dashboard');
      return;
    }
    nameEl.textContent = seriesLabel(wanted);
    document.title = seriesLabel(wanted) + ' — Block Verification Detail';

    var historyEl = document.getElementById('dashboard-block-history');
    if (historyEl) {
      var historyUrl = new URL('dashboard-test-history.html', window.location.href);
      addIdentity(historyUrl, wanted);
      var historyLink = document.createElement('a');
      historyLink.href = historyUrl.href;
      historyLink.textContent = 'Per-test history for ' + seriesLabel(wanted) + ' \u2192';
      historyEl.appendChild(historyLink);
    }

    fetchJson(SUMMARY_URL)
      .then(function (summary) {
        if (!renderSummary(summary)) {
          fail('the published data has no series named "' + seriesLabel(wanted) + '"');
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
   * @param {?Object} entry The resolved series, or null when none was.
   * @param {string} label What to call the destination in the link text.
   */
  function backTo(backEl, page, entry, label) {
    // A failure after the link is drawn reaches here a second time.
    if (!backEl || backEl.firstChild) return;
    var link = document.createElement('a');
    if (entry && entry.flow) {
      var url = new URL(page, window.location.href);
      addIdentity(url, entry);
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
        var wanted = selector();
        var series = (history.series || []).filter(function (entry) {
          return matches(entry, wanted);
        })[0];
        var runs = (series && series.runs) || [];
        var tests = (series && series.tests) || {};
        var test = knownName(tests, params.get('test'));
        backTo(backEl, 'dashboard-test-history.html', series, 'test history');
        if (!test) {
          fail('no such test in the published archives; reach this page from a block’s test history');
          return;
        }
        nameEl.textContent = test + ' — ' + seriesLabel(series);
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
    var wanted = selector();
    var backEl = document.getElementById('dashboard-history-back');

    /**
     * Draw one series' grid, in its own element below any already drawn.
     * @param {!Object} series One entry of test-history.json's series.
     * @param {!HTMLElement} host Element to draw the grid into.
     */
    function heatmap(series, host) {
      var runs = series.runs || [];
      var tests = series.tests || {};
      var names = Object.keys(tests).sort();
      if (!runs.length || !names.length) return;

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

      host.style.height = Math.max(400, names.length * 15 + 140) + 'px';

      var chart = echarts.init(host, null, { renderer: 'svg' });
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
          // Returned as a node rather than as markup, so a published value
          // cannot carry HTML into the page.
          formatter: function (params) {
            var cell = cells[params.dataIndex];
            var tip = document.createElement('div');

            var name = document.createElement('div');
            name.textContent = names[cell.value[1]];
            tip.appendChild(name);

            var outcome = runs[cell.value[0]].date + ': ' + cell.state;
            if (cell.counts) {
              outcome += ' (' + cell.counts.pass + '/' + cell.counts.total + ')';
            }
            var detail = document.createElement('div');
            detail.textContent = outcome;
            tip.appendChild(detail);

            return tip;
          },
        },
        // The legend is driven by scatter series carrying no data; a heatmap
        // series has one name and so cannot label four outcomes.
        legend: {
          top: 8,
          data: HISTORY_STATES,
          // A key, not a control: clicking an entry must not hide its cells.
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
      addIdentity(url, series);
      url.searchParams.set('test', name);
      window.location.href = url.href;
    });

    if (window.ResizeObserver) {
        new ResizeObserver(function () {
          chart.resize();
        }).observe(host);
      }

      return { tests: names.length, runs: runs };
    }

    fetchJson(TEST_HISTORY_URL)
      .then(function (history) {
        var series = (history.series || []).filter(function (entry) {
          return matches(entry, wanted);
        });
        backTo(
          backEl,
          'dashboard-block.html',
          series[0],
          series.length ? seriesLabel(series[0]) : ''
        );
        if (!series.length) {
          fail('no such block in the published archives; reach this page from the dashboard');
          return;
        }

        nameEl.textContent = wanted.flow ? seriesLabel(wanted) : 'Test history';
        document.title = (wanted.flow ? seriesLabel(wanted) : 'Test') + ' — Test History';
        wrapEl.hidden = false;

        var drawn = [];
        series.forEach(function (entry) {
          // Each series gets its own element, so several stack down the page
          // rather than one overwriting another.
          var host = chartEl;
          if (series.length > 1) {
            var heading = document.createElement('h4');
            heading.textContent = seriesLabel(entry);
            chartEl.appendChild(heading);
            host = document.createElement('div');
            host.className = 'dashboard-chart';
            chartEl.appendChild(host);
          }
          var shown = heatmap(entry, host);
          if (shown) drawn.push(shown);
        });

        if (!drawn.length) {
          fail('the published archives contain no test results');
          return;
        }

        var runs = drawn[0].runs;
        statusEl.className = 'dashboard-status';
        statusEl.textContent =
          drawn.length +
          (drawn.length === 1 ? ' series, ' : ' series, up to ') +
          Math.max.apply(null, drawn.map(function (d) { return d.tests; })) +
          ' tests across ' +
          runs.length +
          ' runs, ' +
          runs[0].date +
          ' to ' +
          runs[runs.length - 1].date +
          '.';
      })
      .catch(function (error) {
        backTo(backEl, 'dashboard-block.html', null, '');
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
