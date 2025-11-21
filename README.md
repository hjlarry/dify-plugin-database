## database

**Author:** hjlarry  
**Version:** 0.0.7
**Type:** tool   
**Repo:** [https://github.com/hjlarry/dify-plugin-database](https://github.com/hjlarry/dify-plugin-database)  
**Feature Request:** [issues](https://github.com/hjlarry/dify-plugin-database/issues)  
**中文文档** [README_CN.md](https://github.com/hjlarry/dify-plugin-database/blob/main/README_CN.md)

### Be Carefull!
**The sql_execute tool can run any SQL query; for enhanced security, always use a read-only database account.**

### Description

A database tool make it easy to query data from existing databases.

You can get different format of data, like `json`, `csv`, `yaml`, `xlsx`, `html`, `md` etc. Also support use a url to get those data.

### Usage

#### 1. Input a databaseURI for Authorization. Now support `mysql`, `postgresql`, `sqlite`, `sqlserver`, `oracle`, `clickhouse`, example format:
```shell
mysql+pymysql://root:123456@localhost:3306/test
postgresql+psycopg2://postgres:123456@localhost:5432/test
sqlite:///test.db
mssql+pymssql://<username>:<password>@<freetds_name>/?charset=utf8
oracle+oracledb://user:pass@hostname:port[/dbname][?service_name=<service>[&key=value&key=value...]]
clickhouse://default:password@localhost:8123/default
clickhouse+connect://default:password@localhost:8123/mydatabase
```

**ClickHouse/MyScale Notes:**
- Support for ClickHouse and MyScale (a vector database based on ClickHouse)
- Uses `clickhouse-connect` Python driver
- Default ports: 8123 (HTTP), 9000 (Native TCP)
- MyScale is a ClickHouse-compatible vector database with vector similarity search capabilities

> **Note:**: this plugin always run in a docker, so the `localhost` always means docker internal network, try `host.docker.internal` instead.

#### 2. Use the `SQL Execute` tool to query data from the database.
![sql](./_assets/sql_execute.png)
The `OUTPUT FORMAT` is used to specify the format of the output data. If you don't specify it, the default format is `json` and will output in the `json` variable of workflow node. `md` will output in the `text` variable, other format will create file and output in the `files` variable.

If you input the `DB URI` field, it will overwrite the default authorization uri, so this will be useful if you want to use different databases in the same workflow.

#### 3. Use the `Text to SQL` tool can transform user input to a valid sql query.
![text](./_assets/text.png)

This tool will use the default prompt [here](https://github.com/hjlarry/dify-plugin-database/blob/d6dd3695840e8eb5d673611784af148b1789da97/tools/text2sql.py#L9) to generate a sql query. If you specify the `TABLES` field, it will only get those tables' schema into the LLM context.

#### 4. Use the `Get Table Schema` tool can get the schema of tables.

If the `Text to SQL` tool can't generate a helpful sql query, you can use this tool to get the schema of tables, then use the schema orginze with your own prompt or other information to a LLM node to generate a helpful sql query. 

#### 5. The `CSV Query` tool can execute a sql query from a csv file.
![csv](./_assets/csv.png)  
The table name is always `csv`,  the column name is the csv file's first line. It support output `json` and `md`.

#### 6. Use the `endpoint` tool to get the data from a url request.

example url request format:
```shell
curl -X POST 'https://daemon-plugin.dify.dev/o3wvwZfYFLU5iGopr5CxYmGaM5mWV7xf/sql' -H 'Content-Type: application/json' -d '{"query":"select * from test", "format": "md"}'
```


### Changelog

#### 0.0.7
1. Added ClickHouse/MyScale database support
2. Uses clickhouse-connect 0.10.0+ driver
3. Support all existing output formats (JSON, CSV, YAML, XLSX, HTML, Markdown)
4. Support table schema retrieval, including ClickHouse-specific engine, sorting keys, partition keys, etc.
5. Fully compatible with MyScale vector database

#### 0.0.6
1. support get more table info of `get table schema` tool
2. support special `schema` of `get table schema` tool

#### 0.0.5
1. support `with` in sql query
2. fix `text2sql` generate double quotes sql string
3. fix  `too many clients already`
4. add connect option of sqlalchemy
5. change the `db_uri` of authorization to an optional field
6. add a `Get Table Schema` to directly response the schema of tables
7. add a `CSV Query` tool to execute a sql query from a csv file
8. fix `oracle` authorization can't run `select 1`

#### 0.0.4
1. support `sqlserver`, `oracle` connection
2. change `db_url` to a llm format, so that user can use a environment variable of workflow to set the database uri
3. fix in a agent app, `sql_execute` tool only response the first result
4. migrate the table schema info of the `text2sql` tool to a user prompt, to prevent system prompt too long then response nothing

#### 0.0.3
1. add `cryptography` to requirements.txt to support mysql 8.1 sha256 link
2. remove database uri setting of the endpoint
3. add a `db_uri` to support link to multiple databases
4. change the `output` of sql_execute tool to a form format
5. change the `tables` of text2sql tool to a llm format
6. fix sql query being converted to lowercase [issue](https://github.com/hjlarry/dify-plugin-database/issues/2)


### Contact
![1](_assets/contact.jpg)