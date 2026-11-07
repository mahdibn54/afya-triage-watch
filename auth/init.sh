#!/bin/sh
# E13-3 one-shot (auth-init): prepares the local authorization server (Authelia) before it starts.
# Writes only to two volumes: authdata (private: TLS and signing keys, internal secrets, the hashed client secret,
# Authelia's SQLite store; readable by the auth service only) and authca (the public CA certificate the clients trust).
# Generated once and kept: the local CA, the token-signing key, the internal secrets. Renewed on every start: the
# server certificate and the client-secret digest (so a new AFYA_MCP_CLIENT_SECRET in .env takes effect).
# Prints no secret. Rotate everything with: docker compose down && docker volume rm afya_authdata afya_authca
set -eu
: "${AFYA_MCP_CLIENT_SECRET:?set AFYA_MCP_CLIENT_SECRET in .env}"
D=/data; CA=/ca; HOST=auth.afya.internal; UIDGID=8000:8000
umask 077
mkdir -p "$D/tls" "$CA"
q() { "$@" >/dev/null; }

[ -s "$D/tls/ca.private.pem" ] || q authelia crypto certificate rsa generate --ca --common-name "Afya local CA" \
  --organization "Afya Triage Watch (local)" --duration 5y --directory "$D/tls" \
  --file.private-key ca.private.pem --file.certificate ca.public.crt
q authelia crypto certificate rsa generate --common-name "$HOST" --sans "$HOST" --duration 1y \
  --organization "Afya Triage Watch (local)" --path.ca "$D/tls" --directory "$D/tls" \
  --file.private-key server.private.pem --file.certificate server.public.crt
[ -s "$D/jwk.private.pem" ] || q authelia crypto pair rsa generate --bits 2048 --directory "$D" \
  --file.private-key jwk.private.pem --file.public-key jwk.public.pem
for s in hmac storage session reset; do
  [ -s "$D/$s.secret" ] || q authelia crypto rand --length 64 --charset alphanumeric --file "$D/$s.secret"
done
# Pre-registered client (RFC 6749 §2): only the PBKDF2 digest of the secret is stored here.
authelia crypto hash generate pbkdf2 --variant sha512 --password "$AFYA_MCP_CLIENT_SECRET" --no-confirm \
  | sed -n 's/^Digest: //p' > "$D/afya-api.digest"
[ -s "$D/afya-api.digest" ] || { echo "auth-init: could not hash the client secret" >&2; exit 1; }
# The file user backend needs one entry; nobody signs in to this server (service identities only): disabled.
if [ ! -s "$D/users.yml" ]; then
  p=$(authelia crypto rand --length 48 --charset alphanumeric | sed 's/^Random Value: //')
  h=$(authelia crypto hash generate argon2 --password "$p" --no-confirm | sed -n 's/^Digest: //p')
  printf 'users:\n  no-login:\n    disabled: true\n    displayname: "No interactive login"\n    password: "%s"\n' \
    "$h" > "$D/users.yml"
fi
umask 022
cat "$D/tls/ca.public.crt" > "$CA/ca.crt"
chmod 0644 "$CA/ca.crt"
chown -R "$UIDGID" "$D"
echo "auth-init: ready (issuer https://$HOST:9091)"
