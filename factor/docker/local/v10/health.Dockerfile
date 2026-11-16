FROM python:3.11-slim-bookworm@sha256:a83ba18aef0f865b1a4a611c2cf460fe446f2795673bbb9fe43be570439e3b39
LABEL org.opencontainers.image.title="factor-local-health-v10" \
      org.opencontainers.image.base.name="python:3.11-slim-bookworm" \
      org.opencontainers.image.base.digest="sha256:a83ba18aef0f865b1a4a611c2cf460fe446f2795673bbb9fe43be570439e3b39" \
      local.factor.source.revision="83054588043b3a7ac1ce8324c9242164b632beb9" \
      local.factor.arm64.manifest="sha256:464bee9ac10a34b0c86031f12d94d7ccc4643725773b23eff4076305fafab420"
COPY --chown=65532:65532 health_worker.py /opt/factor/health_worker.py
USER 65532:65532
WORKDIR /run
ENTRYPOINT ["/usr/local/bin/python", "-I", "/opt/factor/health_worker.py"]
CMD ["health"]
