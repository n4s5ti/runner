#!/usr/bin/env bash
set -euo pipefail

if [ "$#" -ne 4 ]; then
  echo "Usage: $0 <artifact.cms> <recipient-cert.pem> <private-key.pem> <output-directory>" >&2
  exit 2
fi

ciphertext="$1"
recipient_cert="$2"
private_key="$3"
output_dir="$4"

for required_file in "$ciphertext" "$recipient_cert" "$private_key"; do
  if [ ! -f "$required_file" ]; then
    echo "Missing required file: $required_file" >&2
    exit 1
  fi
done

if [ -e "$output_dir" ]; then
  echo "Refusing to overwrite existing output path: $output_dir" >&2
  exit 1
fi

umask 077
archive="$(mktemp)"
entries="$(mktemp)"
trap 'rm -f "$archive" "$entries"' EXIT

openssl cms -decrypt -binary -inform DER \
  -in "$ciphertext" \
  -recip "$recipient_cert" \
  -inkey "$private_key" \
  -out "$archive"

tar -tzf "$archive" > "$entries"
if ! cmp -s "$entries" <(printf 'omi-dev.ipa\nreceipt.txt\n'); then
  echo 'Encrypted artifact contains an unexpected file set.' >&2
  exit 1
fi

mkdir -m 700 "$output_dir"
tar -xzf "$archive" -C "$output_dir"
expected_sha256="$(awk -F= '$1 == "sha256" { print $2 }' "$output_dir/receipt.txt")"
actual_sha256="$(shasum -a 256 "$output_dir/omi-dev.ipa" | awk '{print $1}')"
if [ -z "$expected_sha256" ] || [ "$actual_sha256" != "$expected_sha256" ]; then
  rm -rf "$output_dir"
  echo 'Decrypted IPA checksum does not match its signed-build receipt.' >&2
  exit 1
fi

printf 'Decrypted IPA: %s\n' "$output_dir/omi-dev.ipa"
printf 'Receipt: %s\n' "$output_dir/receipt.txt"
