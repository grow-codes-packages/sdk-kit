# Grow Codes SDK demo service: the backend behind `sdk-kit new demo` and the
# Docker scenario core.health. Python standard library only.
FROM python:3.13.18-alpine3.24

RUN adduser -D -H -u 10001 demo
COPY --chmod=0555 server.py /app/server.py

USER 10001
ENV DEMO_PORT=8080 \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1
EXPOSE 8080

# compose files override the timings; this keeps `docker run` useful on its own
HEALTHCHECK --interval=5s --timeout=3s --start-period=10s --start-interval=1s --retries=3 \
  CMD ["python", "/app/server.py", "--healthcheck"]

ENTRYPOINT ["python", "/app/server.py"]
