from collections.abc import Generator
from typing import Any
import re
import json
import pandas as pd
import records
from sqlalchemy import text
from dify_plugin import Tool
from dify_plugin.entities.tool import ToolInvokeMessage
from tools.db_utils import fix_db_uri_encoding

class SQLExecuteTool(Tool):
    def _invoke(self, tool_parameters: dict[str, Any]) -> Generator[ToolInvokeMessage]:
        db_uri = tool_parameters.get("db_uri") or self.runtime.credentials.get("db_uri")
        if not db_uri:
            raise ValueError("Database URI is not provided.")
        
        # 修复 db_uri 中的特殊字符编码问题
        db_uri = fix_db_uri_encoding(db_uri)
        
        query = tool_parameters.get("query").strip()
        format = tool_parameters.get("format", "json")
        config_options = tool_parameters.get("config_options") or "{}"
        try:
            config_options = json.loads(config_options)
        except json.JSONDecodeError:
            raise ValueError("Invalid JSON format for Connect Config")
        db = records.Database(db_uri, **config_options)

        try:
            if re.match(r'^\s*(SELECT|WITH)\s+', query, re.IGNORECASE):
                # 查询字段类型
                table_name = re.search(r'FROM\s+([^\s;]+)', query, re.IGNORECASE)
                column_types = {}
                if table_name:
                    type_query = f"""
                    SELECT COLUMN_NAME, DATA_TYPE, CHARACTER_MAXIMUM_LENGTH
                    FROM INFORMATION_SCHEMA.COLUMNS
                    WHERE TABLE_NAME = '{table_name.group(1)}'
                    """
                    types_rows = db.query(type_query)
                    column_types = {row['COLUMN_NAME']: {
                        'DATA_TYPE': row['DATA_TYPE'],
                        'CHARACTER_MAXIMUM_LENGTH': row['CHARACTER_MAXIMUM_LENGTH']
                    } for row in types_rows.as_dict()}

                # 执行主查询
                rows = db.query(query)
                # 转换为 pandas DataFrame 并处理 NaN
                df = pd.DataFrame(rows.as_dict())
                df = df.fillna('')  # 替换 NaN 为空字符串

                if format == "json":
                    result = df.to_dict(orient='records')
                    yield self.create_json_message({"result": result, "column_types": column_types})
                elif format == "md":
                    result = str(rows.dataset)
                    yield self.create_text_message(result)
                elif format == "csv":
                    result = df.to_csv(index=False).encode()
                    yield self.create_blob_message(
                        result, meta={"mime_type": "text/csv", "filename": "result.csv"}
                    )
                elif format == "yaml":
                    result = df.to_dict(orient='records')
                    result = json.dumps(result, ensure_ascii=False).encode()
                    yield self.create_blob_message(
                        result, meta={"mime_type": "text/yaml", "filename": "result.yaml"}
                    )
                elif format == "xlsx":
                    output_file = '/tmp/output.xlsx'
                    df.to_excel(output_file, index=False)
                    with open(output_file, 'rb') as f:
                        result = f.read()
                    yield self.create_blob_message(
                        result,
                        meta={
                            "mime_type": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                            "filename": "result.xlsx"
                        }
                    )
                elif format == "html":
                    result = df.to_html(index=False).encode()
                    yield self.create_blob_message(
                        result, meta={"mime_type": "text/html", "filename": "result.html"}
                    )
                else:
                    raise ValueError(f"Unsupported format: {format}")
            else:
                with db.get_connection() as conn:
                    trans = conn._conn.begin()
                    try:
                        result = conn._conn.execute(text(query))
                        affected_rows = result.rowcount
                        trans.commit()
                        yield self.create_text_message(
                            f"Query executed successfully. Affected rows: {affected_rows}"
                        )
                    except Exception as e:
                        trans.rollback()
                        yield self.create_text_message(f"Error: {str(e)}")
        finally:
            db.close()
