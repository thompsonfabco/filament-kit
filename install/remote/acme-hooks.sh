#!/bin/sh
# certbot hooks for the filament-kit router (installed as /usr/local/sbin/filament-kit-acme-hook).
# This script never touches the firewall: opening port 80 for the run is the owner's job, and certbot
# (standalone) binds :80 itself, so nginx steps aside for the run and comes back after.
#   pre     stop nginx so certbot can bind :80
#   post    start nginx again (also after a failed run)
#   deploy  install the renewed cert for nginx (only for the router's own certificate)
case "$1" in
  pre)  systemctl is-active -q nginx && systemctl stop nginx; exit 0 ;;
  post) systemctl start nginx || true; exit 0 ;;
  deploy)
    HOST=$(cat /etc/mcp-router/host) || exit 1
    # certbot runs deploy hooks for every certificate on the machine; act on ours only
    [ "$(basename "${RENEWED_LINEAGE:-}")" = "$HOST" ] || exit 0
    install -d -m 750 /etc/mcp-router/tls
    install -m 644 "$RENEWED_LINEAGE/fullchain.pem" /etc/mcp-router/tls/fullchain.pem
    install -m 600 "$RENEWED_LINEAGE/privkey.pem" /etc/mcp-router/tls/privkey.pem
    if systemctl is-active -q nginx; then systemctl reload nginx; fi ;;
  *) echo "usage: $0 pre|post|deploy"; exit 2 ;;
esac
