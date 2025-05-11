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
    config=Config(signature_version="s3v4"),
)

@app.post("/vectorize_and_store")
async def vectorize_and_store(file: UploadFile = File(...)):
    if not file.content_type.startswith("image/"):
        raise HTTPException(400, "File must be an image")

    raw = await file.read()
    try:
        img = Image.open(io.BytesIO(raw)).convert("RGB")
    except Exception:
        raise HTTPException(400, "Unable to read image")

    # Compute SHA256 hash of raw image bytes
    sha256 = hashlib.sha256(raw).hexdigest()
    img_ext = os.path.splitext(file.filename)[1]
    img_key = f"images/{sha256}{img_ext}"

    # Store original image
    s3.put_object(
        Bucket=R2_BUCKET,
        Key=img_key,
        Body=raw,
        ContentType=file.content_type,
    )

    # Store vector
    with torch.no_grad():
        vec = model.get_image_features(
            **processor(images=[img], return_tensors="pt")
        ).squeeze()
    vec = (vec / vec.norm()).cpu().numpy().astype("float32")

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
    except ValueError:
        tbl = db.create_table(
            "images",
            schema=pa.schema([
                ("id",   pa.string()),
                ("path", pa.string()),
                ("vec",  pa.list_(pa.float32(), 512)),
            ])
        )

    tbl.add([{
        "id":   img_key,
        "path": f"s3://{R2_BUCKET}/{img_key}",
        "vec":  vec.tolist(),
    }])

    return {
        "id":        img_key,
        "vectorDim": vec.shape[0],
        "stored":    True,
    }

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

    num_rows = data.num_rows
    num_cols = data.num_columns
    schema = {field.name: str(field.type) for field in data.schema}

    try:
        vec_column = data.column("vec")
        last_vector = vec_column.chunk(0)[-1]
        last_vector_shape = len(last_vector)
    except:
        last_vector_shape = None

    return {
        "rowCount": num_rows,
        "columnCount": num_cols,
        "columns": schema,
        "lastVectorDim": last_vector_shape,
        "tablePath": f"s3://{R2_BUCKET}/vectors/images.lance"
    }

@app.get("/health")
async def health_check():
    return {"status": "ok"}
