
import sys
import os
sys.path.append("soda_server")
from rrd_reader import DuckDBReader

def test_images():
    db_file = "soda_server/test_recording.duckdb"
    if not os.path.exists(db_file):
        print("DB file not found")
        return

    reader = DuckDBReader(db_file)
    images = reader.get_images("camera/front") # created in previous step
    print(f"Found {len(images)} images")
    if len(images) > 0:
        print(f"First image shape: {images[0]['image'].shape}")
        print(f"First image time: {images[0]['time']}")

if __name__ == "__main__":
    test_images()
