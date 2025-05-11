## MVP Test Plan for Lance-Based Vector Store

This project explores using the Lance file format to store and search image vector data in a minimal FastAPI-based image ingestion pipeline. All data is stored on Cloudflare R2.

### Goals

- Validate Lance for storing image metadata and vector embeddings
- Understand file growth and structure over time
- Assess search capability, latency, and performance
- Identify limitations in deletion or update workflows

### Checklist

#### ✅ Core Functionality

- [x] Store a single image with its vector embedding in a Lance dataset
- [x] Verify vector is correctly stored and retrievable
- [x] Observe which files/folders are created in the Lance directory (e.g., `data/`, `index/`, `manifest/`)

#### 📈 Appending Data

- [x] Add 5–10 more image+vector entries to the same Lance dataset
- [x] Confirm that appends succeed without data corruption
- [x] Observe which files are modified or appended
- [x] Note any increase in latency for reads or writes

#### ❌ Deleting Data

- [ ] Attempt to logically delete one or more entries from the dataset
- [ ] Verify whether deleted entries still appear in searches
- [ ] Inspect the resulting files for deletion vector metadata

#### 🔍 Vector Search

- [ ] Convert a text prompt (e.g. "blue car") to a vector using the same CLIP/BLIP model
- [ ] Run a similarity search against the dataset
- [ ] Confirm that expected results appear and are ranked appropriately
- [ ] Measure average search latency without any index
- [ ] Create an index (`ivf_pq` or similar) and measure search latency again
- [ ] Compare search accuracy before and after indexing

#### 🚀 Storage Performance

- [ ] Store the Lance dataset in Cloudflare R2
- [ ] Measure time to:
  - Append a record
  - Run a vector search
- [ ] Optionally compare to:
  - Local disk
  - AWS S3
  - S3 Express One Zone (if applicable)

#### 🔁 Concurrency & Durability

- [ ] Simulate concurrent uploads (2–3 at once)
- [ ] Confirm that no data loss or corruption occurs
- [ ] Try uploading a record while another is being queried

#### 📦 Partial Access Behavior

- [ ] Attempt to retrieve only the vector column or only the metadata
- [ ] Measure how many bytes are downloaded (R2 / S3)
- [ ] Confirm expected columnar behavior (partial reads instead of full dataset)

### Future Experiments

- Explore time travel/versioning capabilities of Lance
- Build a simple UI to test image search UX (e.g., SvelteKit)
- Wrap Lance search into a FastAPI endpoint with caching

### Testing

The files and data will end up in a direct structure as follows:

{r2_bucket_name}/images/{sha256}.{ext}
{r2_bucket_name}/images.lance/_transactions/*.txn
{r2_bucket_name}/images.lance/_versions/*.manifest
{r2_bucket_name}/images.lance/data/*.lance



#### Single image test

```
curl -X POST \
  -F "file=@your_image.jpg" \
  https://fastapi-lance-r2-mvp.fly.dev/vectorize_and_store
```

#### Multiple image test

```
#!/bin/bash

ENDPOINT="https://fastapi-lance-r2-mvp.fly.dev/vectorize_and_store"

for file in *.jpg; do
  if [[ -f "$file" ]]; then
    echo "Uploading: $file"

    time_start=$(date +%s%3N)

    response=$(curl -s -w "\nHTTP_STATUS:%{http_code}" -F "file=@$file" "$ENDPOINT")

    time_end=$(date +%s%3N)
    duration=$((time_end - time_start))

    http_status=$(echo "$response" | grep HTTP_STATUS | cut -d':' -f2)
    body=$(echo "$response" | sed '/HTTP_STATUS/d')

    echo "Status: $http_status"
    echo "Response: $body"
    echo "Time taken: ${duration} ms"
    echo "-----------------------------"
  fi
done
```