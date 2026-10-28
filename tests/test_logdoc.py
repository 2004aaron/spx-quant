"""The cloud log carrier: dump and load round-trip, damaged copies are refused."""
import importlib.util
import sqlite3
import tempfile
import unittest
from pathlib import Path

from spx_quant import pipeline, store
from tests.helpers import PARAMS, pm150, replay

spec = importlib.util.spec_from_file_location("logdoc", Path(__file__).parents[1] / "deploy" / "cloud" / "logdoc.py")
logdoc = importlib.util.module_from_spec(spec)
spec.loader.exec_module(logdoc)


class LogDocTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.d = Path(self.tmp.name)
        conn = store.connect(self.d / "a.db")
        pipeline.scan(conn, replay(), pm150(), PARAMS, slot="13:25", send=False)
        conn.close()

    def tearDown(self):
        self.tmp.cleanup()

    def test_round_trip_keeps_every_row_and_the_append_only_triggers(self):
        before = logdoc.dump(str(self.d / "a.db"), str(self.d / "log.sql"))
        after = logdoc.load(str(self.d / "log.sql"), str(self.d / "b.db"))
        self.assertEqual(before, after)
        self.assertIn("alert=1", after)
        conn = sqlite3.connect(self.d / "b.db")
        with self.assertRaises(sqlite3.DatabaseError):
            conn.execute("DELETE FROM alert")
        conn.close()
        conn2 = store.connect(self.d / "b.db")
        pipeline.scan(conn2, replay(), pm150(), PARAMS, slot="13:25", send=False)
        self.assertEqual(conn2.execute("SELECT COUNT(*) FROM alert").fetchone()[0], 2)

    def test_damaged_copy_is_refused(self):
        logdoc.dump(str(self.d / "a.db"), str(self.d / "log.sql"))
        p = self.d / "log.sql"
        p.write_text(p.read_text().replace("INSERT", "INSERTT", 1))
        with self.assertRaises(SystemExit):
            logdoc.load(str(p), str(self.d / "c.db"))
        self.assertFalse((self.d / "c.db").exists())


if __name__ == "__main__":
    unittest.main()
