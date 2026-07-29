import hashlib

import pandas as pd


def dataframe_content_hash(frame: pd.DataFrame, *, sort_by: list[str]) -> str:
    missing = set(sort_by) - set(frame.columns)
    if missing:
        raise ValueError(f"sort columns are missing: {sorted(missing)}")
    columns = sorted(frame.columns)
    tie_breakers = [column for column in columns if column not in sort_by]
    stable = (
        frame.loc[:, columns]
        .sort_values([*sort_by, *tie_breakers], kind="mergesort")
        .reset_index(drop=True)
    )
    payload = stable.to_json(orient="table", date_format="iso", double_precision=15)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
