"""CLI, library and raw file reads share named loader resolution."""

import json
from pathlib import Path
import subprocess
import sys

import pytest

from aidrin.file_handling.custom_loader import CustomLoaderError, using_custom_loader
from aidrin.file_handling.file_parser import read_file
from aidrin.headless.api import run_batch_metrics, run_metric


@pytest.fixture
def registered_data(tmp_path, monkeypatch):
    script = tmp_path / 'reader.py'
    script.write_text('import pandas as pd\ndef load(path, **kwargs):\n    return pd.read_csv(path, sep=";")\n')
    registry = tmp_path / 'formats.json'
    registry.write_text(json.dumps([
        {'id': 'household', 'name': 'Household power', 'extensions': ['.txt'], 'loader': 'reader.py:load'},
    ]))
    monkeypatch.setenv('AIDRIN_REGISTERED_LOADERS_FILE', str(registry))
    data = tmp_path / 'POWER.TXT'
    data.write_text('a;b\n1;2\n3;4\n')
    return data


def test_library_and_context_use_registry(registered_data):
    data = registered_data
    frame = read_file((str(data), data.name, '.txt'), loader='registered:household')
    assert frame.to_dict('list') == {'a': [1, 3], 'b': [2, 4]}
    with using_custom_loader('registered:household'):
        assert read_file((str(data), data.name, '.txt')).equals(frame)
    result = run_metric('completeness', str(data), loader='registered:household', save_images=False, strip_visualizations=True)
    assert result['Overall Completeness'] == 1.0
    assert result['Completeness scores'] == {'a': 1.0, 'b': 1.0}


def test_batch_uses_same_registry(registered_data):
    result = run_batch_metrics({
        'file_path': str(registered_data), 'metrics': ['completeness'],
        'loader': 'registered:household', 'save_images': False,
    }, strip_visualizations=True)
    assert result['completeness']['Overall Completeness'] == 1.0


def test_actual_cli_uses_registered_loader(registered_data):
    # Launch the actual CLI entry function in a fresh process.
    result = subprocess.run([
        sys.executable, '-c', 'from aidrin.headless.cli import main; main()',
        'run', 'completeness', str(registered_data), '--loader', 'registered:household',
    ], capture_output=True, text=True, check=True, cwd=Path(__file__).resolve().parents[2])
    payload = json.loads(result.stdout)
    assert payload['Overall Completeness'] == 1.0
    assert payload['Completeness scores'] == {'a': 1.0, 'b': 1.0}


def test_registry_errors_are_explicit(registered_data, monkeypatch):
    info = (str(registered_data), registered_data.name, '.txt')
    with pytest.raises(CustomLoaderError, match='Unknown registered format'):
        read_file(info, loader='registered:missing')
    monkeypatch.delenv('AIDRIN_REGISTERED_LOADERS_FILE')
    with pytest.raises(CustomLoaderError, match='AIDRIN_REGISTERED_LOADERS_FILE'):
        read_file(info, loader='registered:household')


def test_registry_checks_extension(registered_data):
    other = registered_data.with_suffix('.dat')
    other.write_text(registered_data.read_text())
    with pytest.raises(CustomLoaderError, match='extension does not match'):
        read_file((str(other), other.name, '.dat'), loader='registered:household')


def test_explicit_script_still_works_without_registry(registered_data, monkeypatch):
    monkeypatch.delenv('AIDRIN_REGISTERED_LOADERS_FILE')
    info = (str(registered_data), registered_data.name, '.txt')
    spec = f'{registered_data.parent / "reader.py"}:load'
    assert len(read_file(info, loader=spec)) == 2


def test_script_update_with_same_size_and_timestamp_uses_new_code(registered_data):
    import os

    script = registered_data.parent / 'reader.py'
    body = 'import pandas as pd\ndef load(path, **kwargs):\n    return pd.DataFrame({"value": [1]})\n'
    script.write_text(body)
    original_stat = script.stat()
    info = (str(registered_data), registered_data.name, '.txt')
    assert read_file(info, loader='registered:household')['value'].tolist() == [1]
    script.write_text(body.replace('[1]', '[2]'))
    os.utime(script, ns=(original_stat.st_atime_ns, original_stat.st_mtime_ns))
    assert read_file(info, loader='registered:household')['value'].tolist() == [2]
