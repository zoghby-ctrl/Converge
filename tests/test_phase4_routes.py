from fastapi.testclient import TestClient
from backend.app.main import create_app


def test_phase4_spa_routing_and_asset_serving(tmp_path):
    app = create_app(tmp_path / 'routes.sqlite3')
    with TestClient(app) as client:
        # 1. Entry Gateway (/)
        res_root = client.get('/')
        assert res_root.status_code == 200
        assert 'text/html' in res_root.headers.get('content-type', '')
        assert '<div id="root"></div>' in res_root.text

        # 2. Report Surface (/report)
        res_report = client.get('/report')
        assert res_report.status_code == 200
        assert 'text/html' in res_report.headers.get('content-type', '')
        assert '<div id="root"></div>' in res_report.text

        # 3. Operations Workbench (/operations)
        res_ops = client.get('/operations')
        assert res_ops.status_code == 200
        assert 'text/html' in res_ops.headers.get('content-type', '')
        assert '<div id="root"></div>' in res_ops.text

        # 4. PWA manifest and service worker
        res_manifest = client.get('/manifest.json')
        assert res_manifest.status_code == 200
        manifest_data = res_manifest.json()
        assert 'Converge' in manifest_data.get('name', '')
        assert manifest_data.get('short_name') == 'Converge'
        assert manifest_data.get('display') == 'standalone'

        res_sw = client.get('/sw.js')
        assert res_sw.status_code == 200
        assert 'SHELL_ASSETS' in res_sw.text

        res_icon = client.get('/icons/icon.svg')
        assert res_icon.status_code == 200

        # 5. Verify /api/* endpoints are NOT shadowed or intercepted
        res_health = client.get('/api/v1/health')
        assert res_health.status_code == 200
        assert res_health.headers.get('content-type', '').startswith('application/json')
        assert 'sqlite_foreign_keys' in res_health.json()

        # Unknown /api/* route must return 404 (JSON/FastAPI default), never SPA index.html
        res_api_unknown = client.get('/api/v1/non_existent_endpoint')
        assert res_api_unknown.status_code == 404
        assert 'text/html' not in res_api_unknown.headers.get('content-type', '')
