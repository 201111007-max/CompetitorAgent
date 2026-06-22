"""GSI 服务器测试"""

import sys
import json
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from gsi.server import GSIServer
from gsi.state_manager import GSIStateManager
from gsi.event_handler import GSIEventHandler
from gsi.event_queue import GSIEventQueue


class TestGSIServer:
    def _create_server(self, token="test_token"):
        eq = GSIEventQueue()
        handler = GSIEventHandler(eq)
        manager = GSIStateManager(event_handler=handler)
        server = GSIServer(host="127.0.0.1", port=0, token=token,
                           state_manager=manager, event_handler=handler)
        return server, manager

    def test_valid_token(self):
        server, manager = self._create_server("my_token")
        app = server._create_app()
        with app.test_client() as client:
            resp = client.post('/', json={"auth": {"token": "my_token"}, "hero": {"name": "pudge"}})
            assert resp.status_code == 200

    def test_invalid_token(self):
        server, _ = self._create_server("my_token")
        app = server._create_app()
        with app.test_client() as client:
            resp = client.post('/', json={"auth": {"token": "wrong"}})
            assert resp.status_code == 403

    def test_no_token_required(self):
        server, manager = self._create_server("")
        app = server._create_app()
        with app.test_client() as client:
            resp = client.post('/', json={"hero": {"name": "axe"}})
            assert resp.status_code == 200

    def test_no_json(self):
        server, _ = self._create_server()
        app = server._create_app()
        with app.test_client() as client:
            resp = client.post('/', data="not json", content_type="text/plain")
            assert resp.status_code in (400, 415)

    def test_health(self):
        server, _ = self._create_server()
        app = server._create_app()
        with app.test_client() as client:
            resp = client.get('/health')
            assert resp.status_code == 200
            assert json.loads(resp.data)["status"] == "ok"
