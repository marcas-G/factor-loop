import sqlite3
import unittest

from core.cog.factor_profile import build_factor_profile


class FactorProfileTest(unittest.TestCase):
    def _conn(self):
        conn = sqlite3.connect(":memory:")
        conn.executescript(
            """
            CREATE TABLE factors (
                xname TEXT PRIMARY KEY,
                class_name TEXT,
                file_path TEXT,
                formula_text TEXT,
                operator_chain TEXT,
                field_bindings TEXT,
                params TEXT,
                status TEXT,
                quality_grade TEXT,
                latest_ic REAL,
                latest_icir REAL,
                latest_sharpe REAL,
                latest_rank_ic REAL,
                latest_r2_x REAL,
                latest_res_ic REAL,
                intuition TEXT,
                deprecated_at TIMESTAMP
            );
            CREATE TABLE factor_lineage_edges (
                parent_xname TEXT,
                child_xname TEXT
            );
            CREATE TABLE factor_ic_daily (
                factor_xname TEXT NOT NULL,
                symbol TEXT NOT NULL,
                freq TEXT NOT NULL,
                y_horizon INTEGER NOT NULL,
                date TEXT NOT NULL,
                ic REAL,
                PRIMARY KEY (factor_xname, symbol, freq, y_horizon, date)
            );
            CREATE TABLE lessons (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                type TEXT,
                text TEXT,
                evidence TEXT,
                factor_xname TEXT,
                deprecated_at TIMESTAMP
            );
            """
        )
        conn.execute(
            """
            INSERT INTO factors (
                xname, class_name, file_path, formula_text, operator_chain,
                field_bindings, params, status, quality_grade,
                latest_ic, latest_icir, latest_sharpe, latest_rank_ic,
                latest_r2_x, latest_res_ic, intuition
            ) VALUES (
                'TestFactor', 'TestFactor', 'factors/TestFactor.h', 'x',
                NULL, NULL, '{}', 'dead_end', NULL,
                0.1, 2.0, NULL, NULL,
                0.83, 0.0034, 'test'
            )
            """
        )
        return conn

    def test_evidence_view_includes_restest_profile(self):
        conn = self._conn()
        try:
            profile = build_factor_profile(conn, "TestFactor")
        finally:
            conn.close()

        self.assertIsNotNone(profile)
        metrics = profile["evidence_view"]["latest_metrics"]
        self.assertEqual(metrics["r2_x"], 0.83)
        self.assertEqual(metrics["res_ic"], 0.0034)
        self.assertIn(
            "factors.latest_r2_x/latest_res_ic",
            profile["provenance"]["evidence_sources"],
        )

    def test_restest_profile_stays_out_of_construction_view(self):
        conn = self._conn()
        try:
            profile = build_factor_profile(conn, "TestFactor")
        finally:
            conn.close()

        construction = profile["construction_view"]
        for field in ("r2_x", "res_ic"):
            self.assertNotIn(field, construction)


if __name__ == "__main__":
    unittest.main()
