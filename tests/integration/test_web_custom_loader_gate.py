"""Pasted web loaders require explicit administrator opt-in."""

import io
from pathlib import Path

import pytest

from aidrin.file_handling.custom_loader import CustomLoaderError, get_active_loader_spec
from web.routes.utils import build_file_info


def test_web_loaders_disabled_by_default(client, app):
    assert app.config['ENABLE_WEB_CUSTOM_LOADERS'] is False
    html = client.get('/inspector').get_data(as_text=True)
    assert 'id="tab-custom"' not in html
    assert 'id="custom-upload"' not in html
    response = client.post('/inspector', data={
        'file': (io.BytesIO(b'a\n1\n'), 'data.csv'),
        'fileTypeSelector': '.custom',
        'loader_code': "raise RuntimeError('must never run')",
    }, follow_redirects=True)
    assert 'Web custom loaders are disabled' in response.get_data(as_text=True)
    assert not list(Path(app.config['UPLOAD_FOLDER']).iterdir())
    assert not list(Path(app.config['CUSTOM_LOADERS_FOLDER']).iterdir())
    with client.session_transaction() as sess:
        assert 'custom_loader_spec' not in sess
        assert 'uploaded_file_path' not in sess


@pytest.mark.parametrize('value,enabled', [('1', True), ('true', True), ('YES', True), ('0', False), ('false', False)])
def test_web_loader_environment_switch(monkeypatch, value, enabled):
    from web import create_app

    monkeypatch.setenv('AIDRIN_ENABLE_WEB_CUSTOM_LOADERS', value)
    app = create_app()
    assert app.config['ENABLE_WEB_CUSTOM_LOADERS'] is enabled
    html = app.test_client().get('/inspector').get_data(as_text=True)
    assert ('id="tab-custom"' in html) is enabled


def test_switch_off_blocks_existing_session_before_worker_dispatch(app, tmp_path):
    from flask import session

    dataset = Path(app.config['UPLOAD_FOLDER']) / 'data.txt'
    dataset.write_text('a\n1\n')
    script = tmp_path / 'loader.py'
    script.write_text("raise RuntimeError('must never run')")
    with app.test_request_context():
        session['custom_loader_spec'] = f'{script}:load'
        with pytest.raises(CustomLoaderError, match='disabled'):
            get_active_loader_spec()
        with pytest.raises(CustomLoaderError, match='disabled'):
            build_file_info(str(dataset), 'data.txt', '.txt')


def test_named_security_switch_takes_precedence_over_generic_flask_config(monkeypatch):
    from web import create_app

    monkeypatch.setenv('AIDRIN_ENABLE_WEB_CUSTOM_LOADERS', '0')
    monkeypatch.setenv('FLASK_ENABLE_WEB_CUSTOM_LOADERS', 'true')
    assert create_app().config['ENABLE_WEB_CUSTOM_LOADERS'] is False


def test_startup_validates_registry_after_flask_config_merge(tmp_path, monkeypatch):
    from web import create_app

    registry = tmp_path / 'invalid.json'
    registry.write_text('{}')
    monkeypatch.setenv('FLASK_REGISTERED_LOADERS_FILE', str(registry))
    with pytest.raises(ValueError, match='JSON list'):
        create_app()
