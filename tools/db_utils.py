"""
数据库工具函数
"""
import re
from urllib.parse import quote_plus


def fix_db_uri_encoding(db_uri: str) -> str:
    """
    修复数据库 URI 中的特殊字符编码问题
    特别是处理密码中包含 @ 符号的情况
    
    Args:
        db_uri: 原始数据库 URI
        
    Returns:
        修复后的数据库 URI
        
    Examples:
        >>> fix_db_uri_encoding("postgresql://user:pass@word@localhost:5432/db")
        'postgresql://user:pass%40word@localhost:5432/db'
        
        >>> fix_db_uri_encoding("mysql://user:pass+word@localhost:3306/db")
        'mysql://user:pass%2Bword@localhost:3306/db'
    """
    try:
        # 使用更精确的正则表达式来解析数据库 URI
        # 格式: scheme://username:password@host:port/database
        import re
        
        # 匹配数据库 URI 的正则表达式
        # 使用非贪婪匹配来正确处理密码中的 @ 符号
        pattern = r'^([^:]+)://([^:]+):(.+)@([^:]+):(\d+)/(.+)$'
        match = re.match(pattern, db_uri)
        
        if match:
            scheme, username, password, host, port, database = match.groups()
            
            # 对用户名和密码进行 URL 编码
            encoded_username = quote_plus(username)
            encoded_password = quote_plus(password)
            
            # 重建 URI
            fixed_uri = f"{scheme}://{encoded_username}:{encoded_password}@{host}:{port}/{database}"
            return fixed_uri
        else:
            # 如果没有匹配到标准格式，尝试其他格式
            # 处理没有端口号的情况
            pattern_no_port = r'^([^:]+)://([^:]+):(.+)@([^/]+)/(.+)$'
            match = re.match(pattern_no_port, db_uri)
            
            if match:
                scheme, username, password, host, database = match.groups()
                
                # 对用户名和密码进行 URL 编码
                encoded_username = quote_plus(username)
                encoded_password = quote_plus(password)
                
                # 重建 URI
                fixed_uri = f"{scheme}://{encoded_username}:{encoded_password}@{host}/{database}"
                return fixed_uri
            else:
                # 如果都不匹配，返回原始 URI
                return db_uri
                
    except Exception:
        # 如果解析失败，返回原始 URI
        return db_uri


def is_clickhouse_uri(db_uri: str) -> bool:
    """
    检查是否为 ClickHouse/MyScale 数据库 URI

    Args:
        db_uri: 数据库 URI

    Returns:
        bool: 是否为 ClickHouse URI
    """
    return db_uri.startswith(('clickhouse://', 'clickhouse+connect://', 'myscale://', 'myscale+connect://'))


def parse_clickhouse_uri(db_uri: str) -> dict:
    """
    解析 ClickHouse/MyScale 连接字符串

    Args:
        db_uri: ClickHouse/MyScale URI，格式如:
                clickhouse://user:password@host:port/database
                clickhouse+connect://user:password@host:port/database
                myscale://user:password@host:port/database
                myscale+connect://user:password@host:port/database

    Returns:
        dict: 包含连接参数的字典
    """
    try:
        # 移除协议前缀
        if db_uri.startswith('clickhouse+connect://'):
            db_uri = db_uri.replace('clickhouse+connect://', '')
        elif db_uri.startswith('clickhouse://'):
            db_uri = db_uri.replace('clickhouse://', '')
        elif db_uri.startswith('myscale+connect://'):
            db_uri = db_uri.replace('myscale+connect://', '')
        elif db_uri.startswith('myscale://'):
            db_uri = db_uri.replace('myscale://', '')

        # 解析用户名、密码、主机、端口、数据库
        if '@' in db_uri:
            auth_part, host_part = db_uri.split('@', 1)

            # 解析用户名和密码
            if ':' in auth_part:
                username, password = auth_part.split(':', 1)
            else:
                username, password = auth_part, ''

            # 解析主机、端口和数据库
            if '/' in host_part:
                host_db_part = host_part.split('/', 1)
                host_port = host_db_part[0]
                database = host_db_part[1] if len(host_db_part) > 1 else 'default'
            else:
                host_port = host_part
                database = 'default'

            # 解析主机和端口
            if ':' in host_port:
                host, port = host_port.split(':', 1)
            else:
                host = host_port
                port = 8123  # ClickHouse 默认端口

            return {
                'host': host,
                'port': int(port),
                'username': username,
                'password': password,
                'database': database
            }
        else:
            # 没有认证信息的情况
            if '/' in db_uri:
                host_db_part = db_uri.split('/', 1)
                host_port = host_db_part[0]
                database = host_db_part[1] if len(host_db_part) > 1 else 'default'
            else:
                host_port = db_uri
                database = 'default'

            if ':' in host_port:
                host, port = host_port.split(':', 1)
            else:
                host = host_port
                port = 8123

            return {
                'host': host,
                'port': int(port),
                'username': 'default',
                'password': '',
                'database': database
            }
    except Exception:
        # 解析失败时返回默认配置
        return {
            'host': 'localhost',
            'port': 8123,
            'username': 'default',
            'password': '',
            'database': 'default'
        } 