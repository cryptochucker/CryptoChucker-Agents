from __future__ import annotations

import csv
import json
import os
from pathlib import Path


def save_watchlist(symbols: list[str], path: str) -> None:
    """Persist a symbol list to JSON or CSV depending on file extension.

    Args:
        symbols: List of trading pair symbols (e.g. ["BTC/USDT", "ETH/USDT"]).
        path: Destination file path. Extension determines format (.json or .csv).
    """
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    ext = Path(path).suffix.lower()
    if ext == ".json":
        with open(path, "w", encoding="utf-8") as f:
            json.dump(symbols, f, indent=2)
    elif ext == ".csv":
        with open(path, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            for sym in symbols:
                writer.writerow([sym])
    else:
        raise ValueError(f"Unsupported watchlist format: {ext!r}. Use .json or .csv.")


def load_watchlist(path: str) -> list[str]:
    """Load a symbol list from JSON or CSV.

    Args:
        path: Source file path. Extension determines format (.json or .csv).

    Returns:
        List of symbol strings.
    """
    ext = Path(path).suffix.lower()
    if ext == ".json":
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, list):
            raise ValueError("Watchlist JSON must be a top-level array.")
        return [str(s) for s in data]
    elif ext == ".csv":
        with open(path, "r", newline="", encoding="utf-8") as f:
            reader = csv.reader(f)
            return [row[0] for row in reader if row]
    else:
        raise ValueError(f"Unsupported watchlist format: {ext!r}. Use .json or .csv.")
