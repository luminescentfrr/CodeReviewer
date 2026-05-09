"""
测试工具调用可视化功能

这个脚本创建一个包含安全问题的测试文件，用于验证工具调用日志是否正确显示。
"""

test_code_with_security_issues = '''
def login_user(username, password):
    """用户登录函数"""
    # 硬编码的 API 密钥 - 应该被 grep_search 检测到
    api_key = "sk-1234567890abcdefghijklmnopqrstuvwxyz"
    
    # 硬编码的数据库密码 - 应该被 grep_search 检测到
    db_password = "admin123"
    
    # 数据库连接串 - 应该被 grep_search 检测到
    db_url = "mysql://root:password123@localhost:3306/mydb"
    
    # JWT 密钥 - 应该被 grep_search 检测到
    jwt_secret = "my-super-secret-jwt-key-12345"
    
    # 正常的业务逻辑
    if username and password:
        return authenticate(username, password, api_key)
    return False

def process_data(data):
    """处理数据 - 这个函数会被多次调用"""
    return data.strip().lower()

def validate_input(data):
    """验证输入"""
    return len(data) > 0

def main():
    # 多次调用 process_data - 应该被 find_symbol_references 检测到
    result1 = process_data("test1")
    result2 = process_data("test2")
    result3 = process_data("test3")
    result4 = process_data("test4")
    result5 = process_data("test5")
    
    # 调用 validate_input
    if validate_input(result1):
        print("Valid")
'''

# 保存测试文件
with open('test_security_sample.py', 'w', encoding='utf-8') as f:
    f.write(test_code_with_security_issues)

print("✅ 测试文件已创建: test_security_sample.py")
print("\n📋 这个文件包含以下安全问题（应该被工具检测到）:")
print("  1. 硬编码的 API 密钥 (第 5 行)")
print("  2. 硬编码的数据库密码 (第 8 行)")
print("  3. 数据库连接串 (第 11 行)")
print("  4. JWT 密钥 (第 14 行)")
print("\n📋 这个文件包含以下性能特征（应该被工具检测到）:")
print("  1. process_data() 被调用 5 次 - 应该显示为热点函数")
print("\n🚀 使用方法:")
print("  1. 启动应用: npm start")
print("  2. 在应用中打开 test_security_sample.py")
print("  3. 点击'开始审查'")
print("  4. 查看 AI 响应顶部的工具调用日志")
print("\n预期看到的工具调用:")
print("  🔍 搜索安全模式 • API密钥/Token")
print("  🔍 搜索安全模式 • 硬编码密码")
print("  🔍 搜索安全模式 • 数据库连接串")
print("  🔍 搜索安全模式 • JWT密钥")
print("  🔗 分析函数调用 • process_data()")
print("  🤖 调用 LLM 分析 • security agent")
print("  🤖 调用 LLM 分析 • optimizer agent")
