# Egress gateway for agent containers on an internal (no-route) Docker network: socat forwards a fixed list of
# ports and nothing else (scripts/egress_gw.py). The agent container's only way out is this list.
FROM alpine:3.22
RUN apk add --no-cache socat
USER 65534:65534
ENTRYPOINT ["/bin/sh", "-c"]
