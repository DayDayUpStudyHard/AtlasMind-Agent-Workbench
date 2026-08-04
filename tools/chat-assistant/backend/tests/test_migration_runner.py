import unittest

from app.api.routes import _execute_migration_statement


class FakeCursor:
    def __init__(self, existing_columns=None):
        self.existing_columns = set(existing_columns or [])
        self.calls = []
        self._last_exists = False

    def execute(self, sql, params=None):
        self.calls.append((sql, params))
        if "information_schema.COLUMNS" in sql:
            self._last_exists = tuple(params) in self.existing_columns

    def fetchone(self):
        return {"exists": 1} if self._last_exists else None


class MigrationRunnerTest(unittest.TestCase):
    def test_adds_only_missing_columns_from_multi_column_alter(self):
        cursor = FakeCursor(existing_columns={("agent_run", "subject_type")})

        _execute_migration_statement(
            cursor,
            """ALTER TABLE agent_run
               ADD COLUMN IF NOT EXISTS subject_type VARCHAR(32) NULL,
               ADD COLUMN IF NOT EXISTS subject_id BIGINT NULL""",
        )

        alter_calls = [sql for sql, _ in cursor.calls if sql.startswith("ALTER TABLE")]
        self.assertEqual(
            ["ALTER TABLE `agent_run` ADD COLUMN `subject_id` BIGINT NULL"],
            alter_calls,
        )

    def test_regular_statement_passes_through(self):
        cursor = FakeCursor()

        _execute_migration_statement(cursor, "CREATE TABLE sample (id BIGINT)")

        self.assertEqual([("CREATE TABLE sample (id BIGINT)", None)], cursor.calls)


if __name__ == "__main__":
    unittest.main()
