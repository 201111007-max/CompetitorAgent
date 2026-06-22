"""GSI HTTP 服务器 - 独立 Flask 实例"""

import threading
from typing import Optional

from utils.log_config import get_logger

logger = get_logger("gsi_server", component="gsi")


class GSIServer:
    """GSI HTTP 服务器"""

    def __init__(self, host: str, port: int, token: str,
                 state_manager, event_handler):
        self.host = host
        self.port = port
        self.token = token
        self.state_manager = state_manager
        self.event_handler = event_handler
        self._app = None
        self._thread: Optional[threading.Thread] = None

    def _create_app(self):
        """创建 Flask 应用"""
        from flask import Flask, request, jsonify
        import logging

        app = Flask(__name__)
        logging.getLogger('werkzeug').setLevel(logging.WARNING)

        @app.route('/', methods=['POST'])
        def handle_gsi():
            data = request.json
            if not data:
                return jsonify({"error": "No JSON data"}), 400
            if self.token:
                auth_token = data.get('auth', {}).get('token', '')
                if auth_token != self.token:
                    return jsonify({"error": "Invalid token"}), 403
            self.state_manager.update_state(data)
            return jsonify({"status": "ok"})

        @app.route('/health', methods=['GET'])
        def health():
            state = self.state_manager.get_state()
            return jsonify({
                "status": "ok",
                "connected": self.state_manager.connected,
                "hero": state.hero_name if state else None,
            })

        return app

    def start(self) -> None:
        """后台线程启动 GSI 服务器"""
        if self._thread is not None and self._thread.is_alive():
            return
        self._app = self._create_app()
        def run():
            self._app.run(host=self.host, port=self.port, threaded=True, debug=False, use_reloader=False)
        self._thread = threading.Thread(target=run, daemon=True)
        self._thread.start()
        logger.info(f"GSI 服务器已启动: http://{self.host}:{self.port}")
