"""Synthetic sequence audits: no real Parkfield or other project data."""

import io
import json
from unittest.mock import patch

import numpy as np
import pandas as pd
import pytest

from aidrin.structured_data_metrics import grouped_time_series as module


def audit(monkeypatch, times, groups=None, **kwargs):
    frame = pd.DataFrame({"sensor": groups if groups is not None else ["A"] * len(times), "time": times})
    monkeypatch.setattr(module, "read_file", lambda _: frame)
    return module.calculate_grouped_time_series(("unused", "unused", ".csv"), ["sensor"], "time", 0.01, **kwargs)


def test_group_isolation_original_order_and_exact_intervals(monkeypatch):
    result = audit(monkeypatch, [0, 0, .02, .01, .01, .01, 0, .02], ["A", "B"] * 4)
    a, b = result["groups"]
    assert a["group"] == {"sensor": "A"}
    assert a["finding_counts"] == {"cadence_gap": 1, "out_of_order": 2, "duplicate_time": 1}
    assert a["findings"][0] == {
        "kind": "cadence_gap", "estimated_missing_samples": 1,
        "from_row_position": 0, "to_row_position": 2, "from_time": 0, "to_time": .02, "delta": .02,
    }
    assert b["finding_counts"] == {"duplicate_time": 1}
    assert a["last_time"] == 0  # Not sorted to conceal reversals.


def test_float_cadence_and_zero_values_are_valid(monkeypatch):
    frame = pd.DataFrame({"station": ["S"] * 1000, "component": ["X"] * 1000,
                          "t": np.arange(1000) * .01, "acceleration": np.zeros(1000)})
    original = frame.copy(deep=True)
    monkeypatch.setattr(module, "read_file", lambda _: frame)
    result = module.calculate_grouped_time_series(("x", "x", ".csv"), ["station", "component"], "t", .01)
    assert result["groups"][0]["finding_counts"] == {}
    assert result["groups"][0]["time_reference"] == "relative_or_unspecified"
    pd.testing.assert_frame_equal(frame, original)
    json.dumps(result, allow_nan=False)


@pytest.mark.parametrize("time_kind", ["datetime", "auto"])
def test_datetime_nanosecond_precision_and_offset_equivalence(monkeypatch, time_kind):
    times = ["2026-01-01T00:00:00.000000000Z", "2025-12-31T19:00:00.000000001-05:00",
             "2026-01-01T00:00:00.000000003Z"]
    frame = pd.DataFrame({"sensor": [1, 1, 1], "time": times})
    monkeypatch.setattr(module, "read_file", lambda _: frame)
    result = module.calculate_grouped_time_series(("x", "x", ".csv"), ["sensor"], "time", 1e-9, time_kind=time_kind)
    assert result["parameters"]["time_kind"] == "datetime"
    group = result["groups"][0]
    assert group["observed_duration"] == pytest.approx(3e-9)
    assert group["finding_counts"] == {"cadence_gap": 1}
    assert group["findings"][0]["estimated_missing_samples"] == 1
    assert group["time_reference"] == "timezone_aware"


def test_missing_invalid_nonfinite_times_break_adjacency(monkeypatch):
    result = audit(monkeypatch, [0, None, .04, "bad", .08, np.inf, .12, -.0])
    group = result["groups"][0]
    assert group["finding_counts"] == {"missing_time": 1, "invalid_time": 1, "nonfinite_time": 1,
                                        "duplicate_time": 1, "out_of_order": 1}
    assert group["evaluated_adjacent_intervals"] == 1
    assert group["valid_time_count"] == 5
    json.dumps(result, allow_nan=False)


def test_mixed_timezone_awareness_is_diagnostic_not_assumed_utc(monkeypatch):
    result = audit(monkeypatch, ["2026-01-01T00:00:00", "2026-01-01T00:00:00.01Z",
                                "2026-01-01T00:00:00.02"], time_kind="datetime")
    group = result["groups"][0]
    assert group["finding_counts"] == {"mixed_timezone_awareness": 1}
    assert group["evaluated_adjacent_intervals"] == 0
    assert group["time_reference"] == "timezone_unspecified"


def test_numeric_epoch_is_not_implicitly_datetime(monkeypatch):
    result = audit(monkeypatch, [0, 1], time_kind="datetime")
    assert result["groups"][0]["finding_counts"] == {"invalid_time": 2, "insufficient_valid_times": 1}


def test_auto_keeps_numeric_strings_numeric_and_audits_bad_values(monkeypatch):
    result = audit(monkeypatch, ["1700000000000000000", "1700000000000000001", "bad"], time_kind="auto")
    assert result["parameters"]["time_kind"] == "numeric"
    assert result["groups"][0]["last_time"] == "1700000000000000001"
    assert result["summary"]["finding_counts"] == {"cadence_gap": 1, "invalid_time": 1}


def test_auto_datetime_does_not_infer_a_date_for_time_only_rows(monkeypatch):
    result = audit(monkeypatch, ["2026-01-01T00:00:00Z", "12:00", "2026-01-01T00:00:00.03Z"], time_kind="auto")
    assert result["parameters"]["time_kind"] == "datetime"
    assert result["summary"]["finding_counts"] == {"invalid_time": 1}
    assert result["groups"][0]["evaluated_adjacent_intervals"] == 0


def test_auto_rejects_mixed_formats_and_manual_override_remains_available(monkeypatch):
    times = ["0", "2026-01-01T00:00:00Z", "0.01"]
    with pytest.raises(ValueError, match="both numbers and dates"):
        audit(monkeypatch, times, time_kind="auto")
    assert audit(monkeypatch, times, time_kind="numeric")["summary"]["finding_counts"] == {"invalid_time": 1}


def test_tolerance_short_intervals_and_off_grid_gap(monkeypatch):
    group = audit(monkeypatch, [0, .0105, .016, .041], tolerance=.001)["groups"][0]
    assert group["finding_counts"] == {"cadence_short": 1, "cadence_gap": 1}
    assert group["findings"][1]["estimated_missing_samples"] is None


def test_truncated_details_keep_full_counts(monkeypatch):
    group = audit(monkeypatch, [0, 0, 0, 0], max_findings=1)["groups"][0]
    assert group["finding_counts"] == {"duplicate_time": 3}
    assert len(group["findings"]) == 1
    assert group["findings_truncated"]
    assert len(audit(monkeypatch, [0, 0, 0, 0], max_findings=0)["groups"][0]["findings"]) == 3


def test_counts_and_duration_detect_truncated_regular_sequence(monkeypatch):
    group = audit(monkeypatch, [0, .01, .02], expected_count=5, expected_duration=.04)["groups"][0]
    assert group["finding_counts"] == {"count_mismatch": 1, "duration_mismatch": 1}
    assert group["row_count"] == 3
    assert group["observed_duration"] == .02


def test_missing_group_keys_not_combined_into_a_sequence(monkeypatch):
    result = audit(monkeypatch, [0, .01, .02], [None, "A", None], max_findings=1)
    assert result["summary"]["unassigned_rows"] == 2
    assert result["unassigned_row_positions"] == [0]
    assert result["unassigned_rows_truncated"]
    assert result["groups"][0]["row_count"] == 1
    assert result["groups"][0]["finding_counts"] == {"insufficient_valid_times": 1}


def test_empty_table_has_zero_groups(monkeypatch):
    assert audit(monkeypatch, [])["summary"] == {
        "total_rows": 0, "group_count": 0, "groups_with_findings": 0, "unassigned_rows": 0, "finding_counts": {},
    }


def test_overflowing_numeric_span_is_diagnostic(monkeypatch):
    group = audit(monkeypatch, [-1e308, 1e308])["groups"][0]
    assert group["finding_counts"] == {"nonfinite_interval": 1, "nonfinite_duration": 1}
    assert group["observed_duration"] is None
    json.dumps(group, allow_nan=False)


@pytest.mark.parametrize("options", [
    {"expected_cadence": 0}, {"expected_cadence": float("inf")}, {"expected_cadence": True},
    {"group_columns": []}, {"group_columns": ["sensor", "sensor"]}, {"group_columns": ["absent"]},
    {"timestamp_column": "sensor"}, {"timestamp_column": "absent"}, {"time_kind": "unknown"},
    {"tolerance": -.1}, {"tolerance": .005}, {"max_findings": 1.2}, {"expected_count": 0},
    {"expected_duration": float("nan")},
])
def test_invalid_configuration_is_rejected(monkeypatch, options):
    monkeypatch.setattr(module, "read_file", lambda _: pd.DataFrame({"sensor": ["A"], "time": [0]}))
    params = dict(group_columns=["sensor"], timestamp_column="time", expected_cadence=.01)
    params.update(options)
    with pytest.raises(ValueError):
        module.calculate_grouped_time_series(("x", "x", ".csv"), **params)


def test_non_scalar_key_rejected(monkeypatch):
    monkeypatch.setattr(module, "read_file", lambda _: pd.DataFrame({"sensor": [[1]], "time": [0]}))
    with pytest.raises(ValueError, match="scalar"):
        module.calculate_grouped_time_series(("x", "x", ".csv"), ["sensor"], "time", .01)


def test_public_api_cli_batch_and_remote_agree(tmp_path):
    import aidrin
    from aidrin.headless.api import run_metric, run_batch_metrics
    from aidrin.headless.cli import main
    from aidrin.compute.remote import remote_metric_runner

    path = tmp_path / "sequence.csv"
    path.write_text("sensor,time,value\nA,0,0\nB,0,0\nA,0.02,0\nB,0.01,0\n")
    kwargs = dict(group_columns=["sensor"], timestamp_column="time", expected_cadence=.01)
    expected = aidrin.calculate_grouped_time_series((str(path), path.name, ".csv"), **kwargs)
    assert run_metric("grouped-time-series", str(path), save_images=False, **kwargs) == expected
    config = {"file-path": str(path), "metrics": ["grouped-time-series"], "group-columns": "sensor",
              "timestamp-column": "time", "expected-cadence": .01, "save-images": False}
    assert run_batch_metrics(config)["grouped_time_series"] == expected
    assert remote_metric_runner("grouped_time_series", str(path), path.name, ".csv", **kwargs) == expected
    assert remote_metric_runner("data_quality", str(path), path.name, ".csv",
                                selected=["grouped_time_series"], **kwargs) == {"Grouped Time Series": expected}
    output = io.StringIO()
    with patch("sys.argv", ["aidrin", "run", "grouped-time-series", str(path), "--group-columns", "sensor",
                            "--timestamp-column", "time", "--expected-cadence", ".01"]), patch("sys.stdout", output):
        main()
    assert json.loads(output.getvalue()) == expected


def test_safe_telemetry_omits_group_identities(monkeypatch):
    from aidrin.telemetry.redaction import project
    result = audit(monkeypatch, [0, .02], ["private-identity"] * 2)
    projected = project("grouped_time_series", result)
    assert projected["aidrin.quality.sequence_groups_with_findings"] == 1
    assert "private-identity" not in json.dumps(projected)


def test_cli_retains_fine_time_precision(tmp_path):
    from aidrin.headless.cli import main
    path = tmp_path / 'fine.csv'
    path.write_text('sensor,time\nA,0\nA,0.000001\nA,0.000003\n')
    output = io.StringIO()
    with patch('sys.argv', ['aidrin', 'run', 'grouped-time-series', str(path), '--group-columns', 'sensor',
                            '--timestamp-column', 'time', '--expected-cadence', '0.000001', '--tolerance', '0.000000001']), \
            patch('sys.stdout', output):
        main()
    result = json.loads(output.getvalue())
    assert result['parameters']['tolerance'] == 1e-9
    assert result['groups'][0]['last_time'] == .000003
    assert result['groups'][0]['findings'][0]['estimated_missing_samples'] == 1


def test_mcp_grouped_arguments_reach_audit(tmp_path):
    pytest.importorskip('mcp')
    from aidrin.mcp.server import run_aidrin_metric
    path = tmp_path / 'mcp.csv'
    path.write_text('sensor,time\nA,0\nA,0.02\n')
    result = json.loads(run_aidrin_metric(
        str(path), 'grouped_time_series', group_columns='sensor', timestamp_column='time',
        expected_cadence=.01, time_kind='numeric', tolerance=1e-6, max_findings=0,
        expected_count=3, expected_duration=.03,
    ))
    assert result['groups'][0]['finding_counts'] == {'cadence_gap': 1, 'count_mismatch': 1, 'duration_mismatch': 1}
    assert result['parameters']['max_findings'] == 0


def test_renderer_preserves_precision_and_escapes_group_values():
    import re
    import shutil
    import subprocess
    from pathlib import Path
    node = shutil.which('node')
    if not node:
        pytest.skip('Node is unavailable')
    source = (Path(__file__).parents[2] / 'web/static/js/inspector.js').read_text(encoding='utf-8')
    render = source[source.index('function formatGroupedTime('):source.index('function renderGroupedCollectionResults(')]
    escape = re.search(r'function escapeHtml\(str\) \{[\s\S]*?\n\}', source).group()
    result = {
        'parameters': {'time_kind': 'datetime', 'timestamp_column': 'time', 'expected_cadence': 5e-10},
        'summary': {'group_count': 2, 'groups_with_findings': 1, 'unassigned_rows': 0,
                    'finding_counts': {'cadence_gap': 1, 'duplicate_time': 2}},
        'groups': [{'group': {'sensor': '<img src=x onerror=alert(1)>'}, 'row_count': 4,
                    'valid_time_count': 4, 'observed_duration': 1e-9, 'finding_counts': {'cadence_gap': 1, 'duplicate_time': 2},
                    'findings': [{'kind': 'cadence_gap', 'delta': 1e-9, 'from_row_position': 0, 'to_row_position': 1,
                                  'from_time': '2026-01-01T00:00:00Z', 'to_time': '2026-01-01T00:00:00.000000001Z',
                                  'estimated_missing_samples': 1},
                                 {'kind': 'duplicate_time', 'row_position': 2, 'first_row_position': 1,
                                  'time': '2026-01-01T00:00:00.000000001Z'}], 'findings_truncated': True},
                   {'group': {'sensor': 'B'}, 'row_count': 3, 'valid_time_count': 3, 'observed_duration': 1e-9,
                    'evaluated_adjacent_intervals': 2, 'finding_counts': {}, 'findings': []}],
    }
    script = escape + '\n' + render + f'\nconst result = {json.dumps(result)};' + """
const numeric = { ...result, parameters: {time_kind: "numeric"}, groups: result.groups.slice(1) };
process.stdout.write(JSON.stringify([
  renderGroupedTimeSeriesResults(result),
  renderGroupedTimeSeriesResults(numeric),
  renderGroupedTimeSeriesTable([...groupedTimeSeriesRows(result), ...groupedTimeSeriesRows(numeric)])
]));
"""
    output = subprocess.run([node, '-e', script], check=True, capture_output=True, encoding='utf-8').stdout
    html, numeric_html, mixed_html = json.loads(output)
    assert '<img src=x' not in html
    assert '&lt;img src=x' in html
    assert '1e-9' in html
    assert 'Time column time · Expected spacing 5e-10 s' in html
    assert html.count('<th scope="row"') == 2
    assert 'Rows<br>checked</th>' in html
    assert 'Valid<br>timestamps</th>' in html
    assert re.search(r'Observed span<br><span[^>]*>\(seconds\)</span></th>', html)
    assert '>1e-9</td>' in html
    assert re.search(r'Observed span<br><span[^>]*>\(time column units\)</span></th>', numeric_html)
    assert '>1e-9</td>' in numeric_html
    assert 'Observed span</th>' in mixed_html
    assert '>1e-9 s</td>' in mixed_html
    assert '>1e-9 column units</td>' in mixed_html
    assert 'Both checked intervals matched.' in html
    assert 'More finding details (1)' in html
    assert 'The gap suggests 1 missing sample.' in html
    assert 'data row 1 and data row 2' in html
    assert 'counts cover all rows' in html
    assert '<pre' not in html


@pytest.mark.parametrize('malformed_tail', [False, True])
def test_large_integer_ticks_remain_exact_in_csv(tmp_path, malformed_tail):
    from aidrin import calculate_grouped_time_series
    path = tmp_path / 'integer_ticks.csv'
    path.write_text('sensor,tick\nA,9007199254740992\nA,9007199254740993\nA,9007199254740994\n' +
                    ('A,invalid\n' if malformed_tail else ''))
    result = calculate_grouped_time_series((str(path), path.name, '.csv'), ['sensor'], 'tick', 1)
    group = result['groups'][0]
    assert group['finding_counts'] == ({'invalid_time': 1} if malformed_tail else {})
    assert group['unique_time_count'] == 3
    assert group['observed_duration'] == 2
    assert group['first_time'] == '9007199254740992'
    assert group['last_time'] == '9007199254740994'
    json.dumps(result, allow_nan=False)


def test_large_integer_failing_interval_and_duration_are_exact(monkeypatch):
    group = audit(monkeypatch, [2**53, 2**53 + 3])['groups'][0]
    assert group['findings'][0]['from_time'] == str(2**53)
    assert group['findings'][0]['to_time'] == str(2**53 + 3)
    assert group['findings'][0]['delta'] == 3
    span = audit(monkeypatch, [-2**63, 2**63 - 1])['groups'][0]
    assert span['observed_duration'] == str(2**64 - 1)
    assert span['findings'][0]['delta'] == str(2**64 - 1)


@pytest.mark.parametrize('start,end', [(0, 2**53 + 1), (-2**63, 2**63 - 1)])
def test_large_integer_missing_count_and_duration_detail_are_exact(tmp_path, start, end):
    from aidrin import calculate_grouped_time_series
    path = tmp_path / 'large_gap.csv'
    path.write_text(f'sensor,tick\nA,{start}\nA,{end}\n')
    group = calculate_grouped_time_series((str(path), path.name, '.csv'), ['sensor'], 'tick', 1,
                                         expected_duration=1)['groups'][0]
    gap, mismatch = group['findings']
    assert gap['kind'] == 'cadence_gap'
    assert gap['delta'] == str(end - start)
    assert gap['estimated_missing_samples'] == str(end - start - 1)
    assert mismatch['kind'] == 'duration_mismatch'
    assert mismatch['observed'] == group['observed_duration'] == str(end - start)
