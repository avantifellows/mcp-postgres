"""Guard tests for is_read_only(): token-based, not substring-based."""
import pytest

from mcp_postgres.server import is_read_only

ALLOWED = [
    "SELECT 1",
    "select id, deleted_at from users where deleted_at is null",
    "SELECT inserted_at, updated_at FROM school",
    "SELECT revoked_at FROM centre_positions WHERE revoked_at IS NOT NULL",
    "SELECT inserted_at::date AS insert_day FROM enrollment_record",
    "WITH x AS (SELECT * FROM t) SELECT * FROM x",
    "SELECT * FROM t WHERE note = 'please DELETE me'",
    "SELECT * FROM t -- DROP TABLE t\nWHERE id = 1",
    "SELECT /* UPDATE? no */ 1",
    'SELECT "deleted_at" FROM t',
    'SELECT U&"d\\0065leted_at" FROM t',
    "SELECT $$DELETE FROM t$$ AS s",
    "SELECT E'it''s an INSERT' AS s",
    "SELECT 1;",
    "  \n SELECT 1  ",
    "SELECT count(*) FROM t WHERE updated_at > now() - interval '1 day'",
]

REJECTED = [
    "",
    "   ",
    "DELETE FROM t",
    "delete from t where id = 1",
    "INSERT INTO t VALUES (1)",
    "UPDATE t SET a = 1",
    "DROP TABLE t",
    "TRUNCATE t",
    "WITH d AS (DELETE FROM t RETURNING *) SELECT * FROM d",
    "WITH i AS (INSERT INTO t VALUES (1) RETURNING id) SELECT * FROM i",
    "SELECT 1; DELETE FROM t",
    "SELECT 1; DROP TABLE t;",
    "SELECT * FROM t FOR UPDATE",
    "COPY t TO '/tmp/x'",
    "CALL do_thing()",
    "EXPLAIN SELECT 1",
    "GRANT ALL ON t TO public",
    "MERGE INTO t USING s ON t.id = s.id WHEN MATCHED THEN DELETE",
    "-- just a comment",
    "'SELECT' 1",
]


@pytest.mark.parametrize("sql", ALLOWED)
def test_allows_read_only(sql):
    assert is_read_only(sql) is True


@pytest.mark.parametrize("sql", REJECTED)
def test_rejects_writes(sql):
    assert is_read_only(sql) is False
