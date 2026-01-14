import sys
import os

# sys.path.append("soda_server") # removed, assuming running from soda_server
from soda_server.data_reader import PandasReader


def test_images():
    db_file = "test_recording.duckdb"  # relative to soda_server
    if not os.path.exists(db_file):
        print("DB file not found")
        return

    reader = PandasReader(db_file)
    images = reader.get_images("camera/front")
    print(f"Found {len(images)} images")
    if len(images) > 0:
        print(f"First image shape: {images[0]['image'].shape}")
        print(f"First image time: {images[0]['time']}")


if __name__ == "__main__":
    test_images()
