# import pandas as pd
# from pathlib import Path


# def create_sample_hazard_data() -> pd.DataFrame:
#     """
#     Create sample district-level hazard, exposure, vulnerability and centroid data
#     for the hackathon prototype.

#     Latitude/longitude values are approximate MVP centroids for map display.
#     Replace them later with official admin boundary centroids or polygons.
#     """

#     data = [
#         {
#             "country": "Ethiopia",
#             "district": "Borena",
#             "hazard": "drought",
#             "hazard_probability": 0.78,
#             "exposure": 0.82,
#             "vulnerability": 0.88,
#             "confidence": 0.75,
#             "latitude": 4.95,
#             "longitude": 38.15,
#         },
#         {
#             "country": "Ethiopia",
#             "district": "Afar Zone 1",
#             "hazard": "heat_stress",
#             "hazard_probability": 0.70,
#             "exposure": 0.68,
#             "vulnerability": 0.80,
#             "confidence": 0.72,
#             "latitude": 12.15,
#             "longitude": 40.75,
#         },
#         {
#             "country": "Kenya",
#             "district": "Turkana",
#             "hazard": "drought",
#             "hazard_probability": 0.81,
#             "exposure": 0.86,
#             "vulnerability": 0.84,
#             "confidence": 0.78,
#             "latitude": 3.12,
#             "longitude": 35.60,
#         },
#         {
#             "country": "Kenya",
#             "district": "Garissa",
#             "hazard": "heavy_rainfall",
#             "hazard_probability": 0.64,
#             "exposure": 0.72,
#             "vulnerability": 0.66,
#             "confidence": 0.70,
#             "latitude": -0.45,
#             "longitude": 39.65,
#         },
#     ]

#     return pd.DataFrame(data)


# if __name__ == "__main__":
#     output_dir = Path("data/sample")
#     output_dir.mkdir(parents=True, exist_ok=True)

#     df = create_sample_hazard_data()
#     output_path = output_dir / "hazard_indicators.csv"
#     df.to_csv(output_path, index=False)

#     print(f"Sample data saved to: {output_path}")


try:
    from app.data_pipeline.chirps_rainfall_pipeline import run_pipeline
except ModuleNotFoundError:
    import sys
    from pathlib import Path

    # Allow running this file directly: python app/data_pipeline/load_sample_data.py
    repo_root = Path(__file__).resolve().parents[2]
    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))

    from app.data_pipeline.chirps_rainfall_pipeline import run_pipeline


if __name__ == "__main__":
    run_pipeline()