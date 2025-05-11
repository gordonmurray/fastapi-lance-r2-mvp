# Deploy to fly.io

The following assumes that the Fly CLI is already installed.

```
fly apps create fastapi-lance-r2-mvp

fly deploy
```

### Set secrets

```
fly secrets set \
  R2_ENDPOINT="https://xxxxxxxxxx.r2.cloudflarestorage.com" \
  R2_ACCESS_KEY_ID="xxxxx" \
  R2_SECRET_ACCESS_KEY="xxxxx" \
  R2_BUCKET="xxxx"
  ```

## Test the API

```
curl -X POST \
  -F "file=@image.jpg" \
  https://fastapi-lance-r2-mvp.fly.dev/vectorize_and_store
```
