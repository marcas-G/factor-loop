"""Read-only dashboard HTTP API contracts against the real corpus SQLite store."""
from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from core.corpus_autoloop.dashboard_api import app
from core.corpus_autoloop.workflow import CorpusAutoloop


class DashboardApiTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.db = Path(self.temp.name) / 'research.sqlite3'
        env = patch.dict(os.environ, {'CORPUS_AUTOLOOP_DB_PATH': str(self.db)})
        env.start()
        self.addCleanup(env.stop)
        self.http = TestClient(app)

    def test_empty_database_does_not_get_created_by_dashboard(self):
        overview = self.http.get('/api/overview')
        self.assertEqual(overview.status_code, 200)
        self.assertEqual(overview.json()['chapter_count'], 81)
        self.assertEqual(overview.json()['research_objects'], 0)
        self.assertEqual(overview.json()['data_mode'], 'corpus_only')
        chapters = self.http.get('/api/chapters').json()['chapters']
        self.assertEqual(len(chapters), 81)
        self.assertEqual(chapters[0]['status'], 'unseeded')
        self.assertTrue(self.http.get('/api/chapters/1').json()['source']['text'])
        self.assertFalse(self.db.exists(), 'GET must not create production DB')
        self.assertEqual(self.http.get('/api/activity').json()['events'], [])
        self.assertEqual(self.http.get('/api/health').json()['mode'], 'read_only')

    def test_seeded_real_db_overview_and_detail(self):
        store = CorpusAutoloop(self.db)
        store.seed()
        ov = self.http.get('/api/overview').json()
        self.assertEqual(ov['research_objects'], 81)
        self.assertEqual(ov['attempted_chapters'], 0)
        self.assertEqual(ov['admitted_factors'], 0)
        ch = self.http.get('/api/chapters/1').json()
        self.assertEqual(ch['source']['chapter'], 1)
        self.assertEqual(ch['research_objects'][0]['status'], 'pending')
        self.assertEqual(ch['research_objects'][0]['depth'], 0)
        detail = self.http.get('/api/research-objects/RO-DDJ-001').json()
        self.assertEqual(detail['research_object']['object_id'], 'RO-DDJ-001')
        self.assertEqual(detail['events'][0]['kind'], 'seed')
        self.assertEqual(detail['links'], {})
        self.assertEqual(len(self.http.get('/api/activity?limit=8').json()['events']), 8)
        self.assertEqual(self.http.get('/api/health').json()['database_exists'], True)
        with store._connection() as db:
            # Read-only API cannot mutate either state or event log.
            self.assertEqual(db.execute('SELECT COUNT(*) FROM research_events').fetchone()[0], 81)

    def test_invalid_identifiers_and_nonexistent_chapters_are_404(self):
        self.assertEqual(self.http.get('/api/chapters/82').status_code, 404)
        self.assertEqual(self.http.get('/api/chapters/0').status_code, 404)
        self.assertEqual(self.http.get('/api/research-objects/bad-path').status_code, 404)
        self.assertEqual(self.http.get('/api/research-objects/RO-DDJ-001').status_code, 404)
        self.assertEqual(self.http.get('/api/activity?limit=1000').status_code, 422)

    def test_request_never_exposes_raw_event_payloads_or_secret_paths(self):
        store = CorpusAutoloop(self.db)
        store.seed()
        detail = self.http.get('/api/research-objects/RO-DDJ-001').json()
        self.assertEqual(set(detail['events'][0]), {'id', 'kind', 'recorded_at'})
        self.assertNotIn('payload', str(detail))


if __name__ == '__main__':
    unittest.main()
