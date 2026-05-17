"""简单测试日志重构后的功能"""

import sys
from pathlib import Path

# 添加项目根目录到路径
project_root = Path(__file__).parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

def test_syntax():
    """测试语法是否正确"""
    print("="*60)
    print("测试 1: 语法检查")
    print("="*60)
    
    import ast
    
    files_to_check = [
        "core/agent_controller.py",
        "core/agent.py"
    ]
    
    all_passed = True
    for file_path in files_to_check:
        try:
            full_path = Path(__file__).parent / file_path
            with open(full_path, encoding='utf-8') as f:
                ast.parse(f.read())
            print(f"✓ {file_path} 语法正确")
        except SyntaxError as e:
            print(f"✗ {file_path} 语法错误: {e}")
            all_passed = False
    
    return all_passed

def test_logger_import():
    """测试 logger 导入"""
    print("\n" + "="*60)
    print("测试 2: Logger 导入")
    print("="*60)
    
    try:
        from utils.log_config import get_logger
        logger = get_logger("test", component="test")
        print("✓ Logger 导入成功")
        
        # 测试日志方法
        logger.info("测试信息日志")
        logger.warning("测试警告日志")
        logger.error("测试错误日志")
        print("✓ 日志方法调用成功")
        
        return True
    except Exception as e:
        print(f"✗ Logger 导入失败: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_code_structure():
    """测试代码结构"""
    print("\n" + "="*60)
    print("测试 3: 代码结构检查")
    print("="*60)
    
    try:
        # 检查 agent_controller.py
        with open("core/agent_controller.py", encoding='utf-8') as f:
            content = f.read()
            
        # 检查是否有 logger 导入
        if "from utils.log_config import get_logger" in content:
            print("✓ agent_controller.py 包含 logger 导入")
        else:
            print("✗ agent_controller.py 缺少 logger 导入")
            return False
        
        # 检查是否有 logger 使用
        if "logger.info_ctx" in content or "logger.warning_ctx" in content:
            print("✓ agent_controller.py 使用 logger 方法")
        else:
            print("✗ agent_controller.py 未使用 logger 方法")
            return False
        
        # 检查是否还有 print 语句（应该很少）
        import re
        print_count = len(re.findall(r'print\(', content))
        print(f"  agent_controller.py 中 print 语句数量: {print_count}")
        
        # 检查 agent.py
        with open("core/agent.py", encoding='utf-8') as f:
            agent_content = f.read()
        
        # 检查是否有 logger 导入
        if "from utils.log_config import get_logger" in agent_content or \
           "from ..utils.log_config import get_logger" in agent_content:
            print("✓ agent.py 包含 logger 导入")
        else:
            print("✗ agent.py 缺少 logger 导入")
            return False
        
        # 检查是否有 logger 使用
        if "logger.info" in agent_content or "logger.warning" in agent_content:
            print("✓ agent.py 使用 logger 方法")
        else:
            print("✗ agent.py 未使用 logger 方法")
            return False
        
        # 检查是否还有 except: pass
        if "except Exception as e:\n            pass" in agent_content or \
           "except:\n            pass" in agent_content:
            print("✗ agent.py 仍有静默失败")
            return False
        else:
            print("✓ agent.py 无静默失败")
        
        return True
        
    except Exception as e:
        print(f"✗ 代码结构检查失败: {e}")
        import traceback
        traceback.print_exc()
        return False

def main():
    """运行所有测试"""
    print("\n日志重构验证测试")
    print("="*60)
    
    results = []
    results.append(("语法检查", test_syntax()))
    results.append(("Logger 导入", test_logger_import()))
    results.append(("代码结构", test_code_structure()))
    
    print("\n" + "="*60)
    print("测试结果汇总")
    print("="*60)
    
    passed = sum(1 for _, result in results if result)
    total = len(results)
    
    for name, result in results:
        status = "✓ 通过" if result else "✗ 失败"
        print(f"{name}: {status}")
    
    print(f"\n总计: {passed}/{total} 通过")
    
    if passed == total:
        print("\n✓ 所有测试通过！日志重构成功！")
        return 0
    else:
        print(f"\n✗ {total - passed} 个测试失败")
        return 1

if __name__ == "__main__":
    sys.exit(main())
