"""
测试运行脚本 - 快速验证测试套件

使用方法:
    python run_tests.py
    
或者直接使用 pytest:
    pytest tests/ -v
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
    print(f"Running: {description}")
    print(f"Command: {' '.join(command)}\n")
    
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            cwd=str(Path(__file__).parent)
        )
        
        if result.returncode == 0:
            print(f"[PASS] {description} - Success")
            return True
        else:
            print(f"[FAIL] {description} - Failed")
            print(result.stdout)
            print(result.stderr)
            return False
    except Exception as e:
        print(f"[FAIL] {description} - Exception: {e}")
        return False


def main():
    """主函数"""
    print_header("DotaHelperAgent Test Suite")
    
    # 检查 pytest 是否安装
    print("Checking pytest installation...")
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "--version"],
        capture_output=True,
        text=True
    )
    
    if result.returncode != 0:
        print("[FAIL] pytest not installed")
        print("\nPlease install: pip install pytest")
        sys.exit(1)
    
    print(f"[OK] pytest installed: {result.stdout.strip()}\n")
    
    # 测试目录列表（按模块划分）
    test_dirs = [
        ("api/", "API Tests"),
        ("core/", "Core Tests"),
        ("unit/", "Unit Tests"),
        ("e2e/", "E2E Tests"),
    ]
    
    print_header("Running Test Suite by Module")
    
    # 运行所有测试
    command = [
        sys.executable,
        "-m",
        "pytest",
        "api/", "core/", "unit/", "e2e/",
        "-v",
        "--tb=short"
    ]
    
    success = run_command(command, "Complete Test Suite")
    
    if success:
        print_header("[SUCCESS] All Tests Passed")
        print("Test suite is working correctly!")
        print("\nTips:")
        print("  - Run specific module: pytest api/ -v")
        print("  - Run specific test: pytest api/test_web_api.py -v")
        print("  - Check coverage: pytest --cov=agents/DotaHelperAgent tests/")
        print("  - Generate HTML report: pytest --html=report.html tests/")
    else:
        print_header("[WARNING] Some Tests Failed")
        print("Please check the error messages above")
        
        sys.exit(0 if success else 1)
        sys.exit(1)


if __name__ == "__main__":
    main()
