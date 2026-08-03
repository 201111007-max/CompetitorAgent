"""pytest 配置 - 确保 competitor_agent 作为顶级包可导入"""
import sys
from pathlib import Path

_pkg_root = Path(__file__).parent.parent
if str(_pkg_root) not in sys.path:
    sys.path.insert(0, str(_pkg_root))