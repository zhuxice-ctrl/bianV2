import pandas as pd


def as_known_at(frame: pd.DataFrame, decision_time: pd.Timestamp) -> pd.DataFrame:
    if decision_time.tzinfo is None:
        raise ValueError("decision_time must be timezone-aware")
    return frame.loc[pd.to_datetime(frame["available_time"], utc=True) <= decision_time].copy()
