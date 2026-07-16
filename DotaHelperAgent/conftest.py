"""根级 conftest - 修复 DotaHelperAgent 内部的裸导入路径"""
import sys
from pathlib import Path

# DotaHelperAgent 内部模块使用 `from utils.log_config import ...` 等裸导入,
# 需要将 DotaHelperAgent 目录加入 sys.path
_dota_root = Path(__file__).parent
if str(_dota_root) not in sys.path:
    sys.path.insert(0, str(_dota_root))
