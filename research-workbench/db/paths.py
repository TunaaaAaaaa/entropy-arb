"""Data discovery supporting historical and strategy-local quote locations."""
from pathlib import Path


def quote_csvs(root):
    workspace = Path(root).resolve().parent
    folders = [workspace / 'logs']
    folders.extend(sorted((workspace / 'strategies').glob('*/logs')))
    return sorted({file for folder in folders for file in folder.rglob('*.csv') if file.is_file()})
