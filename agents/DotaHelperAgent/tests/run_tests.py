"""
测试运行脚本 - 快速验证测试套件

使用方法:
    python run_tests.py
    
或者直接使用 pytest:
    pytest agents/DotaHelperAgent/tests/ -v
"""

import subprocess
import sys
from pathlib import Path


def print_header(text):
    """打印标题"""
    print("\n" + "=" * 60)
    print(text.center(60))
    print("=" * 60 + "\n")


def run_command(command, description):
    """运行命令并显示结果"""
    print(f"运行：{description}")
    print(f"命令：{' '.join(command)}\n")
    
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            cwd=str(Path(__file__).parent.parent)
        )
        
        if result.returncode == 0:
            print(f"✅ {description} - 成功")
            return True
        else:
            print(f"❌ {description} - 失败")
            print(result.stdout)
            print(result.stderr)
            return False
    except Exception as e:
        print(f"❌ {description} - 异常：{e}")
        return False


def main():
    """主函数"""
    print_header("DotaHelperAgent 测试套件验证")
    
    # 检查 pytest 是否安装
    print("检查 pytest 安装...")
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "--version"],
        capture_output=True,
        text=True
    )
    
    if result.returncode != 0:
        print("❌ pytest 未安装，请先安装：pip install pytest")
        sys.exit(1)
    
    print(f"✅ pytest 已安装：{result.stdout.strip()}")
    
    # 测试文件列表
    test_files = [
        "tests/test_agent.py",
        "tests/test_cache.py",
        "tests/test_config.py",
        "tests/test_strategies.py",
        "tests/test_analyzers.py",
        "tests/test_api_client.py",
    ]
    
    print_header("运行完整测试套件")
    
    # 运行所有测试
    command = [
        sys.executable,
        "-m",
        "pytest",
        "agents/DotaHelperAgent/tests/",
        "-v",
        "--tb=short"
    ]
    
    success = run_command(command, "完整测试套件")
    
    if success:
        print_header("✅ 所有测试通过")
        print("测试套件运行正常！")
        print("\n提示:")
        print("  - 运行特定测试：pytest tests/test_cache.py -v")
        print("  - 查看覆盖率：pytest --cov=agents/DotaHelperAgent tests/")
        print("  - 生成 HTML 报告：pytest --html=report.html tests/")
    else:
        print_header("❌ 部分测试失败")
        print("请查看上面的错误信息")
        sys.exit(1)


if __name__ == "__main__":
    main()
