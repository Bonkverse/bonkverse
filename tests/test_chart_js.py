"""Checks for the chart and date helpers in static/core/js.

These run the real JavaScript files in Node (skipped when Node isn't installed).
"""

import json
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
DATES = ROOT / "static/core/js/bv-dates.js"
CHART = ROOT / "static/core/js/bv-chart.js"

pytestmark = pytest.mark.skipif(shutil.which("node") is None, reason="needs node")


def run_js(body: str, fake_root_locale: bool = False):
    """Load bv-dates.js and bv-chart.js into a fresh context, run `body`, return its JSON result.

    With `fake_root_locale`, the browser's own locale formats months as "M03",
    the way some browsers do for languages they have no month names for.
    """
    script = f"""
const vm = require("vm");
const fs = require("fs");
const RealDTF = Intl.DateTimeFormat;
const FakeIntl = Object.create(Intl);
FakeIntl.DateTimeFormat = function (locale, opts) {{
  if (locale === undefined && {json.dumps(fake_root_locale)}) {{
    return {{ format: (d) => "M" + String(d.getMonth() + 1).padStart(2, "0") }};
  }}
  return new RealDTF(locale, opts);
}};
const ctx = {{ Intl: {"FakeIntl" if fake_root_locale else "Intl"} }};
ctx.window = ctx;
vm.createContext(ctx);
vm.runInContext(fs.readFileSync({json.dumps(str(DATES))}, "utf8"), ctx);
vm.runInContext(fs.readFileSync({json.dumps(str(CHART))}, "utf8"), ctx);
process.stdout.write(JSON.stringify(vm.runInContext({json.dumps(body)}, ctx)));
"""
    out = subprocess.run(["node", "-e", script], capture_output=True, text=True, check=True)
    return json.loads(out.stdout)


def test_level_range_gets_whole_number_ticks():
    # The level chart that showed "181, 181, 180, 180, 179": 179 to 181, padded.
    ticks = run_js("BVChart.niceTicks(178.88, 181.12, 6, true)")
    assert ticks == [179, 180, 181]


def test_fractional_data_keeps_fine_ticks():
    ticks = run_js("BVChart.niceTicks(178.88, 181.12, 6, false)")
    assert 179.5 in ticks


def test_integer_ticks_never_use_two_and_a_half():
    ticks = run_js("BVChart.niceTicks(0, 11, 4, true)")
    assert all(float(t).is_integer() for t in ticks)
    assert ticks[0] == 0 and ticks[-1] >= 10


def test_small_counts_do_not_repeat():
    # A bar chart whose biggest bar is 1 replay.
    ticks = run_js("BVChart.niceTicks(0, 1, 5, true)")
    assert ticks == [0, 1]


def test_dates_use_browser_locale_when_it_has_month_names():
    assert run_js("BVDates.pickLocale('fr')") == "fr"


def test_dates_fall_back_to_english_instead_of_m03():
    label = run_js(
        "BVDates.format({ month: 'short', day: 'numeric', year: 'numeric' }).format(new Date(2025, 2, 17))",
        fake_root_locale=True,
    )
    assert "M03" not in label
    assert "Mar" in label
