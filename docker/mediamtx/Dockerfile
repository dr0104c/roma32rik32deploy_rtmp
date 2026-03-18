FROM bluenviron/mediamtx:1.8.4

RUN set -eux; \
    if command -v apk >/dev/null 2>&1; then \
        apk add --no-cache ffmpeg; \
    elif command -v apt-get >/dev/null 2>&1; then \
        apt-get update; \
        apt-get install -y --no-install-recommends ffmpeg; \
        rm -rf /var/lib/apt/lists/*; \
    else \
        echo "unsupported base image: no package manager found" >&2; \
        exit 1; \
    fi
