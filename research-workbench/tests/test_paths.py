from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from db.paths import quote_csvs
from db.backup import make_backup, restore_backup
from workbench import connect


class QuotePathsTests(unittest.TestCase):
    def test_legacy_and_strategy_data_are_both_backed_up_and_restored(self):
        with tempfile.TemporaryDirectory() as temp:
            workspace = Path(temp).resolve()
            root = workspace / 'research-workbench'
            root.mkdir()
            (root / 'sources.json').write_text('{"version":1,"sources":[]}')
            # Explicitly exercise the retained SQLite backup, independent of local backend settings.
            conn = connect(root)
            conn.close()
            expected = ['logs/old.csv', 'strategies/entropy-arbitrage/logs/new.csv',
                        'strategies/weather/logs/nested/quotes.csv']
            for relative in expected + ['strategies/weather/data/not-quotes.csv']:
                file = workspace / relative
                file.parent.mkdir(parents=True, exist_ok=True)
                file.write_text('time_utc,price\n2026-09-10T00:00:00Z,1\n')
            self.assertEqual({p.relative_to(workspace).as_posix() for p in quote_csvs(root)}, set(expected))
            backup = make_backup(root)
            destination = workspace / 'restored'
            restore_backup(backup, destination)
            for relative in expected:
                self.assertEqual((destination / relative).read_bytes(), (workspace / relative).read_bytes())
            self.assertFalse((destination / 'strategies/weather/data/not-quotes.csv').exists())

    def test_missing_log_directories_are_allowed(self):
        with tempfile.TemporaryDirectory() as temp:
            self.assertEqual(quote_csvs(Path(temp) / 'research-workbench'), [])
