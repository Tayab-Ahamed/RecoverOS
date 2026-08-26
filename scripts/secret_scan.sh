#!/usr/bin/env bash
# Fail if anything that looks like a live credential is committed.
# Razorpay live keys begin with rzp_live_; test keys begin with rzp_test_.
set -euo pipefail

cd "$(dirname "$0")/.."

fail=0

check() {
  local pattern="$1" label="$2"
  if git grep -nIE -e "$pattern" -- . ':!scripts/secret_scan.sh' ':!.env.example' >/dev/null 2>&1; then
    echo "FAIL: $label"
    git grep -nIE -e "$pattern" -- . ':!scripts/secret_scan.sh' ':!.env.example' || true
    fail=1
  else
    echo "ok:   no $label"
  fi
}

check 'rzp_live_[A-Za-z0-9]+'        'Razorpay LIVE key'
check 'rzp_test_[A-Za-z0-9]{10,}'    'Razorpay test key'
check 'sk-ant-[A-Za-z0-9-]{20,}'     'Anthropic API key'
check 'AKIA[0-9A-Z]{16}'             'AWS access key'
check '-----BEGIN [A-Z ]*PRIVATE KEY-----' 'private key'

if git ls-files --error-unmatch .env >/dev/null 2>&1; then
  echo "FAIL: .env is tracked by git"
  fail=1
else
  echo "ok:   .env is not tracked"
fi

if [ "$fail" -ne 0 ]; then
  echo
  echo "Secret scan FAILED."
  exit 1
fi

echo
echo "Secret scan passed."
