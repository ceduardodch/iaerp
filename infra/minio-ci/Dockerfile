FROM golang:1.24.8-alpine3.22 AS build
WORKDIR /src
# Official security release, pinned commit and archive checksum. CI only.
RUN wget -q -O /tmp/minio.tar.gz https://codeload.github.com/minio/minio/tar.gz/9e49d5e7a648f00e26f2246f4dc28e6b07f8c84a \
    && echo "45521908307306e925c98d629e1c17d78c8b72b6ee242b1bfb1409f7d8ee5841  /tmp/minio.tar.gz" | sha256sum -c - \
    && tar -xzf /tmp/minio.tar.gz --strip-components=1 -C /src
ENV CGO_ENABLED=0 GOTOOLCHAIN=local
RUN go build -mod=readonly -trimpath \
    -ldflags="-s -w -X github.com/minio/minio/cmd.Version=2025-10-15T17:29:55Z -X github.com/minio/minio/cmd.ReleaseTag=RELEASE.2025-10-15T17-29-55Z -X github.com/minio/minio/cmd.CommitID=9e49d5e7a648f00e26f2246f4dc28e6b07f8c84a" \
    -o /out/minio .

FROM alpine:3.22
RUN apk add --no-cache ca-certificates curl \
    && addgroup -S minio && adduser -S -G minio minio \
    && mkdir /data && chown minio:minio /data
COPY --from=build /out/minio /usr/local/bin/minio
COPY --from=build /src/LICENSE /usr/share/licenses/minio/LICENSE
LABEL org.opencontainers.image.source="https://github.com/minio/minio" \
      org.opencontainers.image.revision=9e49d5e7a648f00e26f2246f4dc28e6b07f8c84a \
      org.opencontainers.image.version="RELEASE.2025-10-15T17-29-55Z" \
      org.opencontainers.image.licenses="AGPL-3.0-only"
USER minio
EXPOSE 9000 9001
ENTRYPOINT ["minio"]
CMD ["server", "/data", "--console-address", ":9001"]
