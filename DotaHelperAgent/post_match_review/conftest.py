"""pytest 配置 - 拦截父包导入

这个 conftest.py 在 pytest 收集测试之前执行，
通过预填充 sys.modules 来阻止 DotaHelperAgent/__init__.py 被加载。
"""
import sys
from pathlib import Path

# 将 post_match_review 目录添加到 sys.path
_pmr_root = Path(__file__).parent
if str(_pmr_root) not in sys.path:
    sys.path.insert(0, str(_pmr_root))

# 预填充 sys.modules 以阻止 DotaHelperAgent.__init__ 被加载
# 这是必要的，因为 DotaHelperAgent.__init__ 导入了许多有问题的依赖
if "DotaHelperAgent" not in sys.modules:
    import types
    mock_parent = types.ModuleType("DotaHelperAgent")
    mock_parent.__path__ = [str(_pmr_root)]
    mock_parent.__package__ = "DotaHelperAgent"
    sys.modules["DotaHelperAgent"] = mock_parent
