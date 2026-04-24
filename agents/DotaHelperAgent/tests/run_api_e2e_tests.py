"""
API 集成测试和端到端测试运行脚本

快速运行新增的测试文件

使用方法:
    python run_api_e2e_tests.py
    
或者直接使用 pytest:
    pytest api/ e2e/ -v
"""

import subprocess
import sys
import shutil
from pathlib import Path


def print_header(text):
    """打印标题"""
    print("\n" + "=" * 70)
    print(text.center(70))
    print("=" * 70 + "\n")


def find_pytest():
    """查找 pytest 可执行文件"""
    # 方法 1: 使用 shutil.which 查找
    pytest_path = shutil.which('pytest')
    if pytest_path:
        return pytest_path
    
    # 方法 2: 使用 python -m pytest
    return None


def run_tests(test_path, description):
    """运行测试文件"""
    print(f"Running: {description}")
    print(f"Path: {test_path}")
    print("-" * 70)
    
    # 使用 python -m pytest 方式运行（最可靠）
    cmd = [
        sys.executable,
        "-m",
        "pytest",
        str(test_path),
        "-v",
        "--tb=short",
        "-s"  # 显示 print 输出
    ]
    
    result = subprocess.run(cmd, capture_output=True, text=True)
    
    print(result.stdout)
    
    if result.returncode == 0:
        print(f"[PASS] {description} - 全部通过")
    else:
        print(f"[FAIL] {description} - 部分失败")
        if result.stderr:
            print(result.stderr)
    
    print()
    return result.returncode == 0


def main():
    """主函数"""
    print_header("DotaHelperAgent API Integration & E2E Test Suite")
    
    # 测试目录列表（按模块划分）
    test_dirs = [
        ("api/", "API Integration Tests"),
        ("e2e/", "End-to-End Workflow Tests"),
    ]
    
    # 检查 pytest 是否安装 - 使用多种方式
    print("Checking pytest installation...")
    
    # 方式 1: 尝试 python -m pytest --version
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "--version"],
        capture_output=True,
        text=True
    )
    
    if result.returncode == 0:
        print(f"[OK] pytest installed: {result.stdout.strip()}\n")
    else:
        # 方式 2: 尝试直接调用 pytest
        pytest_path = shutil.which('pytest')
        if pytest_path:
            print(f"[OK] pytest installed: {pytest_path}\n")
        else:
            print("[FAIL] pytest not installed")
            print("\nPlease install pytest:")
            print(f"  {sys.executable} -m pip install pytest pytest-cov pytest-mock")
            print("\nOr use virtual environment:")
            print("  python -m venv venv")
            print("  venv\\Scripts\\activate  # Windows")
            print("  pip install pytest pytest-cov pytest-mock")
            sys.exit(1)
    
    # 运行测试
    results = []
    
    for test_dir, description in test_dirs:
        test_path = Path(__file__).parent / test_dir
        
        if not test_path.exists():
            print(f"[WARN] Test directory not found: {test_path}")
            continue
        
        success = run_tests(test_path, description)
        results.append((description, success))
    
    # 汇总结果
    print_header("Test Results Summary")
    
    for description, success in results:
        status = "[PASS]" if success else "[FAIL]"
        print(f"{status} {description}")
    
    all_passed = all(success for _, success in results)
    
    if all_passed:
        print("\n[SUCCESS] All tests passed!")
        print("\nTips:")
        print("  - Run specific test: pytest api/test_web_api.py::TestChatEndpoint -v")
        print("  - Check coverage: pytest --cov=agents/DotaHelperAgent tests/")
        print("  - Generate HTML report: pytest --html=report.html tests/")
        print("  - Run E2E tests only: pytest e2e/ -v")
        print("  - Run all tests: pytest tests/ -v")
        return 0
    else:
        print("\n[WARNING] Some tests failed, please check the error messages above")
        return 1


if __name__ == '__main__':
    exit_code = main()
    sys.exit(exit_code)
