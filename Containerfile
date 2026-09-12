# --------------------------------------------------------------
# Build stage – install build‑time deps & Python packages
# --------------------------------------------------------------
# Choose one of the three base images:
#   - python-312-minimal  (default)
#   - python-314-minimal
#   - ubi10-minimal (requires manual Python install – see comment)
ARG BASE_IMAGE=registry.access.redhat.com/ubi10/python-314-minimal
FROM ${BASE_IMAGE} AS builder

USER root

# ----------------------------------------------------------------
# Common build‑time packages (gcc, libffi-devel, python3-devel, etc.)
# ----------------------------------------------------------------
# The package manager in UBI10 is `microdnf`.  It is tiny and
# already present in the minimal images.
#RUN set -x ; id && whoami && ls -la /var/cache/

RUN mkdir -p /var/cache/yum/metadata && chmod -R 777 /var/cache/yum && \
    microdnf install -y \
        gcc \
        gcc-c++ \
        make \
        libffi-devel \
        python3-devel && \
    microdnf clean all

# ----------------------------------------------------------------
# Install Python dependencies into a *virtual‑env* (keeps the
# runtime image clean).  The venv will be copied later.
# ----------------------------------------------------------------
WORKDIR /app

# Copy only the lockfile first – this gives us a stable layer cache.
COPY requirements.txt .
RUN python3 -m venv /opt/venv && \
    /opt/venv/bin/pip install --no-cache-dir -r requirements.txt

# ----------------------------------------------------------------
# Runtime stage – minimal image, copy venv & source code
# ----------------------------------------------------------------
FROM ${BASE_IMAGE} AS runtime

# Create a non‑root user (UID 1000 is the default in UBI)
ARG USERNAME=proxyuser
ARG UID=1000
ARG GID=1000

USER root

RUN microdnf install -y shadow-utils && microdnf clean all

RUN groupadd -g ${GID} ${USERNAME} && \
    useradd -m -u ${UID} -g ${GID} ${USERNAME}

# Switch to the non‑root user for the rest of the build
USER ${USERNAME}
WORKDIR /app

# Copy the virtual‑env from the builder stage
#COPY --from=builder /opt/venv /opt/venv
COPY --from=builder --chown=${USERNAME}:${USERNAME} /opt/venv /opt/venv

# Copy the application source files
COPY --chown=${USERNAME}:${USERNAME} ssh_proxy.py entrypoint.sh logging.conf ./

# Ensure the entrypoint is executable
RUN chmod +x entrypoint.sh

# ----------------------------------------------------------------
# Runtime configuration
# ----------------------------------------------------------------
ENV PATH="/opt/venv/bin:$PATH"

# Expose the Flask API port
EXPOSE 5000

# Default command – the entrypoint script starts the server
ENTRYPOINT ["./entrypoint.sh"]

