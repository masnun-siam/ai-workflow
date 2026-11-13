#!/bin/sh
# Create a local self-signed code-signing identity for setu, once per machine.
#
# Why: `go build` gives the binary an ad-hoc signature, and macOS ties a Full Disk Access grant
# to an ad-hoc binary's exact hash, so every rebuild drops the grant. A binary signed with a
# stable certificate and identifier keeps the grant across rebuilds.
set -eu

NAME="${SETU_SIGN_ID:-setu-dev}"
KEYCHAIN="$HOME/Library/Keychains/login.keychain-db"

if security find-certificate -c "$NAME" "$KEYCHAIN" >/dev/null 2>&1; then
	echo "code-signing identity '$NAME' already exists"
	exit 0
fi

tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT

cat >"$tmp/cert.cnf" <<EOF
[req]
distinguished_name = dn
x509_extensions = ext
prompt = no
[dn]
CN = $NAME
[ext]
basicConstraints = critical,CA:false
keyUsage = critical,digitalSignature
extendedKeyUsage = critical,codeSigning
EOF

openssl req -x509 -newkey rsa:2048 -nodes -days 3650 -config "$tmp/cert.cnf" \
	-keyout "$tmp/key.pem" -out "$tmp/cert.pem" 2>/dev/null
pass=$(openssl rand -hex 16)
openssl pkcs12 -export -legacy -inkey "$tmp/key.pem" -in "$tmp/cert.pem" -name "$NAME" \
	-out "$tmp/id.p12" -passout "pass:$pass" 2>/dev/null ||
	openssl pkcs12 -export -inkey "$tmp/key.pem" -in "$tmp/cert.pem" -name "$NAME" \
		-out "$tmp/id.p12" -passout "pass:$pass"

# -T lets codesign use the key without a keychain prompt.
security import "$tmp/id.p12" -k "$KEYCHAIN" -P "$pass" -T /usr/bin/codesign >/dev/null
echo "created code-signing identity '$NAME' in the login keychain"
