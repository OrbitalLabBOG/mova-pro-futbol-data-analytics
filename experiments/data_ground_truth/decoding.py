"""Reviewed decoding contracts for immutable source artifacts, never guessed fallback."""
from __future__ import annotations

import io

import pandas as pd

from experiments.data_ground_truth.raw import digest

# Exact archived bytes: ISO-8859-1 and Windows-1252 coincide here (no 0x80..0x9f).
# UTF-8 is otherwise mandatory. A future source revision must be reviewed again.
LATIN1_HASHES = {
    '49fd5f815509513fac8cf329abc0faa4e48d99ab57b56162220bcb6caeae4116',  # data/2016-17/gws/merged_gw.csv
    '1d8288bad9994994070100b23a4fc2b28efeb79d8be13c9e6f6be559c1c9369d',  # data/2017-18/gws/merged_gw.csv
    '0c96ab3e3b12ffa9d27e24483b494cc9350d24f02520f2c964ea8b8f19f08c68',  # data/2018-19/gws/merged_gw.csv
}


def read_csv_bytes(data: bytes) -> tuple[pd.DataFrame, str]:
    encoding = 'iso-8859-1' if digest(data) in LATIN1_HASHES else 'utf-8'
    if encoding == 'iso-8859-1' and any(128 <= b <= 159 for b in data):
        raise ValueError('reviewed Latin-1 contract violated')
    text = data.decode(encoding, errors='strict')
    if '\ufffd' in text:
        raise ValueError('replacement character in source')
    return pd.read_csv(io.StringIO(text), low_memory=False), encoding
