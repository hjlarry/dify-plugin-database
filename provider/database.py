from typing import Any

from dify_plugin import ToolProvider
from dify_plugin.errors.tool import ToolProviderCredentialValidationError
from tools.sql_execute import SQLExecuteTool
from tools.db_utils import is_clickhouse_uri, parse_clickhouse_uri


class DatabaseProvider(ToolProvider):
    def _validate_credentials(self, credentials: dict[str, Any]) -> None:
        if not credentials.get("db_uri"):
            return

        db_uri = credentials.get("db_uri")

        # 对于 ClickHouse/MyScale，使用原生验证
        if is_clickhouse_uri(db_uri):
            try:
                import clickhouse_connect

                config = parse_clickhouse_uri(db_uri)

                # 对于 8443 端口，自动添加 SSL 支持
                if config.get('port') == 8443:
                    config['secure'] = True

                # 尝试建立连接并执行测试查询
                client = clickhouse_connect.get_client(**config)
                client.command("SELECT 1")
                client.close()

            except ImportError:
                raise ToolProviderCredentialValidationError("ClickHouse driver (clickhouse-connect) is not installed")
            except Exception as e:
                raise ToolProviderCredentialValidationError(f"ClickHouse connection failed: {str(e)}")
        else:
            # 对于其他数据库，使用原有的验证逻辑
            query = "SELECT 1 FROM DUAL" if "oracle" in db_uri else "SELECT 1"
            try:
                for _ in SQLExecuteTool.from_credentials(credentials).invoke(
                    tool_parameters={"query": query}
                ):
                    pass
            except Exception as e:
                raise ToolProviderCredentialValidationError(str(e))
