# Build from an operator-reviewed, immutable Linux image containing Python 3,
# cryptography, iptables/ip6tables (one reviewed backend), and util-linux setpriv.
# No packages are downloaded by this Dockerfile. No provider credentials in image.
ARG AEARN_EGRESS_BASE
FROM ${AEARN_EGRESS_BASE}
COPY aearn/infra/rag-b-egress/attestor.py aearn/infra/rag-b-egress/run.py aearn/infra/rag-b-egress/worker_entry.py /opt/rag-egress/
ENV PYTHONDONTWRITEBYTECODE=1
ENTRYPOINT ["python3", "/opt/rag-egress/run.py"]
