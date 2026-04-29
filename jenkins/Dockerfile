# ---------------------------------------------------------------------------
# Custom Jenkins image for CurrencyFlow.
#
# Bakes in everything our Jenkinsfile needs so each build doesn't spend time
# installing tools:
#   - Python 3 + venv (for pytest)
#   - Docker CLI    (to build/push images via the host's Docker socket)
#   - sonar-scanner CLI (to send analysis to SonarQube)
#   - useful pre-installed Jenkins plugins (git, pipeline, blueocean, ...)
# ---------------------------------------------------------------------------

FROM jenkins/jenkins:lts-jdk17

USER root

# --- system packages: python, curl, unzip ---
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        python3 python3-pip python3-venv \
        curl unzip ca-certificates lsb-release gnupg \
    && rm -rf /var/lib/apt/lists/*

# --- Docker CLI (talks to the host's docker.sock that we'll mount in compose) ---
RUN install -m 0755 -d /etc/apt/keyrings && \
    curl -fsSL https://download.docker.com/linux/debian/gpg | tee /etc/apt/keyrings/docker.asc > /dev/null && \
    chmod a+r /etc/apt/keyrings/docker.asc && \
    echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/debian $(. /etc/os-release && echo "$VERSION_CODENAME") stable" \
        > /etc/apt/sources.list.d/docker.list && \
    apt-get update && \
    apt-get install -y --no-install-recommends docker-ce-cli && \
    rm -rf /var/lib/apt/lists/*

# --- SonarQube scanner CLI ---
ENV SONAR_SCANNER_VERSION=6.2.1.4610
RUN curl -fsSL -o /tmp/sonar-scanner.zip \
        https://binaries.sonarsource.com/Distribution/sonar-scanner-cli/sonar-scanner-cli-${SONAR_SCANNER_VERSION}-linux-x64.zip && \
    unzip -q /tmp/sonar-scanner.zip -d /opt && \
    mv /opt/sonar-scanner-${SONAR_SCANNER_VERSION}-linux-x64 /opt/sonar-scanner && \
    ln -s /opt/sonar-scanner/bin/sonar-scanner /usr/local/bin/sonar-scanner && \
    rm /tmp/sonar-scanner.zip

USER jenkins

# Pre-install Jenkins plugins so the first-run wizard has them ready.
RUN jenkins-plugin-cli --plugins \
        git \
        github \
        workflow-aggregator \
        pipeline-stage-view \
        blueocean \
        docker-workflow \
        credentials-binding \
        timestamper \
        ws-cleanup
