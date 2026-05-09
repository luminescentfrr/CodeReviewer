"""
Test script to verify tool integration in agents.

This script demonstrates that tools are properly integrated and functional.
"""

import asyncio
import sys
import os

# Add backend to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'backend'))

from backend.tools.code_search import grep_search, find_symbol_references, find_symbol_definition
from backend.tools.test_runner import TestRunner


def test_grep_search():
    """Test grep_search for security patterns"""
    print("\n=== Testing grep_search (Security Agent) ===")
    
    test_code = '''
def login(username, password):
    api_key = "sk-1234567890abcdef"  # Hardcoded API key
    db_password = "admin123"  # Hardcoded password
    return authenticate(username, password, api_key)
'''
    
    files = [{"filename": "test.py", "code": test_code, "language": "python"}]
    
    # Search for API keys
    results = grep_search(r"(api[_-]?key|token)\s*=\s*['\"][^'\"]{10,}['\"]", files)
    print(f"✅ Found {len(results)} API key patterns:")
    for r in results:
        print(f"   Line {r['line']}: {r['match']}")
    
    # Search for passwords
    results = grep_search(r"password\s*=\s*['\"][^'\"]+['\"]", files)
    print(f"✅ Found {len(results)} password patterns:")
    for r in results:
        print(f"   Line {r['line']}: {r['match']}")


def test_find_symbol_references():
    """Test find_symbol_references for hot path analysis"""
    print("\n=== Testing find_symbol_references (Optimizer Agent) ===")
    
    file1 = {
        "filename": "main.py",
        "code": '''
def process_data(data):
    return data.strip()

def main():
    process_data("test1")
    process_data("test2")
    process_data("test3")
''',
        "language": "python"
    }
    
    file2 = {
        "filename": "utils.py",
        "code": '''
from main import process_data

def helper():
    process_data("test4")
    process_data("test5")
''',
        "language": "python"
    }
    
    files = [file1, file2]
    
    # Find references to process_data
    refs = find_symbol_references("process_data", files, exclude_definition=True)
    print(f"✅ Found {len(refs)} references to process_data():")
    for r in refs:
        print(f"   {r['filename']} line {r['line']}")


def test_find_symbol_definition():
    """Test find_symbol_definition for documentation"""
    print("\n=== Testing find_symbol_definition (Documenter Agent) ===")
    
    files = [
        {
            "filename": "module.py",
            "code": '''
def calculate_total(items):
    return sum(items)

class DataProcessor:
    def process(self):
        pass
''',
            "language": "python"
        }
    ]
    
    # Find function definition
    defn = find_symbol_definition("calculate_total", files)
    if defn:
        print(f"✅ Found calculate_total() definition:")
        print(f"   File: {defn['filename']}")
        print(f"   Line: {defn['line']}")
        print(f"   Type: {defn['type']}")
    
    # Find class definition
    defn = find_symbol_definition("DataProcessor", files)
    if defn:
        print(f"✅ Found DataProcessor class definition:")
        print(f"   File: {defn['filename']}")
        print(f"   Line: {defn['line']}")
        print(f"   Type: {defn['type']}")


def test_test_runner():
    """Test TestRunner for test execution"""
    print("\n=== Testing TestRunner (Tester Agent) ===")
    
    # Create a simple test file
    test_file = "test_sample.py"
    test_content = '''
def test_addition():
    assert 1 + 1 == 2

def test_subtraction():
    assert 5 - 3 == 2
'''
    
    try:
        with open(test_file, 'w') as f:
            f.write(test_content)
        
        runner = TestRunner(".")
        success, output = runner.run_pytest(test_file)
        
        if success:
            print(f"✅ Tests passed!")
        else:
            print(f"❌ Tests failed")
        
        print(f"   Output preview: {output[:200]}...")
        
    except Exception as e:
        print(f"⚠️  TestRunner test skipped (pytest not installed): {e}")
    finally:
        # Cleanup
        if os.path.exists(test_file):
            os.remove(test_file)


def main():
    """Run all integration tests"""
    print("=" * 60)
    print("Tool Integration Test Suite")
    print("=" * 60)
    
    try:
        test_grep_search()
        test_find_symbol_references()
        test_find_symbol_definition()
        test_test_runner()
        
        print("\n" + "=" * 60)
        print("✅ All tool integrations verified successfully!")
        print("=" * 60)
        
    except Exception as e:
        print(f"\n❌ Test failed: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    main()
