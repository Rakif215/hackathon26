#!/usr/bin/env bash
# Refresh AWS credentials from the Workshop Studio dashboard.
#
#   1. Dashboard -> "Get AWS CLI credentials" -> copy (either format works)
#   2. ./scripts/aws_creds.sh
#
# Accepts BOTH formats Workshop Studio offers — the `export AWS_...` shell block
# and the `[default]` INI block — and always writes a correct ~/.aws/credentials.
# Reads the clipboard by default, or stdin:  ./scripts/aws_creds.sh < creds.txt
set -uo pipefail

CRED_FILE="$HOME/.aws/credentials"

if [ -t 0 ]; then
  command -v pbpaste >/dev/null || { echo "No clipboard tool; pipe the block in instead." >&2; exit 1; }
  INPUT=$(pbpaste)
  echo "Reading credentials from the clipboard..."
else
  INPUT=$(cat)
  echo "Reading credentials from stdin..."
fi

[ -n "${INPUT//[[:space:]]/}" ] || { echo "Nothing to read. Copy the block first." >&2; exit 1; }

mkdir -p "$HOME/.aws"

CREDS="$INPUT" python3 -I -c '
import os, re, pathlib, sys

raw = os.environ["CREDS"]
vals = {}

# export AWS_ACCESS_KEY_ID="..." / AWS_ACCESS_KEY_ID=...
for m in re.finditer(r"^\s*(?:export\s+)?AWS_([A-Z_]+)\s*=\s*[\"\x27]?([^\"\x27\s]+)", raw, re.M):
    vals[m.group(1)] = m.group(2)
# ini style: aws_access_key_id = ...
for m in re.finditer(r"^\s*aws_([a-z_]+)\s*=\s*[\"\x27]?([^\"\x27\s]+)", raw, re.M):
    vals[m.group(1).upper()] = m.group(2)

key = vals.get("ACCESS_KEY_ID")
secret = vals.get("SECRET_ACCESS_KEY")
token = vals.get("SESSION_TOKEN")
region = vals.get("DEFAULT_REGION") or vals.get("REGION") or "us-west-2"

if not key or not secret:
    sys.exit("Could not find an access key and secret in what you pasted. "
             "Copy the whole block from the dashboard and try again.")

block = ["aws_access_key_id = " + key, "aws_secret_access_key = " + secret]
if token:
    block.append("aws_session_token = " + token)

out = "\n".join(["[default]"] + block + ["", "[hackathon]"] + block + [""])
p = pathlib.Path.home() / ".aws" / "credentials"
p.write_text(out)
p.chmod(0o600)

print("Wrote " + str(p))
print("  key    " + key[:4] + "..." + key[-4:])
print("  token  " + ("yes" if token else "NO (temporary creds normally have one)"))
print("  region " + region)
' || exit 1

echo
echo "Verifying..."
aws sts get-caller-identity --output json || {
  echo
  echo "Credentials were written but rejected — they may already have expired."
  echo "Copy a fresh block from the dashboard and run this again."
  exit 1
}
