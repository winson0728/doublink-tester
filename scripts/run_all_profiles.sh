#!/usr/bin/env bash
set -euo pipefail

NETEMU="http://192.168.105.115:8080"
IPERF_SERVER="192.168.101.101"
RESULTS_DIR=~/iperf3_results_$(date +%Y%m%d_%H%M%S)
mkdir -p "$RESULTS_DIR"

clear_rules() {
    curl -sL $NETEMU/api/rules/ | python3 -c "
import sys, json
for r in json.load(sys.stdin):
    if r.get('status') in ('active','active_varied'):
        print(r['id'])
" 2>/dev/null | while read id; do
        curl -sL -X POST "$NETEMU/api/rules/$id/clear" > /dev/null 2>&1
    done
    sleep 2
}

apply_rule() {
    local data="$1"
    curl -sL -X POST "$NETEMU/api/rules/" -H 'Content-Type: application/json' -d "$data" > /dev/null 2>&1
}

run_tcp() {
    local label="$1"
    echo "  [TCP] $label ..."
    iperf3 -c $IPERF_SERVER -t 10 -P 4 -J > "$RESULTS_DIR/${label}_tcp.json" 2>/dev/null || true
    python3 << PYEOF
import json
try:
    d = json.load(open("$RESULTS_DIR/${label}_tcp.json"))
    recv = d["end"]["sum_received"]
    sent = d["end"]["sum_sent"]
    mbps = recv["bits_per_second"] / 1e6
    retrans = sent.get("retransmits", 0)
    print(f"    TCP: {mbps:.2f} Mbps, retransmits={retrans}")
except Exception as e:
    print(f"    TCP: ERROR - {e}")
PYEOF
}

run_udp() {
    local label="$1"
    local bw="${2:-10M}"
    echo "  [UDP] $label (target ${bw}) ..."
    iperf3 -c $IPERF_SERVER -t 10 -u -b "$bw" -J > "$RESULTS_DIR/${label}_udp.json" 2>/dev/null || true
    python3 << PYEOF
import json
try:
    d = json.load(open("$RESULTS_DIR/${label}_udp.json"))
    s = d["end"]["sum"]
    mbps = s["bits_per_second"] / 1e6
    lost = s.get("lost_packets", 0)
    total = s.get("packets", 1)
    jitter = s.get("jitter_ms", 0)
    loss_pct = (lost / total * 100) if total > 0 else 0
    print(f"    UDP: {mbps:.2f} Mbps, loss={loss_pct:.2f}%, jitter={jitter:.3f}ms")
except Exception as e:
    print(f"    UDP: ERROR - {e}")
PYEOF
}

echo "=========================================="
echo " Doublink iperf3 Full Profile Test"
echo " $(date)"
echo "=========================================="
echo ""

# 1. clean_controlled
echo "[1/15] clean_controlled (baseline)"
clear_rules
run_tcp "01_clean_controlled"
run_udp "01_clean_controlled" "50M"
echo ""

# 2. symmetric_mild_loss
echo "[2/15] symmetric_mild_loss (both lines 2% loss, 20ms delay)"
clear_rules
apply_rule '{"interface":"wan_a_in","direction":"egress","bandwidth_kbit":100000,"delay_ms":20,"jitter_ms":5,"loss_pct":2.0}'
apply_rule '{"interface":"lan_a_out","direction":"egress","bandwidth_kbit":100000,"delay_ms":20,"jitter_ms":5,"loss_pct":2.0}'
apply_rule '{"interface":"wan_b_in","direction":"egress","bandwidth_kbit":100000,"delay_ms":20,"jitter_ms":5,"loss_pct":2.0}'
apply_rule '{"interface":"lan_b_out","direction":"egress","bandwidth_kbit":100000,"delay_ms":20,"jitter_ms":5,"loss_pct":2.0}'
sleep 3
run_tcp "02_symmetric_mild_loss"
run_udp "02_symmetric_mild_loss"
echo ""

# 3. symmetric_mild_latency
echo "[3/15] symmetric_mild_latency (both lines 200ms delay)"
clear_rules
apply_rule '{"interface":"wan_a_in","direction":"egress","bandwidth_kbit":20000,"delay_ms":200,"jitter_ms":30,"loss_pct":0.5}'
apply_rule '{"interface":"lan_a_out","direction":"egress","bandwidth_kbit":20000,"delay_ms":200,"jitter_ms":30,"loss_pct":0.5}'
apply_rule '{"interface":"wan_b_in","direction":"egress","bandwidth_kbit":20000,"delay_ms":200,"jitter_ms":30,"loss_pct":0.5}'
apply_rule '{"interface":"lan_b_out","direction":"egress","bandwidth_kbit":20000,"delay_ms":200,"jitter_ms":30,"loss_pct":0.5}'
sleep 3
run_tcp "03_symmetric_mild_latency"
run_udp "03_symmetric_mild_latency"
echo ""

# 4. congested_recoverable
echo "[4/15] congested_recoverable (both lines 1Kbps, 200ms, 5% loss)"
clear_rules
apply_rule '{"interface":"wan_a_in","direction":"egress","bandwidth_kbit":1000,"delay_ms":200,"jitter_ms":100,"loss_pct":5.0,"corrupt_pct":0.5}'
apply_rule '{"interface":"lan_a_out","direction":"egress","bandwidth_kbit":1000,"delay_ms":200,"jitter_ms":100,"loss_pct":5.0,"corrupt_pct":0.5}'
apply_rule '{"interface":"wan_b_in","direction":"egress","bandwidth_kbit":1000,"delay_ms":200,"jitter_ms":100,"loss_pct":5.0,"corrupt_pct":0.5}'
apply_rule '{"interface":"lan_b_out","direction":"egress","bandwidth_kbit":1000,"delay_ms":200,"jitter_ms":100,"loss_pct":5.0,"corrupt_pct":0.5}'
sleep 3
run_tcp "04_congested_recoverable"
run_udp "04_congested_recoverable"
echo ""

# 5. 5g_degraded_moderate
echo "[5/15] 5g_degraded_moderate (LINE A bad, LINE B clean)"
clear_rules
apply_rule '{"interface":"wan_a_in","direction":"egress","bandwidth_kbit":5000,"delay_ms":80,"jitter_ms":40,"loss_pct":5.0,"corrupt_pct":0.2}'
apply_rule '{"interface":"lan_a_out","direction":"egress","bandwidth_kbit":5000,"delay_ms":80,"jitter_ms":40,"loss_pct":5.0,"corrupt_pct":0.2}'
sleep 3
run_tcp "05_5g_degraded_moderate"
run_udp "05_5g_degraded_moderate"
echo ""

# 6. wifi_degraded_moderate
echo "[6/15] wifi_degraded_moderate (LINE B bad, LINE A clean)"
clear_rules
apply_rule '{"interface":"wan_b_in","direction":"egress","bandwidth_kbit":5000,"delay_ms":80,"jitter_ms":40,"loss_pct":5.0,"corrupt_pct":0.2}'
apply_rule '{"interface":"lan_b_out","direction":"egress","bandwidth_kbit":5000,"delay_ms":80,"jitter_ms":40,"loss_pct":5.0,"corrupt_pct":0.2}'
sleep 3
run_tcp "06_wifi_degraded_moderate"
run_udp "06_wifi_degraded_moderate"
echo ""

# 7. 5g_high_latency_moderate
echo "[7/15] 5g_high_latency_moderate (LINE A 300ms, LINE B normal)"
clear_rules
apply_rule '{"interface":"wan_a_in","direction":"egress","bandwidth_kbit":20000,"delay_ms":300,"jitter_ms":50,"loss_pct":0.5}'
apply_rule '{"interface":"lan_a_out","direction":"egress","bandwidth_kbit":20000,"delay_ms":300,"jitter_ms":50,"loss_pct":0.5}'
apply_rule '{"interface":"wan_b_in","direction":"egress","bandwidth_kbit":100000,"delay_ms":5,"jitter_ms":2,"loss_pct":0}'
apply_rule '{"interface":"lan_b_out","direction":"egress","bandwidth_kbit":100000,"delay_ms":5,"jitter_ms":2,"loss_pct":0}'
sleep 3
run_tcp "07_5g_high_latency_moderate"
run_udp "07_5g_high_latency_moderate"
echo ""

# 8. wifi_high_latency_moderate
echo "[8/15] wifi_high_latency_moderate (LINE B 300ms, LINE A normal)"
clear_rules
apply_rule '{"interface":"wan_a_in","direction":"egress","bandwidth_kbit":100000,"delay_ms":5,"jitter_ms":2,"loss_pct":0}'
apply_rule '{"interface":"lan_a_out","direction":"egress","bandwidth_kbit":100000,"delay_ms":5,"jitter_ms":2,"loss_pct":0}'
apply_rule '{"interface":"wan_b_in","direction":"egress","bandwidth_kbit":20000,"delay_ms":300,"jitter_ms":50,"loss_pct":0.5}'
apply_rule '{"interface":"lan_b_out","direction":"egress","bandwidth_kbit":20000,"delay_ms":300,"jitter_ms":50,"loss_pct":0.5}'
sleep 3
run_tcp "08_wifi_high_latency_moderate"
run_udp "08_wifi_high_latency_moderate"
echo ""

# 9. asymmetric_mixed_moderate
echo "[9/15] asymmetric_mixed_moderate (5G latency + WiFi loss)"
clear_rules
apply_rule '{"interface":"wan_a_in","direction":"egress","bandwidth_kbit":20000,"delay_ms":200,"jitter_ms":40,"loss_pct":0.5}'
apply_rule '{"interface":"lan_a_out","direction":"egress","bandwidth_kbit":20000,"delay_ms":200,"jitter_ms":40,"loss_pct":0.5}'
apply_rule '{"interface":"wan_b_in","direction":"egress","bandwidth_kbit":50000,"delay_ms":10,"jitter_ms":5,"loss_pct":5.0}'
apply_rule '{"interface":"lan_b_out","direction":"egress","bandwidth_kbit":50000,"delay_ms":10,"jitter_ms":5,"loss_pct":5.0}'
sleep 3
run_tcp "09_asymmetric_mixed_moderate"
run_udp "09_asymmetric_mixed_moderate"
echo ""

# 10. 5g_disconnect_visible
echo "[10/15] 5g_disconnect_visible (LINE A 100% loss)"
clear_rules
apply_rule '{"interface":"wan_a_in","direction":"egress","loss_pct":100}'
apply_rule '{"interface":"lan_a_out","direction":"egress","loss_pct":100}'
sleep 3
run_tcp "10_5g_disconnect_visible"
echo ""

# 11. wifi_disconnect_visible
echo "[11/15] wifi_disconnect_visible (LINE B 100% loss)"
clear_rules
apply_rule '{"interface":"wan_b_in","direction":"egress","loss_pct":100}'
apply_rule '{"interface":"lan_b_out","direction":"egress","loss_pct":100}'
sleep 3
run_tcp "11_wifi_disconnect_visible"
echo ""

# 12. 5g_intermittent_visible
echo "[12/15] 5g_intermittent_visible (LINE A flapping every 30s)"
clear_rules
apply_rule '{"interface":"wan_a_in","direction":"egress","bandwidth_kbit":50000,"delay_ms":10,"loss_pct":0.1,"disconnect_schedule":{"enabled":true,"disconnect_duration_s":3,"interval_s":30,"repeat_count":5}}'
apply_rule '{"interface":"lan_a_out","direction":"egress","bandwidth_kbit":50000,"delay_ms":10,"loss_pct":0.1,"disconnect_schedule":{"enabled":true,"disconnect_duration_s":3,"interval_s":30,"repeat_count":5}}'
sleep 3
run_tcp "12_5g_intermittent_visible"
echo ""

# 13. wifi_intermittent_visible
echo "[13/15] wifi_intermittent_visible (LINE B flapping every 30s)"
clear_rules
apply_rule '{"interface":"wan_b_in","direction":"egress","bandwidth_kbit":50000,"delay_ms":10,"loss_pct":0.1,"disconnect_schedule":{"enabled":true,"disconnect_duration_s":3,"interval_s":30,"repeat_count":5}}'
apply_rule '{"interface":"lan_b_out","direction":"egress","bandwidth_kbit":50000,"delay_ms":10,"loss_pct":0.1,"disconnect_schedule":{"enabled":true,"disconnect_duration_s":3,"interval_s":30,"repeat_count":5}}'
sleep 3
run_tcp "13_wifi_intermittent_visible"
echo ""

# 14. wifi_interference_moderate
echo "[14/15] wifi_interference_moderate (LINE A capped, LINE B varied)"
clear_rules
apply_rule '{"interface":"wan_a_in","direction":"egress","bandwidth_kbit":100000,"delay_ms":5,"loss_pct":0}'
apply_rule '{"interface":"lan_a_out","direction":"egress","bandwidth_kbit":100000,"delay_ms":5,"loss_pct":0}'
apply_rule '{"interface":"wan_b_in","direction":"egress","bandwidth_kbit":50000,"delay_ms":15,"jitter_ms":0,"loss_pct":1.5,"variation":{"enabled":true,"delay_range_ms":10,"jitter_range_ms":15,"loss_range_pct":1.0,"bandwidth_range_kbit":20000,"interval_s":3}}'
apply_rule '{"interface":"lan_b_out","direction":"egress","bandwidth_kbit":50000,"delay_ms":15,"jitter_ms":0,"loss_pct":1.5,"variation":{"enabled":true,"delay_range_ms":10,"jitter_range_ms":15,"loss_range_pct":1.0,"bandwidth_range_kbit":20000,"interval_s":3}}'
sleep 3
run_tcp "14_wifi_interference_moderate"
run_udp "14_wifi_interference_moderate"
echo ""

# 15. both_varied_moderate
echo "[15/15] both_varied_moderate (both lines dynamic variation)"
clear_rules
apply_rule '{"interface":"wan_a_in","direction":"egress","bandwidth_kbit":50000,"delay_ms":30,"jitter_ms":0,"loss_pct":1.0,"variation":{"enabled":true,"delay_range_ms":20,"jitter_range_ms":15,"loss_range_pct":0.5,"bandwidth_range_kbit":20000,"interval_s":5}}'
apply_rule '{"interface":"lan_a_out","direction":"egress","bandwidth_kbit":50000,"delay_ms":30,"jitter_ms":0,"loss_pct":1.0,"variation":{"enabled":true,"delay_range_ms":20,"jitter_range_ms":15,"loss_range_pct":0.5,"bandwidth_range_kbit":20000,"interval_s":5}}'
apply_rule '{"interface":"wan_b_in","direction":"egress","bandwidth_kbit":30000,"delay_ms":20,"jitter_ms":0,"loss_pct":2.0,"variation":{"enabled":true,"delay_range_ms":15,"jitter_range_ms":10,"loss_range_pct":1.0,"bandwidth_range_kbit":15000,"interval_s":5}}'
apply_rule '{"interface":"lan_b_out","direction":"egress","bandwidth_kbit":30000,"delay_ms":20,"jitter_ms":0,"loss_pct":2.0,"variation":{"enabled":true,"delay_range_ms":15,"jitter_range_ms":10,"loss_range_pct":1.0,"bandwidth_range_kbit":15000,"interval_s":5}}'
sleep 3
run_tcp "15_both_varied_moderate"
run_udp "15_both_varied_moderate"
echo ""

# Cleanup
echo "Cleanup: clearing all rules"
clear_rules

echo ""
echo "=========================================="
echo " All tests complete!"
echo " Results saved to: $RESULTS_DIR"
echo " $(date)"
echo "=========================================="
echo ""

# Summary table
echo "=== SUMMARY ==="
echo ""
printf "%-25s %12s %10s %12s %8s %10s\n" "Profile" "TCP(Mbps)" "Retrans" "UDP(Mbps)" "Loss%" "Jitter(ms)"
printf "%-25s %12s %10s %12s %8s %10s\n" "-------------------------" "------------" "----------" "------------" "--------" "----------"

for f in "$RESULTS_DIR"/*_tcp.json; do
    base=$(basename "$f" _tcp.json)
    label=$(echo "$base" | sed 's/^[0-9]*_//')

    tcp_mbps=$(python3 -c "
import json
try:
    d=json.load(open('$f'))
    print(f\"{d['end']['sum_received']['bits_per_second']/1e6:.2f}\")
except: print('N/A')
" 2>/dev/null)

    tcp_retr=$(python3 -c "
import json
try:
    d=json.load(open('$f'))
    print(d['end']['sum_sent'].get('retransmits',0))
except: print('N/A')
" 2>/dev/null)

    udp_file="$RESULTS_DIR/${base}_udp.json"
    if [ -f "$udp_file" ]; then
        udp_mbps=$(python3 -c "
import json
try:
    d=json.load(open('$udp_file'))
    print(f\"{d['end']['sum']['bits_per_second']/1e6:.2f}\")
except: print('N/A')
" 2>/dev/null)
        udp_loss=$(python3 -c "
import json
try:
    d=json.load(open('$udp_file'))
    s=d['end']['sum']
    print(f\"{s['lost_packets']/s['packets']*100:.2f}\")
except: print('N/A')
" 2>/dev/null)
        udp_jitter=$(python3 -c "
import json
try:
    d=json.load(open('$udp_file'))
    print(f\"{d['end']['sum'].get('jitter_ms',0):.3f}\")
except: print('N/A')
" 2>/dev/null)
    else
        udp_mbps="-"
        udp_loss="-"
        udp_jitter="-"
    fi

    printf "%-25s %12s %10s %12s %8s %10s\n" "$label" "$tcp_mbps" "$tcp_retr" "$udp_mbps" "$udp_loss" "$udp_jitter"
done
