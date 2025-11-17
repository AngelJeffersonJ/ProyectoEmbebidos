from __future__ import annotations

from typing import Iterable, List, Dict, Any

import numpy as np
import pandas as pd
from sklearn.cluster import DBSCAN

INSECURE_LEVELS = {'open', 'wep'}
EARTH_RADIUS_METERS = 6_371_000


def cluster_insecure_networks(records: Iterable[Dict[str, Any]], eps_meters: float = 75.0, min_samples: int = 3) -> Dict[str, List[Dict[str, Any]]]:
    """Cluster insecure networks (Open/WEP) using DBSCAN over lat/lon coordinates.

    Returns a dictionary with the enriched raw points and cluster summaries.
    """

    records_list = list(records or [])
    if not records_list:
        return {'points': [], 'clusters': []}

    df = pd.DataFrame(records_list)
    if {'latitude', 'longitude', 'security'}.difference(df.columns):
        return {'points': [], 'clusters': []}

    insecure = df[df['security'].str.lower().isin(INSECURE_LEVELS)].copy()
    insecure.dropna(subset=['latitude', 'longitude'], inplace=True)
    if insecure.empty:
        return {'points': [], 'clusters': []}

    coords_rad = np.radians(insecure[['latitude', 'longitude']].astype(float).values)
    eps_radians = eps_meters / EARTH_RADIUS_METERS
    model = DBSCAN(eps=eps_radians, min_samples=min_samples, metric='haversine')
    labels = model.fit_predict(coords_rad)
    insecure['cluster'] = labels

    clusters = (
        insecure[insecure['cluster'] != -1]
        .groupby('cluster')
        .agg(count=('cluster', 'size'),
             avg_latitude=('latitude', 'mean'),
             avg_longitude=('longitude', 'mean'),
             avg_rssi=('rssi', 'mean'))
        .reset_index()
    )

    return {
        'points': insecure.to_dict(orient='records'),
        'clusters': clusters.to_dict(orient='records'),
    }
