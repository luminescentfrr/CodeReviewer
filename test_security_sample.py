
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
