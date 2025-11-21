from collections.abc import Generator
from typing import Any
import re
import json

from sqlalchemy import create_engine, text
from dify_plugin import Tool
from dify_plugin.entities.tool import ToolInvokeMessage
from tools.db_utils import fix_db_uri_encoding, is_clickhouse_uri, parse_clickhouse_uri


class SQLExecuteTool(Tool):
    def _invoke(self, tool_parameters: dict[str, Any]) -> Generator[ToolInvokeMessage]:
        db_uri = tool_parameters.get("db_uri") or self.runtime.credentials.get("db_uri")
        if not db_uri:
            raise ValueError("Database URI is not provided.")

        query = tool_parameters.get("query").strip()
        format = tool_parameters.get("format", "json")
        config_options = tool_parameters.get("config_options") or "{}"

        # 检查是否为 ClickHouse/MyScale 数据库
        if is_clickhouse_uri(db_uri):
            # 处理 ClickHouse/MyScale 连接
            config = parse_clickhouse_uri(db_uri)

            # 解析额外的配置选项
            try:
                extra_options = json.loads(config_options)
                config.update(extra_options)
            except json.JSONDecodeError:
                raise ValueError("Invalid JSON format for Connect Config")

            return self._handle_clickhouse_query(config, query, format)
        else:
            # 处理其他数据库类型（原有逻辑）
            db_uri = fix_db_uri_encoding(db_uri)

            try:
                config_options = json.loads(config_options)
            except json.JSONDecodeError:
                raise ValueError("Invalid JSON format for Connect Config")
            engine = create_engine(db_uri, **config_options)

            return self._handle_sqlalchemy_query(engine, query, format)

    def _handle_clickhouse_query(self, config: dict, query: str, format: str) -> Generator[ToolInvokeMessage]:
        """处理 ClickHouse/MyScale 查询"""
        try:
            import clickhouse_connect

            # 建立 ClickHouse 连接
            client = clickhouse_connect.get_client(**config)

            try:
                # 检查查询类型
                if re.match(r'^\s*(SELECT|WITH|SHOW|DESCRIBE|EXISTS)\s+', query, re.IGNORECASE):
                    # 查询类语句
                    result = client.query(query)

                    if format == "json":
                        # 转换为 JSON 格式
                        data = []
                        for row in result.result_rows:
                            row_dict = {}
                            for i, column_name in enumerate(result.column_names):
                                value = row[i]
                                # 处理日期和其他不可序列化的类型
                                if hasattr(value, 'isoformat'):  # datetime/date 对象
                                    value = value.isoformat()
                                elif hasattr(value, '__str__'):  # 其他对象
                                    value = str(value)
                                row_dict[column_name] = value
                            data.append(row_dict)
                        yield self.create_json_message({"result": data})

                    elif format == "md":
                        # 生成 Markdown 表格
                        if result.column_names and result.result_rows:
                            # 表头
                            header = "| " + " | ".join(result.column_names) + " |"
                            separator = "| " + " | ".join(["---"] * len(result.column_names)) + " |"

                            # 数据行
                            rows = []
                            for row in result.result_rows:
                                row_str = "| " + " | ".join(str(cell) if cell is not None else "NULL" for cell in row) + " |"
                                rows.append(row_str)

                            markdown_table = "\n".join([header, separator] + rows)
                            yield self.create_text_message(markdown_table)
                        else:
                            yield self.create_text_message("Query returned no results")

                    elif format == "csv":
                        # 生成 CSV 格式
                        import io
                        import csv

                        output = io.StringIO()
                        writer = csv.writer(output)

                        # 写入表头
                        if result.column_names:
                            writer.writerow(result.column_names)

                        # 写入数据
                        for row in result.result_rows:
                            writer.writerow(row)

                        csv_data = output.getvalue()
                        yield self.create_blob_message(
                            csv_data.encode('utf-8'),
                            meta={"mime_type": "text/csv", "filename": "result.csv"}
                        )

                    elif format == "yaml":
                        # 生成 YAML 格式
                        import yaml

                        data = []
                        for row in result.result_rows:
                            row_dict = {}
                            for i, column_name in enumerate(result.column_names):
                                row_dict[column_name] = row[i]
                            data.append(row_dict)

                        yaml_data = yaml.dump({"result": data}, default_flow_style=False, allow_unicode=True)
                        yield self.create_blob_message(
                            yaml_data.encode('utf-8'),
                            meta={"mime_type": "text/yaml", "filename": "result.yaml"}
                        )

                    elif format == "xlsx":
                        # 生成 Excel 格式
                        import pandas as pd

                        # 创建 DataFrame
                        df = pd.DataFrame(result.result_rows, columns=result.column_names)

                        # 保存为 Excel
                        import io
                        output = io.BytesIO()
                        with pd.ExcelWriter(output, engine='openpyxl') as writer:
                            df.to_excel(writer, index=False, sheet_name='Results')

                        yield self.create_blob_message(
                            output.getvalue(),
                            meta={
                                "mime_type": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                                "filename": "result.xlsx",
                            },
                        )

                    elif format == "html":
                        # 生成 HTML 格式
                        html_data = "<table>\n"

                        # 表头
                        if result.column_names:
                            html_data += "<thead><tr>"
                            for col in result.column_names:
                                html_data += f"<th>{col}</th>"
                            html_data += "</tr></thead>\n"

                        # 数据
                        html_data += "<tbody>\n"
                        for row in result.result_rows:
                            html_data += "<tr>"
                            for cell in row:
                                html_data += f"<td>{cell if cell is not None else 'NULL'}</td>"
                            html_data += "</tr>\n"
                        html_data += "</tbody>\n</table>"

                        yield self.create_blob_message(
                            html_data.encode('utf-8'),
                            meta={"mime_type": "text/html", "filename": "result.html"},
                        )

                    else:
                        raise ValueError(f"Unsupported format: {format}")

                else:
                    # 非查询语句（INSERT, UPDATE, DELETE, CREATE, DROP, etc.）
                    command_result = client.command(query)
                    affected_rows = command_result if isinstance(command_result, int) else 0
                    yield self.create_text_message(
                        f"Query executed successfully. Affected rows: {affected_rows}"
                    )

            finally:
                client.close()

        except ImportError:
            raise ValueError("ClickHouse driver (clickhouse-connect) is not installed. Please add it to requirements.txt")
        except Exception as e:
            yield self.create_text_message(f"Error: {str(e)}")

    def _handle_sqlalchemy_query(self, engine, query: str, format: str) -> Generator[ToolInvokeMessage]:
        """处理 SQLAlchemy 支持的数据库查询"""
        try:
            with engine.connect() as conn:
                if re.match(r'^\s*(SELECT|WITH)\s+', query, re.IGNORECASE):
                    # 查询语句
                    result = conn.execute(text(query))
                    rows = result.fetchall()
                    columns = result.keys()

                    if format == "json":
                        result_data = [dict(zip(columns, row)) for row in rows]
                        yield self.create_json_message({"result": result_data})
                    elif format == "md":
                        from tabulate import tabulate
                        if rows:
                            table = tabulate(rows, headers=columns, tablefmt="pipe")
                            yield self.create_text_message(table)
                        else:
                            yield self.create_text_message("Query returned no results")
                    elif format == "csv":
                        import io
                        import csv
                        output = io.StringIO()
                        writer = csv.writer(output)
                        writer.writerow(columns)
                        writer.writerows(rows)
                        csv_data = output.getvalue()
                        yield self.create_blob_message(
                            csv_data.encode('utf-8'),
                            meta={"mime_type": "text/csv", "filename": "result.csv"}
                        )
                    elif format == "yaml":
                        import yaml
                        result_data = [dict(zip(columns, row)) for row in rows]
                        yaml_data = yaml.dump({"result": result_data}, default_flow_style=False, allow_unicode=True)
                        yield self.create_blob_message(
                            yaml_data.encode('utf-8'),
                            meta={"mime_type": "text/yaml", "filename": "result.yaml"},
                        )
                    elif format == "xlsx":
                        import pandas as pd
                        df = pd.DataFrame(rows, columns=columns)
                        import io
                        output = io.BytesIO()
                        with pd.ExcelWriter(output, engine='openpyxl') as writer:
                            df.to_excel(writer, index=False, sheet_name='Results')
                        yield self.create_blob_message(
                            output.getvalue(),
                            meta={
                                "mime_type": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                                "filename": "result.xlsx",
                            },
                        )
                    elif format == "html":
                        html_data = "<table>\n"
                        if columns:
                            html_data += "<thead><tr>"
                            for col in columns:
                                html_data += f"<th>{col}</th>"
                            html_data += "</tr></thead>\n"
                        html_data += "<tbody>\n"
                        for row in rows:
                            html_data += "<tr>"
                            for cell in row:
                                html_data += f"<td>{cell if cell is not None else 'NULL'}</td>"
                            html_data += "</tr>\n"
                        html_data += "</tbody>\n</table>"
                        yield self.create_blob_message(
                            html_data.encode('utf-8'),
                            meta={"mime_type": "text/html", "filename": "result.html"},
                        )
                    else:
                        raise ValueError(f"Unsupported format: {format}")
                else:
                    # 非查询语句
                    trans = conn.begin()
                    try:
                        result = conn.execute(text(query))
                        affected_rows = result.rowcount
                        trans.commit()
                        yield self.create_text_message(
                            f"Query executed successfully. Affected rows: {affected_rows}"
                        )
                    except Exception as e:
                        trans.rollback()
                        yield self.create_text_message(f"Error: {str(e)}")
        finally:
            engine.dispose()
