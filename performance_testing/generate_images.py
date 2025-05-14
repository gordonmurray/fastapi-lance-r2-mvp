import requests
import os
import hashlib
import time

NUM_IMAGES = 50
WIDTH = 256
HEIGHT = 256
UPLOAD_URL = "https://fastapi-lance-r2-mvp.fly.dev/vectorize_and_store"
SAVE_DIR = "images"
os.makedirs(SAVE_DIR, exist_ok=True)

for _ in range(NUM_IMAGES):
    start_total = time.time()
    print(f"Generating image {_ + 1} of {NUM_IMAGES}")

    start_download = time.time()
    img_url = f"https://picsum.photos/{WIDTH}/{HEIGHT}"
    headers = {"User-Agent": "gordonmurray.com-Performance-Test/1.0"}
    res = requests.get(img_url, headers=headers)
    download_time = time.time() - start_download
    print(f"Download took: {download_time:.2f}s")

    if res.status_code == 200:
        start_save = time.time()
        image_bytes = res.content
        sha256_hash = hashlib.sha256(image_bytes).hexdigest()
        filename = f"{sha256_hash}.jpg"
        path = os.path.join(SAVE_DIR, filename)

        with open(path, "wb") as f:
            f.write(image_bytes)
        save_time = time.time() - start_save
        #print(f"Save took: {save_time:.2f}s")

        start_upload = time.time()
        with open(path, "rb") as f:
            upload = requests.post(
                UPLOAD_URL,
                files={"file": (filename, f, "image/jpeg")},
                timeout=60
            )
        upload_time = time.time() - start_upload
        #print(f"Upload took: {upload_time:.2f}s")
        print(f"Uploaded {filename} – Status: {upload.status_code}")

        total_time = time.time() - start_total
        print(f"Total time: {total_time:.2f}s")

        time.sleep(1)
