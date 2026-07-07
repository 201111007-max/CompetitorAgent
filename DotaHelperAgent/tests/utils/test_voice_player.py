"""VoicePlayer 单元测试"""

import os
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock

from utils.voice_player import VoicePlayer


class TestVoicePlayerInit:
    """VoicePlayer 初始化测试"""

    def test_init_default_config(self):
        """测试默认配置初始化"""
        player = VoicePlayer()
        assert player._enabled is True
        assert player._volume == 0.7
        assert player._resources_dir == "resources/voice"
        assert player._event_settings == {}

    def test_init_custom_config(self):
        """测试自定义配置初始化"""
        config = {
            "enabled": False,
            "volume": 0.5,
            "resources_dir": "/custom/path",
            "events": {"stack": True, "rune_mid": False},
        }
        player = VoicePlayer(config)
        assert player._enabled is False
        assert player._volume == 0.5
        assert player._resources_dir == "/custom/path"
        assert player._event_settings == {"stack": True, "rune_mid": False}

    def test_init_empty_config(self):
        """测试空字典配置初始化"""
        player = VoicePlayer({})
        assert player._enabled is True
        assert player._volume == 0.7


class TestVoicePlayerPlay:
    """VoicePlayer 播放测试"""

    def test_play_disabled_global(self):
        """测试全局禁用时不播放"""
        config = {"enabled": False}
        player = VoicePlayer(config)
        # play 应该不报错，直接返回
        player.play("stack")

    def test_play_disabled_event(self):
        """测试事件禁用时不播放"""
        config = {"enabled": True, "events": {"stack": False}}
        player = VoicePlayer(config)
        player.play("stack")

    def test_play_unknown_event_type(self):
        """测试未知事件类型不报错"""
        player = VoicePlayer()
        # 未知事件类型没有映射，应静默跳过
        player.play("totally_unknown")

    def test_play_file_not_exists(self):
        """测试语音文件不存在时不报错"""
        player = VoicePlayer({"resources_dir": "/nonexistent/path"})
        player.play("stack")

    def test_event_voice_map_completeness(self):
        """测试事件类型映射表完整性"""
        expected_events = {
            "game_start", "stack", "rune_mid", "rune_bounty",
            "rune_wisdom", "rune_lotus", "neutral", "daytime",
            "nighttime", "roshan", "tormentor", "shard", "ward_purchase",
        }
        assert set(VoicePlayer.EVENT_VOICE_MAP.keys()) == expected_events

    def test_event_voice_map_values(self):
        """测试映射的语音文件名正确"""
        assert VoicePlayer.EVENT_VOICE_MAP["stack"] == "alarm_stack.wav"
        assert VoicePlayer.EVENT_VOICE_MAP["rune_mid"] == "alarm_mid_runes.wav"
        assert VoicePlayer.EVENT_VOICE_MAP["roshan"] == "alarm_roshan.wav"
        assert VoicePlayer.EVENT_VOICE_MAP["game_start"] == "prologue.wav"


class TestVoicePlayerControl:
    """VoicePlayer 控制方法测试"""

    def test_set_enabled(self):
        """测试设置全局启用状态"""
        player = VoicePlayer()
        player.set_enabled(False)
        assert player._enabled is False
        player.set_enabled(True)
        assert player._enabled is True

    def test_set_volume(self):
        """测试设置音量"""
        player = VoicePlayer()
        player.set_volume(0.3)
        assert player._volume == 0.3

    def test_set_volume_clamp(self):
        """测试音量超出范围时裁剪"""
        player = VoicePlayer()
        player.set_volume(1.5)
        assert player._volume == 1.0
        player.set_volume(-0.5)
        assert player._volume == 0.0

    def test_set_event_enabled(self):
        """测试设置事件类型启用状态"""
        player = VoicePlayer()
        player.set_event_enabled("stack", False)
        assert player._event_settings["stack"] is False
        player.set_event_enabled("stack", True)
        assert player._event_settings["stack"] is True

    def test_get_status(self):
        """测试获取播放器状态"""
        config = {
            "enabled": True,
            "volume": 0.6,
            "events": {"stack": True, "rune_mid": False},
        }
        player = VoicePlayer(config)
        status = player.get_status()

        assert status["enabled"] is True
        assert status["volume"] == 0.6
        assert status["event_settings"]["stack"] is True
        assert status["event_settings"]["rune_mid"] is False
        assert "pygame_available" in status
        assert isinstance(status["pygame_available"], bool)

    def test_get_status_returns_copy(self):
        """测试 get_status 返回的是副本，修改不影响内部状态"""
        player = VoicePlayer({"events": {"stack": True}})
        status = player.get_status()
        status["event_settings"]["stack"] = False
        # 内部状态不应改变
        assert player._event_settings["stack"] is True


class TestVoicePlayerPygameMock:
    """使用 mock 测试 pygame 播放逻辑"""

    @patch("utils.voice_player._PYGAME_AVAILABLE", True)
    @patch("os.path.exists", return_value=True)
    def test_play_calls_pygame(self, mock_exists):
        """测试播放时调用 pygame"""
        # 创建 pygame mock
        mock_pygame = MagicMock()
        mock_sound = MagicMock()
        mock_pygame.mixer.Sound.return_value = mock_sound
        
        with patch.dict('sys.modules', {'pygame': mock_pygame, 'pygame.mixer': mock_pygame.mixer}):
            config = {"enabled": True, "volume": 0.8, "resources_dir": "resources/voice"}
            player = VoicePlayer(config)
            player._pygame_available = True
            
            # 手动注入 mock pygame 到 player 的命名空间
            import utils.voice_player as vp_module
            original_pygame = getattr(vp_module, 'pygame', None)
            vp_module.pygame = mock_pygame
            
            try:
                player.play("stack")
                
                mock_pygame.mixer.Sound.assert_called_once_with(
                    os.path.join("resources/voice", "alarm_stack.wav")
                )
                mock_sound.set_volume.assert_called_once_with(0.8)
                mock_sound.play.assert_called_once()
            finally:
                # 恢复原始状态
                if original_pygame is not None:
                    vp_module.pygame = original_pygame
                elif hasattr(vp_module, 'pygame'):
                    delattr(vp_module, 'pygame')

    def test_play_pygame_unavailable(self):
        """测试 pygame 不可用时 play 静默跳过"""
        player = VoicePlayer()
        player._pygame_available = False
        # 不应抛出异常
        player.play("stack")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
