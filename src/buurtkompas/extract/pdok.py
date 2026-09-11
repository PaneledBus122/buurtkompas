import geopandas as gpd
import requests

BASE_URL = "https://service.pdok.nl/cbs/wijken-en-buurten-2024/wfs/v1_0"


def fetch_all_buurten(page_size: int = 1000) -> list:
    all_features = []
    start_index = 0
    while True:
        params = {
            "service": "WFS",
            "version": "2.0.0",
            "request": "GetFeature",
            "typeName": "wijkenbuurten:buurten",
            "outputFormat": "application/json",
            "srsName": "EPSG:4326",
            "count": page_size,
            "startIndex": start_index,
        }
        resp = requests.get(BASE_URL, params=params, timeout=30)
        resp.raise_for_status()
        features = resp.json().get("features", [])
        print(f"startIndex={start_index}: {len(features)}개 수신")
        if not features:
            break
        all_features.extend(features)
        if len(features) < page_size:
            break
        start_index += page_size
    return all_features


features = fetch_all_buurten()
print("전체 buurten 수:", len(features))

gdf = gpd.GeoDataFrame.from_features(features, crs="EPSG:4326")
eindhoven = gdf[gdf["gemeentecode"] == "GM0772"].copy()
print(f"Eindhoven buurten: {len(eindhoven)}")
eindhoven.to_file("data/raw/pdok_eindhoven_buurten.geojson", driver="GeoJSON")
