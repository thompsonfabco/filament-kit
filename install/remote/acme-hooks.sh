#!/bin/sh
# certbot hooks for the filament-kit router (installed as /usr/local/sbin/filament-kit-acme-hook).
# This script never touches the firewall: opening port 80 for the run is the owner's job, and certbot
# (standalone) binds :80 itself, so nginx steps aside for the run and comes back after.
#   pre     stop nginx so certbot can bind :80
#   post    start nginx again (also after a failed run)
#   deploy  install the renewed cert for nginx (only for the router's own certificate)
#   check   run before every nginx start: if the certificate and key do not match (a stop part-way through a
#           replace), put back the previous pair, else copy the certificate store's pair again. Never blocks
#           nginx. Off switch: create the file /etc/mcp-router/no-pair-check.
R="${FK_ROOT:-}"   # empty on a real machine; a test points it at a scratch tree
T="$R/etc/mcp-router/tls"

# 0 when the certificate and the key are one pair
pair_ok() {
  a=$(openssl x509 -noout -pubkey -in "$1" 2>/dev/null) || return 1
  b=$(openssl pkey -pubout -in "$2" 2>/dev/null) || return 1
  [ -n "$a" ] && [ "$a" = "$b" ]
}

# put a matching pair from directory $1 in place; each file is copied whole, then renamed
take_pair() {
  pair_ok "$1/fullchain.pem" "$1/privkey.pem" || return 1
  cp "$1/privkey.pem" "$T/privkey.pem.tmp" && chmod 600 "$T/privkey.pem.tmp" &&
    mv "$T/privkey.pem.tmp" "$T/privkey.pem" || return 1
  cp "$1/fullchain.pem" "$T/fullchain.pem.tmp" && chmod 644 "$T/fullchain.pem.tmp" &&
    mv "$T/fullchain.pem.tmp" "$T/fullchain.pem"
}

# keep the pair now in place as the previous one (copied whole, then renamed)
keep_previous() {
  pair_ok "$T/fullchain.pem" "$T/privkey.pem" || return 0
  install -d -m 700 "$T/previous" || return 0
  cp "$T/privkey.pem" "$T/previous/privkey.pem.tmp" && chmod 600 "$T/previous/privkey.pem.tmp" &&
    cp "$T/fullchain.pem" "$T/previous/fullchain.pem.tmp" &&
    mv "$T/previous/privkey.pem.tmp" "$T/previous/privkey.pem" &&
    mv "$T/previous/fullchain.pem.tmp" "$T/previous/fullchain.pem"
  return 0
}

case "$1" in
  pre)  systemctl is-active -q nginx && systemctl stop nginx; exit 0 ;;
  post) systemctl start nginx || true; exit 0 ;;
  deploy)
    HOST=$(cat /etc/mcp-router/host) || exit 1
    # certbot runs deploy hooks for every certificate on the machine; act on ours only
    [ "$(basename "${RENEWED_LINEAGE:-}")" = "$HOST" ] || exit 0
    install -d -m 750 /etc/mcp-router/tls
    keep_previous
    install -m 644 "$RENEWED_LINEAGE/fullchain.pem" /etc/mcp-router/tls/fullchain.pem
    install -m 600 "$RENEWED_LINEAGE/privkey.pem" /etc/mcp-router/tls/privkey.pem
    if systemctl is-active -q nginx; then systemctl reload nginx; fi ;;
  check)
    [ -e "$R/etc/mcp-router/no-pair-check" ] && exit 0
    [ -f "$T/fullchain.pem" ] && [ -f "$T/privkey.pem" ] || exit 0   # nothing there to compare
    command -v openssl >/dev/null 2>&1 || exit 0
    pair_ok "$T/fullchain.pem" "$T/privkey.pem" && exit 0
    HOST=$(cat "$R/etc/mcp-router/host" 2>/dev/null)
    if take_pair "$T/previous"; then
      echo "filament-kit: the saved certificate and key did not belong together, so the previous working pair was put back."
    elif [ -n "$HOST" ] && take_pair "$R/etc/letsencrypt/live/$HOST"; then
      echo "filament-kit: the saved certificate and key did not belong together, so a fresh copy was taken from the certificate store."
    else
      echo "filament-kit: the saved certificate and key do not belong together and no good copy was found; run 'filament-kit apply' to make them again."
    fi
    exit 0 ;;
  *) echo "usage: $0 pre|post|deploy|check"; exit 2 ;;
esac
