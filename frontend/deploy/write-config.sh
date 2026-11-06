#!/bin/sh
# Runs when the container starts (nginx image convention): writes /config.js from API_BASE_URL.
# Only the address of the API goes in; it is public. Characters that could break out of the string
# are refused, so a wrong setting cannot inject script into the page.
set -eu
api="${API_BASE_URL:-}"
case "$api" in
  "" ) ;;
  http://*|https://* ) ;;
  * ) echo "API_BASE_URL must start with http:// or https://" >&2; exit 1 ;;
esac
case "$api" in
  *[!A-Za-z0-9:/._-]* ) echo "API_BASE_URL has a character that is not allowed" >&2; exit 1 ;;
esac
printf 'window.ISCAN_CONFIG = { apiBaseUrl: "%s" };\n' "$api" > /usr/share/nginx/html/config.js
