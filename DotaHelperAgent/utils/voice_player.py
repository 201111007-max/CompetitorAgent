"""语音播放器模块 - 负责游戏事件的语音提醒"""

import os
import logging
from typing import Dict, Any, Optional

logger = logging.getLogger(__name__)

# 尝试导入 pygame，失败时静默降级
try:
    import pygame.mixer
    _PYGAME_AVAILABLE = True
except ImportError:
    _PYGAME_AVAILABLE = False
    logger.debug("pygame 未安装，语音播放功能将禁用")


class VoicePlayer:
    """语音播放器 - 负责音频播放"""
    
    # 事件类型到语音文件的映射
    EVENT_VOICE_MAP = {
        "game_start": "prologue.wav",
        "stack": "alarm_stack.wav",
        "rune_mid": "alarm_mid_runes.wav",
        "rune_bounty": "alarm_bounty_runes.wav",
        "rune_wisdom": "alarm_wisdom_runes.wav",
        "rune_lotus": "alarm_lotus.wav",
        "neutral": "alarm_neutral_items.wav",
        "daytime": "alarm_daytime.wav",
        "nighttime": "alarm_night_time.wav",
        "roshan": "alarm_roshan.wav",
        "tormentor": "alarm_first_tormentor.wav",
        "shard": "alarm_shard.wav",
        "ward_purchase": "alarm_ward_purchase.wav",
    }
    
    def __init__(self, config: Optional[Dict[str, Any]] = None):
        """
        初始化播放器
        
        Args:
            config: 配置字典，包含：
                - enabled: 是否启用语音（默认 True）
                - volume: 音量 0.0-1.0（默认 0.7）
                - resources_dir: 语音文件目录（默认 "resources/voice"）
                - events: 各事件类型的启用状态字典
        """
        self._config = config or {}
        self._enabled = self._config.get("enabled", True)
        self._volume = self._config.get("volume", 0.7)
        self._resources_dir = self._config.get("resources_dir", "resources/voice")
        self._event_settings = self._config.get("events", {})
        
        # pygame 可用性
        self._pygame_available = _PYGAME_AVAILABLE
        
        # 初始化 pygame.mixer
        if self._pygame_available:
            try:
                pygame.mixer.init()
                logger.info("pygame.mixer 初始化成功")
            except Exception as e:
                logger.warning(f"pygame.mixer 初始化失败: {e}")
                self._pygame_available = False
        
        logger.info(
            f"VoicePlayer 初始化完成 - enabled: {self._enabled}, "
            f"volume: {self._volume}, pygame: {self._pygame_available}"
        )
    
    def play(self, event_type: str) -> None:
        """
        播放指定事件类型的语音
        
        Args:
            event_type: 事件类型（如 "stack", "rune_mid", "roshan"）
        """
        # 检查 pygame 可用性
        if not self._pygame_available:
            return
        
        # 检查全局启用状态
        if not self._enabled:
            return
        
        # 检查该事件类型是否启用
        event_enabled = self._event_settings.get(event_type, True)
        if not event_enabled:
            return
        
        # 获取语音文件
        voice_file = self.EVENT_VOICE_MAP.get(event_type)
        if not voice_file:
            logger.debug(f"事件类型 {event_type} 没有对应的语音文件")
            return
        
        # 构建完整路径
        full_path = os.path.join(self._resources_dir, voice_file)
        
        # 检查文件是否存在
        if not os.path.exists(full_path):
            logger.warning(f"语音文件不存在: {full_path}")
            return
        
        # 播放语音
        try:
            sound = pygame.mixer.Sound(full_path)
            sound.set_volume(self._volume)
            sound.play()
            logger.debug(f"播放语音: {event_type} -> {voice_file}")
        except Exception as e:
            logger.error(f"播放语音失败: {e}")
    
    def set_enabled(self, enabled: bool) -> None:
        """运行时设置全局启用状态"""
        self._enabled = enabled
        logger.info(f"语音全局开关: {enabled}")
    
    def set_volume(self, volume: float) -> None:
        """运行时设置音量（0.0-1.0）"""
        self._volume = max(0.0, min(1.0, volume))
        logger.info(f"语音音量: {self._volume}")
    
    def set_event_enabled(self, event_type: str, enabled: bool) -> None:
        """运行时设置指定事件类型的启用状态"""
        self._event_settings[event_type] = enabled
        logger.info(f"事件 {event_type} 语音开关: {enabled}")
    
    def get_status(self) -> Dict[str, Any]:
        """
        获取播放器状态
        
        Returns:
            状态字典
        """
        return {
            "enabled": self._enabled,
            "volume": self._volume,
            "pygame_available": self._pygame_available,
            "event_settings": self._event_settings.copy(),
        }
