# Build from the repository root:
# docker build -f packages/python/gateway/Dockerfile -t nakama-gateway .
FROM python:3.12-slim
WORKDIR /app
COPY pyproject.toml README.md LICENSE ./
COPY packages/python ./packages/python
RUN python -m pip install --no-cache-dir .
RUN useradd --create-home --uid 10001 nakama && mkdir /data && chown nakama:nakama /data
USER nakama
VOLUME ["/data"]
ENV GW_DB=/data/gateway.db GW_HOST=0.0.0.0 PORT=8080
EXPOSE 8080
CMD ["python", "-m", "gateway.server"]
