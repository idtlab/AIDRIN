"""Web form and JSON result coverage with synthetic grouped sequences."""

import io

import pandas as pd
import pytest


def suggest_interval(client, **fields):
    return client.post('/data-quality', data={
        'action': 'suggest_grouped_interval',
        'grouped_series': 'file',
        'timestamp column for grouped time series': 't',
        'time kind for grouped time series': 'auto',
        **fields,
    })


@pytest.mark.parametrize('file_type', ['.csv', '.parquet', '.json'])
def test_suggest_interval_from_samples_for_multiple_formats(client, monkeypatch, file_type):
    # Two regular intervals and one gap still support a 0.01-second suggestion.
    values = {'t': [0, .01, .02, .04], 'value': [1, 2, 3, 4]}
    table = pd.DataFrame(values)
    if file_type == '.csv':
        content = table.to_csv(index=False).encode()
    elif file_type == '.parquet':
        table['t'] = pd.to_datetime(table['t'], unit='s', origin='2026-01-01')
        content = table.to_parquet(index=False)
    else:
        content = table.to_json(orient='records').encode()
    assert client.post('/inspector', data={
        'file': (io.BytesIO(content), f'times{file_type}'),
        'fileTypeSelector': file_type,
    }).status_code == 302
    if file_type == '.json':
        assert suggest_interval(client).status_code == 400
        assert client.post('/feature-set').get_json()['success']

    from aidrin.file_handling.file_parser import READER_MAP

    def reject_full_read(self):
        pytest.fail('An interval suggestion must never do a full file read')

    monkeypatch.setattr(READER_MAP[file_type], 'read', reject_full_read)
    response = suggest_interval(client)
    assert response.status_code == 200
    assert response.get_json()['interval'] == .01
    assert response.get_json()['time_kind'] == ('datetime' if file_type == '.parquet' else 'numeric')
    assert not client.get('/cached-result/data_quality').get_json()['cached']


def test_suggest_interval_declines_inconsistent_data_and_exhausted_budget(client, monkeypatch):
    assert client.post('/inspector', data={
        'file': (io.BytesIO(b't,value\n0,1\n.01,2\n.03,3\n.06,4\n'), 'irregular.csv'),
        'fileTypeSelector': '.csv',
    }).status_code == 302
    response = suggest_interval(client)
    assert response.status_code == 400
    assert 'uneven spacing' in response.get_json()['error']
    monkeypatch.setattr('web.routes.grouped_interval._TIME_BUDGET', 0)
    response = suggest_interval(client)
    assert response.status_code == 400
    assert 'timed out' in response.get_json()['error']


def test_whole_file_sequence_checks_a_file_without_series_identifiers(client):
    response = client.post('/inspector', data={
        'file': (io.BytesIO(b'time,value\n0,4\n0.0105,5\n0.0305,6\n'), 'one_series.csv'),
        'fileTypeSelector': '.csv',
    }, content_type='multipart/form-data')
    assert response.status_code == 302
    response = client.post('/data-quality?return_type=json', data={
        'grouped time series': 'yes',
        'grouped_series': 'file',
        'timestamp column for grouped time series': 'time',
        'cadence for grouped time series': '.01',
        'tolerance for grouped time series': '.001',
    })
    assert response.status_code == 200
    result = response.get_json()['Grouped Time Series']
    assert result['summary']['group_count'] == 1
    assert result['summary']['finding_counts'] == {'cadence_gap': 1}
    assert result['groups'][0]['findings'][0]['from_row_position'] == 1
    assert result['groups'][0]['findings'][0]['to_row_position'] == 2


def test_grouped_sequence_web_form_and_results(client):
    response = client.post('/inspector', data={
        'file': (io.BytesIO(b'station,component,t,value\nA,X,0,0\nA,X,0.02,0\nA,Y,0,0\nA,Y,0.01,0\n'), 'sensors.csv'),
        'fileTypeSelector': '.csv',
    }, content_type='multipart/form-data')
    assert response.status_code == 302
    page = client.get('/inspector').get_data(as_text=True)
    assert 'name="grouped time series"' in page
    assert 'id="groupedTimeSeriesTimeDropdown"' in page
    assert 'id="groupedTimeSeriesColumnsCheckbox"' in page
    response = client.post('/data-quality?return_type=json', data={
        'grouped time series': 'yes',
        'grouped_series': 'columns',
        'group columns for grouped time series': ['station', 'component'],
        'timestamp column for grouped time series': 't',
        'cadence for grouped time series': '.01',
        'expected count for grouped time series': '3',
        'max findings for grouped time series': '0',
    })
    assert response.status_code == 200
    result = response.get_json()['Grouped Time Series']
    assert result['summary']['group_count'] == 2
    assert result['groups'][0]['finding_counts'] == {'cadence_gap': 1, 'count_mismatch': 1}
    assert result['groups'][1]['finding_counts'] == {'count_mismatch': 1}
    assert result['parameters']['max_findings'] == 0
    assert result['groups'][0]['findings'][0]['from_row_position'] == 0


def test_invalid_grouped_form_is_actionable(uploaded_client):
    response = uploaded_client.post('/data-quality?return_type=json', data={'grouped time series': 'yes'})
    assert response.status_code == 200
    assert 'group_columns' in response.get_json()['Grouped Time Series']['Error']

    response = uploaded_client.post('/data-quality?return_type=json', data={
        'grouped time series': 'yes',
        'grouped_series': 'columns',
        'timestamp column for grouped time series': 'time',
        'cadence for grouped time series': '.01',
    })
    assert 'Choose at least one column' in response.get_json()['Grouped Time Series']['Error']


def test_web_sequence_precision_and_existing_score_formatting(client):
    from web.routes.utils import format_dict_values

    response = client.post('/inspector', data={
        'file': (io.BytesIO(b'sensor,t\nA,0\nA,0.000001\nA,0.000003\n'), 'fine.csv'),
        'fileTypeSelector': '.csv',
    }, content_type='multipart/form-data')
    assert response.status_code == 302
    response = client.post('/data-quality?return_type=json', data={
        'grouped time series': 'yes',
        'group columns for grouped time series': ['sensor'],
        'timestamp column for grouped time series': 't',
        'cadence for grouped time series': '0.000001',
        'tolerance for grouped time series': '0.000000001',
    })
    result = response.get_json()['Grouped Time Series']
    assert result['parameters']['expected_cadence'] == 1e-6
    assert result['parameters']['tolerance'] == 1e-9
    assert result['groups'][0]['last_time'] == 3e-6
    assert result['groups'][0]['findings'][0]['delta'] == 2.0000000000000003e-6
    # Existing chart-score formatting remains unchanged in the same wrapper.
    formatted = format_dict_values({'sequence': result, 'score': {'ratio': .123456}})
    assert formatted['sequence'] == result
    assert formatted['score']['ratio'] == .123
