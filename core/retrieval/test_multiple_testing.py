import sqlite3
import unittest

from core.retrieval.multiple_testing import build_multiple_testing_context


class MultipleTestingContextTest(unittest.TestCase):
    def _conn(self):
        conn = sqlite3.connect(":memory:")
        conn.executescript(
            """
            CREATE TABLE ideas (
                id INTEGER PRIMARY KEY,
                angle_code TEXT
            );
            CREATE TABLE factors (
                xname TEXT PRIMARY KEY,
                status TEXT,
                angle_code TEXT,
                deprecated_at TIMESTAMP
            );
            CREATE TABLE idea_factor_links (
                idea_id INTEGER,
                factor_xname TEXT,
                PRIMARY KEY (idea_id, factor_xname)
            );
            INSERT INTO ideas VALUES (7, 'book_imbalance');
            INSERT INTO factors VALUES ('OldEvaluated', 'evaluated', 'book_imbalance', NULL);
            INSERT INTO factors VALUES ('OldDeadEnd', 'dead_end', 'book_imbalance', NULL);
            INSERT INTO factors VALUES ('OldEvaluated2', 'evaluated', 'book_imbalance', NULL);
            INSERT INTO factors VALUES ('OldDraft', 'draft', 'book_imbalance', NULL);
            INSERT INTO factors VALUES ('OldOtherAngle', 'dead_end', 'depth_shape', NULL);
            INSERT INTO idea_factor_links VALUES (7, 'OldEvaluated');
            INSERT INTO idea_factor_links VALUES (7, 'OldEvaluated2');
            INSERT INTO idea_factor_links VALUES (7, 'OldDraft');
            """
        )
        return conn

    def test_counts_angle_and_lineage_attempts(self):
        factor = {"name": "NewImb", "formula": "imb * depth", "tags": ["book_imbalance"]}
        current = [factor, {"name": "NewImb2", "formula": "ofi"}, {"name": "Other"}]

        conn = self._conn()
        try:
            context = build_multiple_testing_context(
                conn, factor, 7, current_factors=current, factor_index=0
            )
        finally:
            conn.close()

        self.assertTrue(context["available"])
        self.assertEqual(context["angle_code"], "book_imbalance")
        self.assertEqual(context["angle_source"], "idea")
        self.assertEqual(context["angle_prior_attempt_count"], 3)
        self.assertEqual(context["angle_attempt_count_including_current"], 6)
        self.assertEqual(context["angle_attempt_status_counts"]["evaluated"], 2)
        self.assertEqual(context["angle_attempt_status_counts"]["dead_end"], 1)
        self.assertEqual(context["lineage_prior_attempt_count"], 2)
        self.assertEqual(context["lineage_attempt_count_including_current_batch"], 5)
        self.assertEqual(context["current_batch_size"], 3)

    def test_infers_angle_without_idea_id(self):
        factor = {"name": "OiEnergyNew", "formula": "open_interest energy", "tags": []}

        conn = self._conn()
        try:
            context = build_multiple_testing_context(conn, factor, None)
        finally:
            conn.close()

        self.assertEqual(context["angle_code"], "oi_anomaly")
        self.assertEqual(context["angle_source"], "inferred")
        self.assertEqual(context["angle_attempt_count_including_current"], 1)
        self.assertEqual(context["lineage_prior_attempt_count"], 0)


if __name__ == "__main__":
    unittest.main()
