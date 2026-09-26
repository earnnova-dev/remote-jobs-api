FROM python:3.13-slim

WORKDIR /app
COPY remote_jobs_api /app/remote_jobs_api

EXPOSE 8321
ENV PORT=8321

CMD ["python3", "-m", "remote_jobs_api.server"]
