#!/bin/sh
# replication labeller: one design -> label_driver (freeze 1's, unchanged), anon re-open check, freeze check
cd /Users/dave/Jane_Street_Reverse_ASIC || exit 9
id="$1"; did=$(echo "$id" | sed 's#/#__#')
echo "=== $id ($did) $(date -u +%Y-%m-%dT%H:%M:%SZ)"
.venv/bin/python -B out/s3/blind/label_driver.py "$id"; lrc=$?
echo "label_driver rc=$lrc"
if [ $lrc -eq 0 ]; then .venv/bin/python -B out/s3/replication/verify_anon.py "$did"; echo "verify_anon rc=$?"; fi
fc=$(.venv/bin/python -m tools.s3.freeze check 2>&1); echo "freeze check: $fc"
[ "$fc" = "freeze holds" ] || { echo "FREEZE DOES NOT HOLD"; exit 3; }
exit $lrc
