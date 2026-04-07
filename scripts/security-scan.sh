#!/bin/bash
# Semgrep 보안 스캔 — Python 코드 보안 취약점 검사
# 사용: ./scripts/security-scan.sh

echo "🔒 Running Semgrep security scan..."

semgrep scan \
  --config auto \
  --lang python \
  --severity ERROR \
  --severity WARNING \
  --quiet \
  app/ 2>&1

EXIT=$?

if [ $EXIT -ne 0 ]; then
    echo ""
    echo "⚠️  Security issues found. Review above."
else
    echo "✅ No security issues found."
fi

exit $EXIT
