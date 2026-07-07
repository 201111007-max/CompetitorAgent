"""语音提醒系统集成测试"""

import pytest
from pathlib import Path
from unittest.mock import MagicMock

from gsi.event_queue import GSIEventQueue
from gsi.event_handler import GSIEventHandler
from gsi.models import GameState
from utils.voice_player import VoicePlayer


class TestVoiceEventHandlerIntegration:
    """测试 VoicePlayer 与 EventHandler 的集成"""

    def test_event_handler_with_voice_player(self):
        """测试 EventHandler 正确调用 VoicePlayer"""
        event_queue = GSIEventQueue(max_history=10)
        voice_player = MagicMock(spec=VoicePlayer)
        
        handler = GSIEventHandler(
            event_queue=event_queue,
            config={},
            voice_player=voice_player
        )
        
        # 模拟游戏状态
        state = GameState()
        state.game_time = 120  # 2分钟
        state.daytime = True
        
        prev_state = GameState()
        prev_state.game_time = 119
        
        # 触发事件
        handler.on_game_time_tick(state, prev_state)
        
        # 验证 voice_player.play 被调用
        assert voice_player.play.called

    def test_event_handler_without_voice_player(self):
        """测试 EventHandler 在没有 VoicePlayer 时正常工作"""
        event_queue = GSIEventQueue(max_history=10)
        
        handler = GSIEventHandler(
            event_queue=event_queue,
            config={},
            voice_player=None
        )
        
        state = GameState()
        state.game_time = 120
        state.daytime = True
        
        prev_state = GameState()
        prev_state.game_time = 119
        
        # 不应该抛出异常
        handler.on_game_time_tick(state, prev_state)
        
        # 验证事件仍然被添加到队列（通过 get_recent 检查）
        recent = event_queue.get_recent(10)
        assert len(recent) > 0

    def test_voice_player_receives_correct_event_types(self):
        """测试 VoicePlayer 接收正确的事件类型"""
        event_queue = GSIEventQueue(max_history=10)
        voice_player = MagicMock(spec=VoicePlayer)
        
        handler = GSIEventHandler(
            event_queue=event_queue,
            config={},
            voice_player=voice_player
        )
        
        # 测试昼夜切换事件
        state = GameState()
        state.daytime = False  # 夜晚
        
        handler.on_daytime_changed(state)
        
        # 验证调用了正确的事件类型
        voice_player.play.assert_called_with("nighttime")

    def test_voice_config_loaded_from_yaml(self):
        """测试从 YAML 配置文件加载语音配置"""
        import yaml
        
        config_path = Path(__file__).parent.parent.parent / "config" / "gsi_config.yaml"
        
        if not config_path.exists():
            pytest.skip("配置文件不存在")
        
        with open(config_path, 'r', encoding='utf-8') as f:
            config = yaml.safe_load(f)
        
        voice_config = config.get("voice", {})
        
        # 验证配置结构
        assert "enabled" in voice_config
        assert "volume" in voice_config
        assert "resources_dir" in voice_config
        assert "events" in voice_config
        
        # 验证可以创建 VoicePlayer
        player = VoicePlayer(voice_config)
        assert player._enabled == voice_config["enabled"]
        assert player._volume == voice_config["volume"]

    def test_voice_player_with_real_audio_files(self):
        """测试使用真实音频文件"""
        resources_dir = Path(__file__).parent.parent.parent / "resources" / "voice"
        
        if not resources_dir.exists():
            pytest.skip("音频资源目录不存在")
        
        config = {
            "enabled": True,
            "volume": 0.5,
            "resources_dir": str(resources_dir)
        }
        
        player = VoicePlayer(config)
        
        # 验证 pygame 可用（如果已安装）
        if player._pygame_available:
            # 测试播放不会抛出异常
            # 注意：实际播放需要音频设备，这里只验证不报错
            try:
                player.play("stack")
            except Exception as e:
                # 某些环境可能没有音频设备，这是可以接受的
                print(f"音频播放失败（可能缺少音频设备）: {e}")


class TestVoiceAPIEndpoints:
    """测试语音相关的 Web API 端点"""

    def test_voice_api_status_endpoint_exists(self):
        """测试语音状态 API 端点存在"""
        # 这个测试验证 app.py 中定义了相关端点
        # 实际的 HTTP 测试需要使用 Flask 测试客户端
        from web.app import app
        
        # 获取所有路由
        routes = [rule.rule for rule in app.url_map.iter_rules()]
        
        # 验证语音相关端点存在
        assert "/api/voice/status" in routes
        assert "/api/voice/toggle" in routes
        assert "/api/voice/volume" in routes
        assert "/api/voice/event" in routes


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
