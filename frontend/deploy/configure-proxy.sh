#!/bin/sh
# Runs when the container starts (nginx image convention). Reads the setting API_UPSTREAM_URL (the address
# of the API service, for example https://iscan-api-dev-123.europe-west3.run.app) and writes the nginx
# configuration from the template. Only the address goes in; it is public. Anything that is not a plain
# address is refused, so a wrong setting cannot inject nginx configuration.
set -eu

url="${API_UPSTREAM_URL:-}"
[ -n "$url" ] || { echo "API_UPSTREAM_URL is required (the address of the API service)" >&2; exit 1; }

case "$url" in
  https://* ) ;;
  http://* )
    [ "${API_UPSTREAM_ALLOW_HTTP:-}" = "1" ] \
      || { echo "API_UPSTREAM_URL must start with https:// (API_UPSTREAM_ALLOW_HTTP=1 allows http for tests)" >&2; exit 1; } ;;
  * ) echo "API_UPSTREAM_URL must start with https://" >&2; exit 1 ;;
esac
case "$url" in
  *[!A-Za-z0-9:/._-]* ) echo "API_UPSTREAM_URL has a character that is not allowed" >&2; exit 1 ;;
esac

# scheme://host[:port] and nothing after it (a trailing slash is tolerated).
origin="${url%/}"
rest="${origin#*://}"
case "$rest" in
  */* ) echo "API_UPSTREAM_URL must be an address without a path" >&2; exit 1 ;;
  "" | :* ) echo "API_UPSTREAM_URL has no host" >&2; exit 1 ;;
esac
hostname="${rest%%:*}"

# The platform's name server (Cloud Run: 169.254.169.254; Docker: its own).
resolver="$(awk '$1 == "nameserver" && $2 ~ /^[0-9.]+$/ { print $2; exit }' /etc/resolv.conf 2> /dev/null || true)"
resolver="${resolver:-169.254.169.254}"

sed \
  -e "s|@UPSTREAM_ORIGIN@|$origin|" \
  -e "s|@UPSTREAM_HOSTNAME@|$hostname|" \
  -e "s|@UPSTREAM_HOST@|$rest|" \
  -e "s|@RESOLVER@|$resolver|" \
  /etc/nginx/iscan/nginx.conf.template > /etc/nginx/conf.d/default.conf
