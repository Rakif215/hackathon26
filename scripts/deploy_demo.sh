#!/usr/bin/env bash
# Redeploy the standalone pitch demo (/) and the animated slide deck (/slides.html) to AWS (S3 behind CloudFront).
# Live URL: https://d2wa2y5kr2otft.cloudfront.net
# Bucket and distribution live in the Workshop Studio event account, so they disappear when the event ends.
# Usage: ./scripts/deploy_demo.sh   (needs fresh credentials: ./scripts/aws_creds.sh)
set -euo pipefail

BUCKET="medguard-demo-52024"
DIST_ID="E4J7JDJNGK4K8"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"

aws s3 cp "$ROOT/web/medguard-pitch.html" "s3://$BUCKET/index.html" \
  --content-type "text/html; charset=utf-8" --cache-control "max-age=300"
aws s3 cp "$ROOT/web/slides.html" "s3://$BUCKET/slides.html" \
  --content-type "text/html; charset=utf-8" --cache-control "max-age=300"
aws cloudfront create-invalidation --distribution-id "$DIST_ID" --paths "/*" --query Invalidation.Id --output text
echo "Deployed: https://d2wa2y5kr2otft.cloudfront.net  and  https://d2wa2y5kr2otft.cloudfront.net/slides.html"
