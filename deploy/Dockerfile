FROM ubuntu:22.04

ENV DEBIAN_FRONTEND=noninteractive
ENV PYTHONUNBUFFERED=1

RUN apt-get update && apt-get install -y --no-install-recommends \
    python3 python3-pip python3-venv \
    iperf3 curl wget \
    && rm -rf /var/lib/apt/lists/*

# Install fortio
RUN curl -L https://github.com/fortio/fortio/releases/download/v1.63.5/fortio_linux_amd64-1.63.5.tgz \
    | tar xz -C /usr/local/bin fortio

WORKDIR /opt/doublink

COPY pyproject.toml /opt/doublink/
COPY src/ /opt/doublink/src/

RUN python3 -m venv /opt/doublink/venv \
    && /opt/doublink/venv/bin/pip install --no-cache-dir -e .

COPY config/ /opt/doublink/config/

EXPOSE 8090

CMD ["/opt/doublink/venv/bin/python", "-m", "uvicorn", \
     "doublink_tester.api.app:create_app", "--factory", \
     "--host", "0.0.0.0", "--port", "8090", "--log-level", "info"]
