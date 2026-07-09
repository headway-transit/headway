# headway-ingest — walking-skeleton ingestion connectors (ADR-0009).
# NOTE: this image is UNTESTED — Docker was not available in the authoring
# environment. Build with:  docker build -t headway-ingest services/ingestion
FROM golang:1.25-alpine AS build
WORKDIR /src
COPY go.mod go.sum ./
RUN go mod download
COPY . .
RUN CGO_ENABLED=0 GOOS=linux go build -trimpath -ldflags="-s -w" \
    -o /out/headway-ingest ./cmd/headway-ingest

FROM gcr.io/distroless/static-debian12:nonroot
COPY --from=build /out/headway-ingest /headway-ingest
USER nonroot
ENTRYPOINT ["/headway-ingest"]
