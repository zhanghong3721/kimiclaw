#!/bin/bash
# Memory Consolidation 自测脚本
# 用法: ssh 到目标机器后跑 bash selftest.sh

echo "=== 1. Hook 注册 ==="
grep -a 'Registered hook.*memory-stm' /root/.openclaw/logs/openclaw.log 2>/dev/null | tail -1 | python3 -c "
import sys,json
for l in sys.stdin:
 try:
  d=json.loads(l.strip())
  print(d.get('time','')[:25], d.get('1',''))
 except: pass
" || echo "FAIL: hook not registered"

echo ""
echo "=== 2. Timer 状态 ==="
cat /tmp/memory-hook-debug.log 2>/dev/null | tail -3 || echo "FAIL: no timer log"

echo ""
echo "=== 3. OAuth ==="
python3 -c "
import json, time
try:
    with open('/root/.kimi/credentials/kimi-code.json') as f:
        c = json.load(f)
    exp = c.get('expires_at', 0)
    print(f'token: exists, expired: {time.time() > exp}')
except:
    print('FAIL: no credentials')
"

echo ""
echo "=== 4. LTM ==="
python3 -c "
import json, os
p = '/root/.openclaw/workspace/memory_consolidation/state/ltm.json'
if os.path.exists(p):
    d = json.load(open(p))
    print(f'invoke: {d.get(\"invoke_time\")}, generated: {d.get(\"generated_at\")}')
else:
    print('none (new user or not yet generated)')
"

echo ""
echo "=== 5. Diary ==="
ls -lt /root/.openclaw/workspace/memorized_diary/*.md 2>/dev/null | head -3 || echo "none"

echo ""
echo "=== 6. USER.md sections ==="
grep -c "Memory Consolidation" /root/.openclaw/workspace/USER.md && \
grep -c "Visual Memory" /root/.openclaw/workspace/USER.md && \
grep -c "Diary" /root/.openclaw/workspace/USER.md && \
grep -c "Long-Term Memory" /root/.openclaw/workspace/USER.md && \
grep -c "Short-Term Memory" /root/.openclaw/workspace/USER.md && \
echo "All 5 sections present" || echo "FAIL: missing sections"

echo ""
echo "=== 7. STM last_update ==="
grep "last_update" /root/.openclaw/workspace/USER.md | tail -1

echo ""
echo "=== 8. .env ==="
grep -v '^#' /root/.openclaw/workspace/memory_consolidation/memory_consolidation.env | grep -v '^$'

echo ""
echo "=== 9. hooks config ==="
python3 -c "import json; c=json.load(open('/root/.openclaw/openclaw.json')); print(json.dumps(c.get('hooks',{}), indent=2))"

echo ""
echo "=== Done ==="
