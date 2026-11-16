ARG TARGETPLATFORM
FROM --platform=$TARGETPLATFORM python:3.10-slim-bookworm@sha256:5be5aaecb962a41567bc8041f1e9e3432cb085b037fe057f9a562630b2e4b370
LABEL org.opencontainers.image.title="factor-controller" \
      org.opencontainers.image.source="https://github.com/microsoft/RD-Agent" \
      local.factor.rdagent.revision="484776c211e4fbbeef03e0ec00d6bbee7362a4f4" \
      local.factor.rdagent.tree="d4444284fb4554f75f352ecb1f072cedbf4c6421"
RUN groupadd --gid 65532 factor && useradd --uid 65532 --gid 65532 --no-create-home --home-dir /home/runner --shell /usr/sbin/nologin factor \
    && mkdir -p /opt/factor /home/runner /run/input /run/output \
    && chown -R 65532:65532 /opt/factor /home/runner /run/output
COPY requirements/controller.requirements.lock /opt/factor/requirements.lock
COPY wheelhouse/controller/ /opt/factor/wheelhouse/
RUN --network=none python -m pip install --no-index --find-links=/opt/factor/wheelhouse --require-hashes -r /opt/factor/requirements.lock \
    && python -m pip check \
    && python -m pip uninstall -y pip wheel \
    && rm -rf /opt/factor/wheelhouse /root/.cache
COPY workers/controller_worker.py /opt/factor/controller_worker.py
USER 65532:65532
WORKDIR /run
ENTRYPOINT ["/usr/local/bin/python", "-I", "/opt/factor/controller_worker.py"]
