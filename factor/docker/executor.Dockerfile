ARG TARGETPLATFORM
FROM --platform=$TARGETPLATFORM python:3.10-slim-bookworm@sha256:5be5aaecb962a41567bc8041f1e9e3432cb085b037fe057f9a562630b2e4b370
LABEL org.opencontainers.image.title="factor-executor" \
      org.opencontainers.image.source="https://github.com/microsoft/qlib" \
      local.factor.qlib.revision="2fb9380b342556ddb50a4b24e4fe8655d548b2b8" \
      local.factor.qlib.tree="0f541590a9efecb9bfb5342155be50461ad7d002"
RUN groupadd --gid 65532 factor && useradd --uid 65532 --gid 65532 --no-create-home --home-dir /home/runner --shell /usr/sbin/nologin factor \
    && mkdir -p /opt/factor /home/runner /run/input /run/output \
    && chown -R 65532:65532 /opt/factor /home/runner /run/output
COPY requirements/executor.requirements.lock /opt/factor/requirements.lock
COPY wheelhouse/executor/ /opt/factor/wheelhouse/
RUN --network=none python -m pip install --no-index --find-links=/opt/factor/wheelhouse --require-hashes -r /opt/factor/requirements.lock \
    && python -m pip check \
    && python -c "import qlib; import qlib.data._libs.rolling; import qlib.data._libs.expanding" \
    && python -m pip uninstall -y pip wheel \
    && rm -rf /opt/factor/wheelhouse /root/.cache
COPY workers/executor_worker.py /opt/factor/executor_worker.py
USER 65532:65532
WORKDIR /run
ENTRYPOINT ["/usr/local/bin/python", "-I", "/opt/factor/executor_worker.py"]
