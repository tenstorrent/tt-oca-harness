# DV Dashboard Data

Canonical store for the OCAH DV weekly dashboard data. The `dashboard`
workflow on `main` (`.github/workflows/dashboard.yml`) writes `latest/`
and `data/`; publishers of other flows keep their own top-level
directory. The documentation site renders its verification dashboard
from this branch. Do not edit by hand.

    latest/<dut>.result.json                      one normalized result per weekly DUT (schema "0.2")
    latest/summary.json                           the aggregate over those results (schema "0.2")
    latest/artifacts/<dut>/coverage/              staged coverage files of a run that collected coverage
    data/history.json                             trend history, newest 90 points (schema "0.2")
    data/runs/<dut>/<date>-run<id>.result.json.gz  archives of the newest 90 runs, per DUT
    data/runs/<date>-run<id>.result.json.gz        the one-DUT-per-run series the documentation site's test-history page reads
    data/classification/<date>.json               infrastructure / design / flaky split, per DUT and summed
