"""Web form and JSON result coverage with synthetic grouped sequences."""

import io


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
