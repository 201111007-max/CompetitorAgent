"""pytest 配置 - 确保 dota_helper 作为顶级包可导入"""
import sys
from pathlib import Path

# 将 dota_helper 的父目录添加到 sys.path
# 这样 dota_helper 会成为顶级包可正确导入
_pkg_root = Path(__file__).parent.parent
if str(_pkg_root) not in sys.path:
    sys.path.insert(0, str(_pkg_root))
