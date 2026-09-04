"""Read-only PostgreSQL MCP server for Avanti Fellows DB Service."""

import json
import re
import os
from contextlib import asynccontextmanager

import asyncpg
from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP

load_dotenv()

# Initialize MCP server
mcp = FastMCP("avanti-postgres")

# Database configuration from environment
DB_CONFIG = {
    "host": os.environ.get("AF_DB_HOST", "localhost"),
    "port": int(os.environ.get("AF_DB_PORT", "5432")),
    "user": os.environ.get("AF_DB_USER", ""),
    "password": os.environ.get("AF_DB_PASSWORD", ""),
    "database": os.environ.get("AF_DB_NAME", ""),
}


@asynccontextmanager
async def get_connection():
    """Get a database connection."""
    # Server-side guard: every transaction on this connection is READ ONLY, so
    # Postgres itself rejects INSERT/UPDATE/DELETE/DDL regardless of how the
    # statement text is shaped. is_read_only() below is only the friendly
    # pre-check that turns a would-be server error into a clear message.
    conn = await asyncpg.connect(
        **DB_CONFIG, server_settings={"default_transaction_read_only": "on"}
    )
    try:
        yield conn
    finally:
        await conn.close()


# Statements that are never read-only. Matched as whole tokens, never as
# substrings — `deleted_at`, `inserted_at`, `revoked_at`, `AS insert_day` are
# ordinary identifiers and must pass (D43/D95/D120).
_WRITE_KEYWORDS = frozenset({
    "INSERT", "UPDATE", "DELETE", "MERGE", "DROP", "ALTER", "TRUNCATE",
    "CREATE", "GRANT", "REVOKE", "COPY", "CALL",
})
_READ_LEADERS = ("SELECT", "WITH")

_SQL_NOISE = re.compile(
    r"""
      --[^\n]*                     # line comment
    | /\*.*?\*/                     # block comment
    | \$(\w*)\$.*?\$\1\$            # dollar-quoted string
    | [eE]?'(?:[^']|'')*'           # string literal ('' escape, E'' prefix)
    | (?:U&)?"(?:[^"]|"")*"          # quoted identifier (incl. U&"...")
    """,
    re.S | re.X,
)
_TOKEN = re.compile(r"[A-Za-z_][A-Za-z0-9_$]*")


def _strip_noise(sql: str) -> str:
    """Remove comments, string literals and quoted identifiers so keyword
    scanning only ever sees bare SQL tokens."""
    return _SQL_NOISE.sub(" ", sql)


def is_read_only(sql: str) -> bool:
    """True iff `sql` is a single SELECT/WITH statement with no data-modifying
    keyword as a whole token.

    Tokenises instead of substring-matching: the previous check refused any
    SQL containing 'DELETE' anywhere, which rejected every query naming an
    Ecto `deleted_at`/`inserted_at` column. The real enforcement is the
    READ ONLY transaction set in get_connection(); this is the pre-check.
    """
    bare = _strip_noise(sql).strip()
    if not bare:
        return False
    # One statement only: a trailing semicolon is fine, an interior one is not.
    if ";" in bare.rstrip().rstrip(";"):
        return False
    tokens = [t.upper() for t in _TOKEN.findall(bare)]
    if not tokens or tokens[0] not in _READ_LEADERS:
        return False
    return not any(t in _WRITE_KEYWORDS for t in tokens)


@mcp.tool()
async def query(sql: str) -> str:
    """Execute a read-only SQL query against the database.

    Only SELECT queries are allowed. Use this to explore data,
    debug issues, or validate assumptions about the data.

    Args:
        sql: A SELECT query to execute

    Returns:
        JSON array of results, or error message
    """
    if not is_read_only(sql):
        return json.dumps({"error": "Only SELECT queries are allowed"})

    try:
        async with get_connection() as conn:
            rows = await conn.fetch(sql)
            # Convert to list of dicts, handling special types
            results = []
            for row in rows:
                results.append({k: _serialize_value(v) for k, v in dict(row).items()})
            return json.dumps(results, indent=2, default=str)
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp.tool()
async def list_tables() -> str:
    """List all tables in the database.

    Returns tables from all schemas (excluding system schemas).
    Use this to discover what data is available.

    Returns:
        JSON array of tables with schema, name, and type
    """
    sql = """
        SELECT
            table_schema,
            table_name,
            table_type
        FROM information_schema.tables
        WHERE table_schema NOT IN ('pg_catalog', 'information_schema')
        ORDER BY table_schema, table_name
    """
    try:
        async with get_connection() as conn:
            rows = await conn.fetch(sql)
            results = [dict(row) for row in rows]
            return json.dumps(results, indent=2)
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp.tool()
async def describe_table(table_name: str, schema_name: str = "public") -> str:
    """Get detailed schema information for a table.

    Returns column names, types, nullability, and defaults.
    Use this to understand table structure before querying.

    Args:
        table_name: Name of the table
        schema_name: Schema name (default: public)

    Returns:
        JSON with columns, primary keys, and foreign keys
    """
    columns_sql = """
        SELECT
            column_name,
            data_type,
            is_nullable,
            column_default,
            character_maximum_length
        FROM information_schema.columns
        WHERE table_schema = $1 AND table_name = $2
        ORDER BY ordinal_position
    """

    pk_sql = """
        SELECT a.attname as column_name
        FROM pg_index i
        JOIN pg_attribute a ON a.attrelid = i.indrelid AND a.attnum = ANY(i.indkey)
        JOIN pg_class c ON c.oid = i.indrelid
        JOIN pg_namespace n ON n.oid = c.relnamespace
        WHERE i.indisprimary
        AND n.nspname = $1
        AND c.relname = $2
    """

    fk_sql = """
        SELECT
            kcu.column_name,
            ccu.table_schema AS foreign_schema,
            ccu.table_name AS foreign_table,
            ccu.column_name AS foreign_column
        FROM information_schema.table_constraints AS tc
        JOIN information_schema.key_column_usage AS kcu
            ON tc.constraint_name = kcu.constraint_name
            AND tc.table_schema = kcu.table_schema
        JOIN information_schema.constraint_column_usage AS ccu
            ON ccu.constraint_name = tc.constraint_name
        WHERE tc.constraint_type = 'FOREIGN KEY'
        AND tc.table_schema = $1
        AND tc.table_name = $2
    """

    try:
        async with get_connection() as conn:
            columns = await conn.fetch(columns_sql, schema_name, table_name)
            pks = await conn.fetch(pk_sql, schema_name, table_name)
            fks = await conn.fetch(fk_sql, schema_name, table_name)

            result = {
                "table": f"{schema_name}.{table_name}",
                "columns": [dict(row) for row in columns],
                "primary_keys": [row["column_name"] for row in pks],
                "foreign_keys": [dict(row) for row in fks],
            }
            return json.dumps(result, indent=2, default=str)
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp.tool()
async def sample_data(table_name: str, schema_name: str = "public", limit: int = 10) -> str:
    """Get sample rows from a table.

    Useful for understanding what data looks like without
    writing a full query.

    Args:
        table_name: Name of the table
        schema_name: Schema name (default: public)
        limit: Number of rows to return (default: 10, max: 100)

    Returns:
        JSON array of sample rows
    """
    limit = min(limit, 100)  # Cap at 100 rows

    # Use identifier quoting to prevent SQL injection
    sql = f'SELECT * FROM "{schema_name}"."{table_name}" LIMIT {limit}'

    try:
        async with get_connection() as conn:
            rows = await conn.fetch(sql)
            results = []
            for row in rows:
                results.append({k: _serialize_value(v) for k, v in dict(row).items()})
            return json.dumps(results, indent=2, default=str)
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp.tool()
async def count_rows(table_name: str, schema_name: str = "public", where: str = None) -> str:
    """Count rows in a table, optionally with a WHERE clause.

    Args:
        table_name: Name of the table
        schema_name: Schema name (default: public)
        where: Optional WHERE clause (without 'WHERE' keyword)

    Returns:
        JSON with count
    """
    sql = f'SELECT COUNT(*) as count FROM "{schema_name}"."{table_name}"'

    if where:
        # Basic validation - only allow read operations in WHERE
        if not is_read_only(f"SELECT * FROM t WHERE {where}"):
            return json.dumps({"error": "Invalid WHERE clause"})
        sql += f" WHERE {where}"

    try:
        async with get_connection() as conn:
            row = await conn.fetchrow(sql)
            return json.dumps({"count": row["count"]})
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp.tool()
async def search_columns(search_term: str) -> str:
    """Search for columns by name across all tables.

    Useful when you know a column name but not which table it's in.

    Args:
        search_term: Partial column name to search for (case-insensitive)

    Returns:
        JSON array of matching columns with their tables
    """
    sql = """
        SELECT
            table_schema,
            table_name,
            column_name,
            data_type
        FROM information_schema.columns
        WHERE table_schema NOT IN ('pg_catalog', 'information_schema')
        AND LOWER(column_name) LIKE LOWER($1)
        ORDER BY table_schema, table_name, column_name
    """

    try:
        async with get_connection() as conn:
            rows = await conn.fetch(sql, f"%{search_term}%")
            results = [dict(row) for row in rows]
            return json.dumps(results, indent=2)
    except Exception as e:
        return json.dumps({"error": str(e)})


def _serialize_value(value):
    """Serialize special PostgreSQL types to JSON-compatible values."""
    if value is None:
        return None
    if isinstance(value, (dict, list)):
        return value
    if hasattr(value, "isoformat"):  # datetime, date, time
        return value.isoformat()
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return value


def main():
    """Run the MCP server."""
    mcp.run()


if __name__ == "__main__":
    main()
