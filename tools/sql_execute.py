from collections.abc import Generator
from typing import Any
import re
import json

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
                # Database.query() internally uses get_connection(close_with_result=True),
                # whose Connection.close() deliberately skips self._conn.close()
                # ("the connection will close when the results are all consumed or GCed").
                # In a generator tool the result is held by the plugin runtime, so the
                # reference chain never dissolves and GC never reclaims the connection.
                # With pymysql (default autocommit=0) the implicit transaction of the
                # SELECT stays open on that checked-out connection, holding metadata
                # locks for hours; db.close() -> engine.dispose() cannot close
                # checked-out connections either. Use an explicit connection lifecycle
                # like the write path below.
                with db.get_connection() as conn:
                    rows = conn.query(query)
                    if format == "json":
                        result = rows.as_dict()
                        yield self.create_json_message({"result": result})
                    elif format == "md":
                        result = str(rows.dataset)
                        yield self.create_text_message(result)
                    elif format == "csv":
                        result = rows.export("csv").encode()
                        yield self.create_blob_message(
                            result, meta={"mime_type": "text/csv", "filename": "result.csv"}
                        )
                    elif format == "yaml":
                        result = rows.export("yaml").encode()
                        yield self.create_blob_message(
                            result,
                            meta={"mime_type": "text/yaml", "filename": "result.yaml"},
                        )
                    elif format == "xlsx":
                        result = rows.export("xlsx")
                        yield self.create_blob_message(
                            result,
                            meta={
                                "mime_type": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                                "filename": "result.xlsx",
                            },
                        )
                    elif format == "html":
                        result = rows.export("html").encode()
                        yield self.create_blob_message(
                            result,
                            meta={"mime_type": "text/html", "filename": "result.html"},
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
