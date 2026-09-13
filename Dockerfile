FROM python:3.12-slim
WORKDIR /app
COPY server.py shop-demo.html TOKEN2049-Paydify-demo.html ./
# Cloud-facing defaults. The PAYDIFY_KEY / PAYDIFY_SECRET are NOT baked in —
# set them as env vars / secrets in the hosting dashboard. Never commit the secret.
ENV HOST=0.0.0.0 \
    PORT=8080 \
    DEFAULT_PAGE=shop-demo.html \
    FIXED_AMOUNT=0.10
EXPOSE 8080
CMD ["python3", "server.py"]
