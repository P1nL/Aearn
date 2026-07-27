ARG AEARN_RUNTIME_BASE_IMAGE
FROM ${AEARN_RUNTIME_BASE_IMAGE}

WORKDIR /work
COPY --chown=10001:10001 --chmod=0555 harnesses/common/entrypoint.py /opt/aearn/entrypoint.py
COPY --chown=10001:10001 runtimes/go-managed-v1/runtime-protocol.json /opt/aearn/runtime-protocol.json
USER 10001:10001
ENV AEARN_RUNTIME_ID=go-managed-v1 \
    AEARN_WALL_CLOCK_SECONDS=15 \
    AEARN_MAX_OUTPUT_BYTES=8192
ENTRYPOINT ["/opt/aearn/entrypoint.py"]
