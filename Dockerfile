FROM python:3.13-slim

WORKDIR /app
COPY remote_jobs_api /app/remote_jobs_api

# /data holds the persisted key store (keys.json). In Kubernetes this
# is a PVC mount; locally it's just a directory.
RUN useradd -m -u 10001 apiuser \
    && mkdir -p /data \
    && chown -R apiuser:apiuser /data /app
USER apiuser

VOLUME ["/data"]
EXPOSE 8321
ENV PORT=8321 \
    RJA_KEYS_PATH=/data/keys.json

CMD ["python3", "-m", "remote_jobs_api.server"]
