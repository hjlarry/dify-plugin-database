from collections.abc import Generator
from typing import Any
import json
import re
from urllib.parse import quote_plus

from sqlalchemy import create_engine, inspect
from dify_plugin import Tool
from dify_plugin.entities.tool import ToolInvokeMessage
from dify_plugin.entities.model.message import SystemPromptMessage, UserPromptMessage
from tools.db_utils import fix_db_uri_encoding, is_clickhouse_uri, parse_clickhouse_uri

SYSTEM_PROMPT_TEMPLATE = """
You are a {dialect} expert. Your task is to generate an executable {dialect} query based on the user's question.

Requirements:
1. Generate a complete, executable {dialect} query that can be run directly
2. Query only necessary columns
3. Don't wrap column names in double quotes (") as delimited identifiers
4. Unless specified, limit results to 5 rows
5. Use date('now') for current date references
6. The response format should not include special characters like ```, \n, \", etc.

Query Guidelines:
- Ensure the query matches the exact {dialect} syntax
- Only use columns that exist in the provided tables
- Add appropriate table joins with correct join conditions
- Include WHERE clauses to filter data as needed
- Add ORDER BY when sorting is beneficial
- Use appropriate data type casting

Common Pitfalls to Avoid:
- NULL handling in NOT IN clauses
- UNION vs UNION ALL usage
- Exclusive range conditions
- Data type mismatches
- Missing or incorrect quotes around identifiers
- Wrong function arguments
- Incorrect join conditions
"""

USER_PROMPT_TEMPLATE = """
Context and Tables:
{table_info}

Examples:
User input: How many employees are there
Your response: SELECT COUNT(*) FROM "Employee"

User input: How many tracks are there in the album with ID 5?
Your response: SELECT COUNT(*) FROM Track WHERE AlbumId = 5;

User input: Which albums are from the year 2000?
Your response: SELECT * FROM Album WHERE strftime('%Y', ReleaseDate) = '2000';

User input: List all tracks in the 'Rock' genre.
Your response: SELECT * FROM Track WHERE GenreId = (SELECT GenreId FROM Genre WHERE Name = 'Rock');


Now, the user input is : {query}
"""


class QueryTool(Tool):
    def _invoke(self, tool_parameters: dict[str, Any]) -> Generator[ToolInvokeMessage]:
        db_uri = tool_parameters.get("db_uri") or self.runtime.credentials.get("db_uri")
        if not db_uri:
            raise ValueError("Database URI is not provided.")

        # 检查是否为 ClickHouse/MyScale 数据库
        if is_clickhouse_uri(db_uri):
            # 处理 ClickHouse/MyScale
            config = parse_clickhouse_uri(db_uri)
            config_options = tool_parameters.get("config_options") or "{}"
            try:
                extra_options = json.loads(config_options)
                config.update(extra_options)
            except json.JSONDecodeError:
                raise ValueError("Invalid JSON format for Connect Config")

            dialect = "clickhouse"  # 设置方言为 clickhouse
            schema_info = self._get_clickhouse_schema(config)
        else:
            # 处理其他数据库类型（原有逻辑）
            db_uri = fix_db_uri_encoding(db_uri)

            config_options = tool_parameters.get("config_options") or "{}"
            try:
                config_options = json.loads(config_options)
            except json.JSONDecodeError:
                raise ValueError("Invalid JSON format for Connect Config")
            engine = create_engine(db_uri, **config_options)
            inspector = inspect(engine)
            dialect = engine.dialect.name

            tables = tool_parameters.get("tables")
            tables = tables.split(",") if tables else inspector.get_table_names()

            schema_info = {}
            with engine.connect() as _:
                for table_name in tables:
                    try:
                        columns = inspector.get_columns(table_name)
                        schema_info[table_name] = [
                            {
                                "name": col["name"],
                                "type": str(col["type"]),
                                "nullable": col.get("nullable", True),
                                "default": col.get("default"),
                                "primary_key": col.get("primary_key", False),
                            }
                            for col in columns
                        ]
                    except Exception as e:
                        schema_info[table_name] = f"Error getting schema: {str(e)}"
        prompt_messages = [
            SystemPromptMessage(content=SYSTEM_PROMPT_TEMPLATE.format(dialect=dialect)),
            UserPromptMessage(
                content=USER_PROMPT_TEMPLATE.format(
                    table_info=schema_info, query=tool_parameters.get("query")
                )
            ),
        ]

        response = self.session.model.llm.invoke(
            model_config=tool_parameters.get("model"),
            prompt_messages=prompt_messages,
            stream=False,
        )
        yield self.create_text_message(response.message.content)

    def _get_clickhouse_schema(self, config: dict) -> dict:
        """获取 ClickHouse/MyScale 表结构信息"""
        schema_info = {}
        try:
            import clickhouse_connect

            client = clickhouse_connect.get_client(**config)

            try:
                # 获取所有表名
                tables_query = "SELECT name FROM system.tables WHERE database = currentDatabase()"
                result = client.query(tables_query)
                tables_list = [row[0] for row in result.result_rows]

                for table_name in tables_list:
                    try:
                        # 获取表结构信息
                        columns_query = f"""
                        SELECT
                            name,
                            type,
                            is_in_primary_key,
                            is_in_sorting_key,
                            comment
                        FROM system.columns
                        WHERE database = currentDatabase() AND table = '{table_name}'
                        ORDER BY position
                        """
                        columns_result = client.query(columns_query)

                        schema_info[table_name] = []
                        for row in columns_result.result_rows:
                            schema_info[table_name].append({
                                "name": row[0],
                                "type": str(row[1]),
                                "nullable": "Nullable" in str(row[1]),
                                "default": None,
                                "primary_key": row[2] if len(row) > 2 else False,
                            })

                    except Exception as e:
                        schema_info[table_name] = f"Error getting table schema: {str(e)}"

            finally:
                client.close()

        except ImportError:
            raise ValueError("ClickHouse driver (clickhouse-connect) is not installed")
        except Exception as e:
            # 如果连接失败，返回一个示例表结构
            return {
                "example_table": [
                    {
                        "name": "id",
                        "type": "UInt64",
                        "nullable": False,
                        "default": None,
                        "primary_key": True,
                    },
                    {
                        "name": "name",
                        "type": "String",
                        "nullable": True,
                        "default": None,
                        "primary_key": False,
                    }
                ]
            }

        return schema_info
