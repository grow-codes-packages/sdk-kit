# Better Stack Logs intake + SQL query stub (contract-verified, Python standard library only).
# ingest: POST / on 8080   query (ClickHouse HTTP): POST / on 8123   see README.md
FROM python:3.13.18-alpine3.24

RUN adduser -D -H -u 10001 stub && mkdir -m 0755 /app
COPY --chmod=0444 msgpack_decode.py otlp.py sql.py /app/
COPY --chmod=0555 stub.py /app/stub.py

USER 10001
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1
EXPOSE 8080 8123

HEALTHCHECK --interval=5s --timeout=3s --start-period=10s --start-interval=1s --retries=3 \
  CMD ["python", "/app/stub.py", "--healthcheck"]

ENTRYPOINT ["python", "/app/stub.py"]
