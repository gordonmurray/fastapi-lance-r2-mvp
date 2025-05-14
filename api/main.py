from fastapi import FastAPI, File, UploadFile, HTTPException
from fastapi.middleware.cors import CORSMiddleware
import torch
from transformers import CLIPProcessor, CLIPModel
from PIL import Image
import io, os, uuid
from dotenv import load_dotenv
import boto3, lancedb, pyarrow as pa
from botocore.client import Config
import hashlib
from fastapi import Query
import logging
import os

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

load_dotenv()

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Load model
model = CLIPModel.from_pretrained("openai/clip-vit-base-patch32")
processor = CLIPProcessor.from_pretrained("openai/clip-vit-base-patch32")

# Config
R2_ENDPOINT = os.getenv("R2_ENDPOINT")
R2_BUCKET   = os.getenv("R2_BUCKET")
R2_ACCESS   = os.getenv("R2_ACCESS_KEY_ID")
R2_SECRET   = os.getenv("R2_SECRET_ACCESS_KEY")

s3 = boto3.client(
    "s3",
    endpoint_url=R2_ENDPOINT,
    aws_access_key_id=R2_ACCESS,
    aws_secret_access_key=R2_SECRET,
    config=Config(
        signature_version="s3v4",
        connect_timeout=5,
        read_timeout=10,
        retries={'max_attempts': 2}
    ),
)

# Vectorize and store an image
# curl -X 'POST' \
#   'https://fastapi-lance-r2-mvp.fly.dev/vectorize_and_store' \
#   -H 'accept: application/json' \
#   -F 'file=@/path/to/image.jpg'

@app.post("/vectorize_and_store")
async def vectorize_and_store(file: UploadFile = File(...)):
    logger.info(f"Starting vectorize_and_store for file: {file.filename}")

    if not file.content_type.startswith("image/"):
        raise HTTPException(400, "File must be an image")

    raw = await file.read()
    try:
        img = Image.open(io.BytesIO(raw)).convert("RGB")
        logger.info("Successfully loaded and converted image")
    except Exception:
        raise HTTPException(400, "Unable to read image")

    sha256 = hashlib.sha256(raw).hexdigest()
    img_ext = os.path.splitext(file.filename)[1]
    img_key = f"images/{sha256}{img_ext}"
    logger.info(f"Generated image key: {img_key}")

    try:
        logger.info("Uploading image to R2...")
        s3.put_object(
            Bucket=R2_BUCKET,
            Key=img_key,
            Body=raw,
            ContentType=file.content_type,
        )
        logger.info("Successfully uploaded image to R2")
    except Exception as e:
        logger.error(f"Failed to store image: {str(e)}")
        raise HTTPException(500, f"Failed to store image: {str(e)}")

    try:
        logger.info("Vectorizing image...")
        with torch.no_grad():
            vec = model.get_image_features(
                **processor(images=[img], return_tensors="pt")
            ).squeeze()
        vec = (vec / vec.norm()).cpu().numpy().astype("float32")
        logger.info("Successfully vectorized image")
    except Exception as e:
        logger.error(f"Failed to vectorize image: {str(e)}")
        raise HTTPException(500, f"Failed to vectorize image: {str(e)}")

    try:
        logger.info("Connecting to LanceDB...")

        db = lancedb.connect(
            f"s3://{R2_BUCKET}/vectors",
            storage_options={
                "aws_access_key_id":     R2_ACCESS,
                "aws_secret_access_key": R2_SECRET,
                "region":                "auto",
                "endpoint":              R2_ENDPOINT,
            },
        )

        logger.info("Successfully connected to LanceDB")

        try:
            logger.info("Opening LanceDB table...")
            tbl = db.open_table("images")
            logger.info("Successfully opened existing table")
        except ValueError:
            logger.info("Creating new LanceDB table...")
            tbl = db.create_table(
                "images",
                schema=pa.schema([
                    ("id",   pa.string()),
                    ("path", pa.string()),
                    ("vector",  pa.list_(pa.float32(), 512)),
                ])
            )
            logger.info("Successfully created new table")

        # Check if index exists and create if needed
        #indices = tbl.list_indices()
        #if not indices:
        #    logger.info("No index found, creating IVF_PQ index...")

        #    import inspect
        #    print("create_index signature:", inspect.signature(tbl.create_index))

        #    tbl.create_index(
        #        metric="cosine",
        #        index_type="IVF_FLAT", # no PQ, less data required
        #        num_partitions=10,
        #        vector_column_name="vector"
        #    )

        #    logger.info("Successfully created IVF_PQ index")
        #else:
        #    logger.info(f"Found existing indices: {indices}")


        # Check for existing vector
        existing = tbl.to_arrow().filter(pa.compute.equal(tbl.to_arrow()['id'], img_key))
        if existing:
            logger.info("Vector already exists, skipping insert.")
        else:
            logger.info("Adding vector to table...")
            tbl.add([{
                "id":   img_key,
                "path": f"s3://{R2_BUCKET}/{img_key}",
                "vector": vec.tolist(),
            }])

        logger.info("Successfully added vector to table")

    except Exception as e:
        logger.error(f"Failed to store vector: {str(e)}")
        raise HTTPException(500, f"Failed to store vector: {str(e)}")

    logger.info("Vectorize and store completed successfully")
    return {
        "id":        img_key,
        "vectorDim": vec.shape[0],
        "stored":    True,
    }

# Get stats
# curl -X 'GET' \
#   'https://fastapi-lance-r2-mvp.fly.dev/stats' \
#   -H 'accept: application/json'

@app.get("/stats")
async def get_stats():
    db = lancedb.connect(
        f"s3://{R2_BUCKET}/vectors",
        storage_options={
            "aws_access_key_id":     R2_ACCESS,
            "aws_secret_access_key": R2_SECRET,
            "region":                "auto",
            "endpoint":              R2_ENDPOINT,
        },
    )

    try:
        tbl = db.open_table("images")
    except Exception as e:
        raise HTTPException(404, detail=f"Lance table not found: {e}")

    data = tbl.to_arrow()
    indices = tbl.list_indices()

    num_rows = data.num_rows
    num_cols = data.num_columns
    schema = {field.name: str(field.type) for field in data.schema}

    try:
        vec_column = data.column("vector")
        last_vector = vec_column.chunk(0)[-1]
        last_vector_shape = len(last_vector)
    except:
        last_vector_shape = None

    return {
        "rowCount": num_rows,
        "columnCount": num_cols,
        "columns": schema,
        "lastVectorDim": last_vector_shape,
        "tablePath": f"s3://{R2_BUCKET}/vectors/images.lance",
        "indices": indices
    }

# Search images
# curl -X 'GET' \
#   'https://fastapi-lance-r2-mvp.fly.dev/search?text=dog' \
#   -H 'accept: application/json'

@app.get("/search")
async def search_images(text: str = Query(..., description="Text to search for")):
    if not text.strip():
        raise HTTPException(400, "Query cannot be empty")

    # Vectorize the input text
    with torch.no_grad():
        text_vec = model.get_text_features(
            **processor(text=[text], return_tensors="pt")
        ).squeeze()
    text_vec = (text_vec / text_vec.norm()).cpu().numpy().astype("float32")

    # Connect to Lance table
    db = lancedb.connect(
        f"s3://{R2_BUCKET}/vectors",
        storage_options={
            "aws_access_key_id":     R2_ACCESS,
            "aws_secret_access_key": R2_SECRET,
            "region":                "auto",
            "endpoint":              R2_ENDPOINT,
        },
    )

    try:
        tbl = db.open_table("images")
    except Exception as e:
        raise HTTPException(404, detail=f"Lance table not found: {e}")

    # Perform nearest-neighbor search
    try:
        raw_results = tbl.search(text_vec).limit(10).to_arrow().to_pylist()

        # Strip vector and deduplicate by 'id'
        seen = set()
        results = []
        for r in raw_results:
            r.pop("vector", None)
            if r["id"] not in seen:
                seen.add(r["id"])
                results.append(r)
            if len(results) >= 3:
                break
    except Exception as e:
        raise HTTPException(500, detail=f"Vector search failed: {e}")

    return {
        "query": text,
        "results": results
    }