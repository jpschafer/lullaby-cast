FROM debian:trixie-slim

RUN apt-get update \
 && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
      icecast2 gettext-base \
 && rm -rf /var/lib/apt/lists/*

COPY icecast.xml.template /etc/icecast2/icecast.xml.template
COPY entrypoint.sh /entrypoint.sh
RUN chmod 0755 /entrypoint.sh

# Icecast refuses to run as root; the Debian package creates this user.
USER icecast2
ENTRYPOINT ["/entrypoint.sh"]
