from collections.abc import Generator
from typing import Any
import json

from sqlalchemy import create_engine, inspect
from dify_plugin import Tool
from dify_plugin.entities.tool import ToolInvokeMessage
from tools.db_utils import fix_db_uri_encoding, is_clickhouse_uri, parse_clickhouse_uri


class QueryTool(Tool):
    def _invoke(self, tool_parameters: dict[str, Any]) -> Generator[ToolInvokeMessage]:
        db_uri = tool_parameters.get("db_uri") or self.runtime.credentials.get("db_uri")
        if not db_uri:
            raise ValueError("Database URI is not provided.")

        tables = tool_parameters.get("tables")
        schema = tool_parameters.get("schema")
        if not schema:
            # sometimes the schema is empty string, it must be None
            schema = None

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

            return self._get_clickhouse_schema(config, tables, schema)
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

            return self._get_sqlalchemy_schema(inspector, engine, tables, schema)

    def _get_clickhouse_schema(self, config: dict, tables: str, schema: str) -> Generator[ToolInvokeMessage]:
        """获取 ClickHouse/MyScale 表结构"""
        try:
            import clickhouse_connect

            client = clickhouse_connect.get_client(**config)

            try:
                # 获取所有表名或使用指定的表名
                if not tables:
                    # 查询所有表名
                    tables_query = "SELECT name FROM system.tables WHERE database = currentDatabase()"
                    result = client.query(tables_query)
                    tables_list = [row[0] for row in result.result_rows]
                else:
                    tables_list = [t.strip() for t in tables.split(",")]

                schema_info = {}

                for table_name in tables_list:
                    try:
                        # 获取表结构信息
                        columns_query = f"""
                        SELECT
                            name,
                            type,
                            is_in_primary_key,
                            is_in_sorting_key,
                            is_in_partition_key,
                            comment
                        FROM system.columns
                        WHERE database = currentDatabase() AND table = '{table_name}'
                        ORDER BY position
                        """

                        columns_result = client.query(columns_query)

                        table_info = {
                            "table_name": table_name,
                            "columns": [],
                            "primary_keys": [],
                            "sorting_keys": [],
                            "partition_keys": [],
                            "engine": "",
                            "comment": ""
                        }

                        # 获取表的引擎和注释
                        try:
                            table_query = f"""
                            SELECT engine, comment
                            FROM system.tables
                            WHERE database = currentDatabase() AND name = '{table_name}'
                            """
                            table_result = client.query(table_query)
                            if table_result.result_rows:
                                row = table_result.result_rows[0]
                                table_info["engine"] = row[0]
                                table_info["comment"] = row[1] or ""
                        except Exception:
                            pass

                        # 处理列信息
                        for row in columns_result.result_rows:
                            column_info = {
                                "name": row[0],
                                "type": row[1],
                                "nullable": "Nullable" in str(row[1]),
                                "default": None,
                                "comment": row[5] or ""
                            }
                            table_info["columns"].append(column_info)

                            if row[2]:  # is_in_primary_key
                                table_info["primary_keys"].append(row[0])
                            if row[3]:  # is_in_sorting_key
                                table_info["sorting_keys"].append(row[0])
                            if row[4]:  # is_in_partition_key
                                table_info["partition_keys"].append(row[0])

                        schema_info[table_name] = table_info

                    except Exception as e:
                        schema_info[table_name] = f"Error getting table schema: {str(e)}"

                yield self.create_text_message(json.dumps(schema_info, ensure_ascii=False))

            finally:
                client.close()

        except ImportError:
            raise ValueError("ClickHouse driver (clickhouse-connect) is not installed. Please add it to requirements.txt")
        except Exception as e:
            yield self.create_text_message(f"Error: {str(e)}")

    def _get_sqlalchemy_schema(self, inspector, engine, tables: str, schema: str) -> Generator[ToolInvokeMessage]:
        """获取 SQLAlchemy 支持的数据库表结构"""
        tables = tables.split(",") if tables else inspector.get_table_names(schema=schema)

        schema_info = {}
        with engine.connect() as _:
            for table_name in tables:
                # Basic table info
                table_info = {
                    "table_name": table_name,
                    "columns": [],
                    "primary_keys": inspector.get_pk_constraint(table_name, schema=schema).get('constrained_columns', []),
                    "foreign_keys": [],
                    "indexes": []
                }
                
                # Get table comment
                try:
                    table_info["comment"] = inspector.get_table_comment(table_name, schema=schema).get('text', '')
                except NotImplementedError:
                    table_info["comment"] = ""
                
                # Get foreign keys
                try:
                    for fk in inspector.get_foreign_keys(table_name, schema=schema):
                        table_info["foreign_keys"].append({
                            "referred_table": fk['referred_table'],
                            "referred_columns": fk['referred_columns'],
                            "constrained_columns": fk['constrained_columns']
                        })
                except NotImplementedError:
                    pass
                
                # Get indexes
                try:
                    for idx in inspector.get_indexes(table_name, schema=schema):
                        table_info["indexes"].append({
                            "name": idx['name'],
                            "columns": idx['column_names'],
                            "unique": idx['unique']
                        })
                except NotImplementedError:
                    pass
                
                # Get columns
                try:
                    columns = inspector.get_columns(table_name, schema=schema)
                    table_info["columns"] = [
                        {
                            "name": col["name"],
                            "type": str(col["type"]),
                            "nullable": col.get("nullable", True),
                            "default": col.get("default"),
                            "comment": col.get("comment", ""),
                        }
                        for col in columns
                    ]
                    
                    schema_info[table_name] = table_info
                except Exception as e:
                    schema_info[table_name] = f"Error getting schema: {str(e)}"
        yield self.create_text_message(json.dumps(schema_info, ensure_ascii=False))
