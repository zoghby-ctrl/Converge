import json
import socket

from fastapi.testclient import TestClient

from backend.app.main import create_app
from fixtures.generate import build


def complete(client, scenario='signature'):
    reset = client.post('/api/v1/demo/replay', json={'action': 'reset', 'scenario': scenario})
    assert reset.status_code == 200
    state = reset.json()
    while state['step'] < state['total_steps']:
        response = client.post('/api/v1/demo/replay', json={'action': 'advance'})
        assert response.status_code == 200, response.text
        state = response.json()
    return state


def test_persisted_replay_revision_history_reset_and_restart(tmp_path):
    path = tmp_path / 'test.sqlite3'
    app = create_app(path)
    with TestClient(app) as client:
        health = client.get('/api/v1/health').json()
        assert health['sqlite_foreign_keys'] and not health['openai_enabled']
        client.post('/api/v1/demo/replay', json={'action': 'reset'})
        assert client.get('/api/v1/signals/b-water-later').status_code == 404
        started = client.post('/api/v1/demo/replay', json={'action': 'start'}).json()
        assert started['step'] == 1 and len(started['signals']) == 1
        assert client.post('/api/v1/demo/replay', json={'action': 'start'}).json()['step'] == 1
        first = complete(client)
        b = next(i for i in first['incidents'] if i['status'] == 'candidate')
        assert client.get('/api/v1/incidents/' + b['incident_id']).json() == b
        assert client.get('/api/v1/signals/b-water-later').json()['provenance']['content_origin'] == 'synthetic'
        assert client.post('/api/v1/demo/replay', json={'action': 'advance'}).json() == first
        with app.state.store.connection() as db:
            assert db.execute('PRAGMA foreign_key_check').fetchall() == []
            assert db.execute('SELECT count(*) FROM signals').fetchone()[0] == 12
            assert db.execute('SELECT count(*) FROM incident_revisions').fetchone()[0] > 3
            assert db.execute('SELECT count(*) FROM incident_members').fetchone()[0] > 12
        assert complete(client) == first
    with TestClient(create_app(path)) as client:
        assert client.get('/api/v1/incidents').json() == first
        empty = client.post('/api/v1/demo/replay', json={'action': 'reset'}).json()
        assert empty['incidents'] == [] and empty['signals'] == [] and empty['step'] == 0


def test_comparison_is_transient_and_duplicate_invariant(tmp_path):
    with TestClient(create_app(tmp_path / 'test.sqlite3')) as client:
        state = complete(client)
        ablation = client.post('/api/v1/demo/compare', json={'disable_families': ['image']}).json()
        b = next(i for i in ablation['incidents'] if i['status'] == 'candidate')
        assert b['risk']['display'] == '52–83' and b['evidence_strength'] == 'Limited'
        copies = client.post('/api/v1/demo/compare', json={'add_duplicates': 10}).json()
        for before, after in zip(copies['baseline'], copies['incidents']):
            assert before['risk'] == after['risk']
            assert before['hypotheses'] == after['hypotheses']
            assert before['independent_capture_count'] == after['independent_capture_count']
        assert client.get('/api/v1/incidents').json() == state


def test_cached_image_signature_replay_and_scoped_image_delivery(tmp_path):
    with TestClient(create_app(tmp_path / 'test.sqlite3')) as client:
        state = complete(client, 'signature_image')
        b = next(i for i in state['incidents'] if i['status'] == 'candidate')
        image = next(s for s in state['signals'] if s['signal_id'] == 'b-road-image')
        assert state['mode'] == 'cached_extraction'
        assert (b['risk']['display'], b['evidence_strength'],
                b['independent_capture_count']) == ('68', 'Moderate', 3)
        assert image['provenance']['annotation_method'] == 'ai_image'
        assert image['image_url'] == '/api/v1/signals/b-road-image/image'
        assert image.get('image_path') is None
        delivered = client.get(image['image_url'])
        assert delivered.status_code == 200 and delivered.headers['content-type'] == 'image/jpeg'
        ablation = client.post('/api/v1/demo/compare', json={'disable_families': ['image']}).json()
        changed = next(i for i in ablation['incidents'] if i['status'] == 'candidate')
        assert changed['risk']['display'] == '52–83' and changed['evidence_strength'] == 'Limited'
        assert changed['independent_capture_count'] == 2
        copies = client.post('/api/v1/demo/compare', json={
            'add_duplicates': 10, 'source_signal_id': 'b-water-first'}).json()
        duplicate_b = next(i for i in copies['incidents'] if 'b-water-first' in i['signal_ids'])
        assert len(duplicate_b['signal_ids']) == 13
        assert duplicate_b['independent_capture_count'] == 3
        assert duplicate_b['risk'] == b['risk']
        assert duplicate_b['hypotheses'] == b['hypotheses']
        assert duplicate_b['evidence_strength'] == b['evidence_strength']
        assert client.post('/api/v1/demo/compare', json={
            'add_duplicates': 10, 'source_signal_id': 'missing'}).status_code == 422



def test_legacy_structured_image_does_not_advertise_missing_file(tmp_path):
    with TestClient(create_app(tmp_path / 'test.sqlite3')) as client:
        state = complete(client, 'signature')
        image = next(s for s in state['signals'] if s['signal_id'] == 'b-road-image')
        assert 'image_url' not in image and client.get(
            '/api/v1/signals/b-road-image/image'
        ).status_code == 404


def test_structured_input_and_limits_are_enforced(tmp_path):
    with TestClient(create_app(tmp_path / 'test.sqlite3')) as client:
        assert client.post('/api/v1/demo/compare', json={}).status_code == 409
        assert client.post('/api/v1/demo/replay', json={'action': 'reset', 'scenario': '../secret'}).status_code == 404
        payload = build()['spatial_119m']
        result = client.post('/api/v1/demo/replay', json={'action': 'reset', 'dataset': payload})
        assert result.status_code == 200
        assert client.post('/api/v1/demo/replay', json={'action': 'advance'}).json()['incidents'][0]['status'] == 'candidate'
        assert client.post('/api/v1/demo/compare', json={'add_duplicates': 11}).status_code == 422
        payload['signals'][0]['provenance']['content_origin'] = 'collected'
        assert client.post('/api/v1/demo/replay', json={'action': 'reset', 'dataset': payload}).status_code == 422
        assert client.post('/api/v1/demo/replay', json={'action': 'advance', 'dataset': payload}).status_code == 422


def test_backend_replay_runs_with_network_connections_disabled(tmp_path, monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError('Outbound network attempted')
    with TestClient(create_app(tmp_path / 'test.sqlite3')) as client:
        # Initialize Windows asyncio's loopback self-pipe before disabling connections.
        monkeypatch.setattr(socket, 'create_connection', forbidden)
        monkeypatch.setattr(socket.socket, 'connect', forbidden)
        result = complete(client)
        assert len(result['incidents']) == 3
        assert client.post('/api/v1/demo/compare', json={'disable_families': ['image']}).status_code == 200


def test_atomic_failed_step_does_not_leave_partial_writes(tmp_path):
    app = create_app(tmp_path / 'test.sqlite3')
    with TestClient(app) as client:
        complete(client)
        before = client.get('/api/v1/incidents').json()
        with app.state.store.connection() as db:
            # Simulate a storage failure after signal writes, before snapshot completion.
            db.execute("CREATE TRIGGER fail_snapshot BEFORE INSERT ON incident_revisions BEGIN SELECT RAISE(ABORT, 'test failure'); END")
        from backend.app.engine import run_engine
        from backend.app.models import Dataset
        from datetime import datetime
        dataset = Dataset.model_validate(build()['signature'])
        clock = datetime.fromisoformat(before['clock'])
        items, excluded, signals = run_engine(dataset, clock)
        import sqlite3
        import pytest
        with pytest.raises(sqlite3.IntegrityError):
            app.state.store.commit_step(dataset, clock, 7, items, excluded, signals)
        assert client.get('/api/v1/incidents').json() == before
