import hashlib

import pandas as pd


def dataframe_content_hash(frame: pd.DataFrame, *, sort_by: list[str]) -> str:
    stable = frame.sort_values(sort_by).reset_index(drop=True)
    payload = stable.to_json(orient="table", date_format="iso", double_precision=15)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
