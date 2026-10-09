ARG AEARN_RUNTIME_BASE_IMAGE
FROM ${AEARN_RUNTIME_BASE_IMAGE}

WORKDIR /work
COPY --chown=10001:10001 --chmod=0555 harnesses/item_supply/entrypoint.py /opt/aearn/entrypoint.py
COPY --chown=10001:10001 --chmod=0555 harnesses/item_supply/runtime_adapter.py /opt/aearn/runtime-adapter
COPY --chown=10001:10001 --chmod=0444 harnesses/item_supply/python_goal.py /opt/aearn/python_goal.py
COPY --chown=10001:10001 --chmod=0444 harnesses/item_supply/python_state_goal.py /opt/aearn/python_state_goal.py
COPY --chown=10001:10001 --chmod=0444 harnesses/item_supply/runtime-protocol.json /opt/aearn/runtime-protocol.json
USER 10001:10001
ENV AEARN_RUNTIME_ID=python-stdout-v1 AEARN_WALL_CLOCK_SECONDS=5 AEARN_MAX_OUTPUT_BYTES=16384
ENTRYPOINT ["/opt/aearn/entrypoint.py"]
