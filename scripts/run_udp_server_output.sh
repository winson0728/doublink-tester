#!/usr/bin/env bash
set -euo pipefail

NETEMU="http://192.168.105.115:8080"
IPERF_SERVER="192.168.101.101"
RESULTS_DIR=$(ls -dt ~/iperf3_results_* | head -1)
echo "Saving UDP server-output results to: $RESULTS_DIR"

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
    curl -sL -X POST "$NETEMU/api/rules/" -H 'Content-Type: application/json' -d "$1" > /dev/null 2>&1
}

run_udp() {
    local label="$1"
    local bw="${2:-10M}"
    echo "  [UDP] $label ($bw) ..."
    iperf3 -c $IPERF_SERVER -t 10 -u -b "$bw" --get-server-output -J > "$RESULTS_DIR/${label}_udp_sv.json" 2>/dev/null || true
}

echo ""

echo "[1/11] clean"
clear_rules
run_udp "01_clean" "50M"

echo "[2/11] symmetric_loss"
clear_rules
apply_rule '{"interface":"wan_a_in","direction":"egress","bandwidth_kbit":100000,"delay_ms":20,"jitter_ms":5,"loss_pct":2.0}'
apply_rule '{"interface":"lan_a_out","direction":"egress","bandwidth_kbit":100000,"delay_ms":20,"jitter_ms":5,"loss_pct":2.0}'
apply_rule '{"interface":"wan_b_in","direction":"egress","bandwidth_kbit":100000,"delay_ms":20,"jitter_ms":5,"loss_pct":2.0}'
apply_rule '{"interface":"lan_b_out","direction":"egress","bandwidth_kbit":100000,"delay_ms":20,"jitter_ms":5,"loss_pct":2.0}'
sleep 3
run_udp "02_symmetric_loss"

echo "[3/11] symmetric_latency"
clear_rules
apply_rule '{"interface":"wan_a_in","direction":"egress","bandwidth_kbit":20000,"delay_ms":200,"jitter_ms":30,"loss_pct":0.5}'
apply_rule '{"interface":"lan_a_out","direction":"egress","bandwidth_kbit":20000,"delay_ms":200,"jitter_ms":30,"loss_pct":0.5}'
apply_rule '{"interface":"wan_b_in","direction":"egress","bandwidth_kbit":20000,"delay_ms":200,"jitter_ms":30,"loss_pct":0.5}'
apply_rule '{"interface":"lan_b_out","direction":"egress","bandwidth_kbit":20000,"delay_ms":200,"jitter_ms":30,"loss_pct":0.5}'
sleep 3
run_udp "03_symmetric_latency"

echo "[4/11] symmetric_congested"
clear_rules
apply_rule '{"interface":"wan_a_in","direction":"egress","bandwidth_kbit":1000,"delay_ms":200,"jitter_ms":100,"loss_pct":5.0,"corrupt_pct":0.5}'
apply_rule '{"interface":"lan_a_out","direction":"egress","bandwidth_kbit":1000,"delay_ms":200,"jitter_ms":100,"loss_pct":5.0,"corrupt_pct":0.5}'
apply_rule '{"interface":"wan_b_in","direction":"egress","bandwidth_kbit":1000,"delay_ms":200,"jitter_ms":100,"loss_pct":5.0,"corrupt_pct":0.5}'
apply_rule '{"interface":"lan_b_out","direction":"egress","bandwidth_kbit":1000,"delay_ms":200,"jitter_ms":100,"loss_pct":5.0,"corrupt_pct":0.5}'
sleep 3
run_udp "04_symmetric_congested"

echo "[5/11] 5g_degraded"
clear_rules
apply_rule '{"interface":"wan_a_in","direction":"egress","bandwidth_kbit":5000,"delay_ms":80,"jitter_ms":40,"loss_pct":5.0,"corrupt_pct":0.2}'
apply_rule '{"interface":"lan_a_out","direction":"egress","bandwidth_kbit":5000,"delay_ms":80,"jitter_ms":40,"loss_pct":5.0,"corrupt_pct":0.2}'
sleep 3
run_udp "05_5g_degraded"

echo "[6/11] wifi_degraded"
clear_rules
apply_rule '{"interface":"wan_b_in","direction":"egress","bandwidth_kbit":5000,"delay_ms":80,"jitter_ms":40,"loss_pct":5.0,"corrupt_pct":0.2}'
apply_rule '{"interface":"lan_b_out","direction":"egress","bandwidth_kbit":5000,"delay_ms":80,"jitter_ms":40,"loss_pct":5.0,"corrupt_pct":0.2}'
sleep 3
run_udp "06_wifi_degraded"

echo "[7/11] 5g_high_latency"
clear_rules
apply_rule '{"interface":"wan_a_in","direction":"egress","bandwidth_kbit":20000,"delay_ms":300,"jitter_ms":50,"loss_pct":0.5}'
apply_rule '{"interface":"lan_a_out","direction":"egress","bandwidth_kbit":20000,"delay_ms":300,"jitter_ms":50,"loss_pct":0.5}'
apply_rule '{"interface":"wan_b_in","direction":"egress","bandwidth_kbit":100000,"delay_ms":5,"jitter_ms":2,"loss_pct":0}'
apply_rule '{"interface":"lan_b_out","direction":"egress","bandwidth_kbit":100000,"delay_ms":5,"jitter_ms":2,"loss_pct":0}'
sleep 3
run_udp "07_5g_high_latency"

echo "[8/11] wifi_high_latency"
clear_rules
apply_rule '{"interface":"wan_a_in","direction":"egress","bandwidth_kbit":100000,"delay_ms":5,"jitter_ms":2,"loss_pct":0}'
apply_rule '{"interface":"lan_a_out","direction":"egress","bandwidth_kbit":100000,"delay_ms":5,"jitter_ms":2,"loss_pct":0}'
apply_rule '{"interface":"wan_b_in","direction":"egress","bandwidth_kbit":20000,"delay_ms":300,"jitter_ms":50,"loss_pct":0.5}'
apply_rule '{"interface":"lan_b_out","direction":"egress","bandwidth_kbit":20000,"delay_ms":300,"jitter_ms":50,"loss_pct":0.5}'
sleep 3
run_udp "08_wifi_high_latency"

echo "[9/11] asymmetric_mixed"
clear_rules
apply_rule '{"interface":"wan_a_in","direction":"egress","bandwidth_kbit":20000,"delay_ms":200,"jitter_ms":40,"loss_pct":0.5}'
apply_rule '{"interface":"lan_a_out","direction":"egress","bandwidth_kbit":20000,"delay_ms":200,"jitter_ms":40,"loss_pct":0.5}'
apply_rule '{"interface":"wan_b_in","direction":"egress","bandwidth_kbit":50000,"delay_ms":10,"jitter_ms":5,"loss_pct":5.0}'
apply_rule '{"interface":"lan_b_out","direction":"egress","bandwidth_kbit":50000,"delay_ms":10,"jitter_ms":5,"loss_pct":5.0}'
sleep 3
run_udp "09_asymmetric_mixed"

echo "[10/11] wifi_interference"
clear_rules
apply_rule '{"interface":"wan_a_in","direction":"egress","bandwidth_kbit":100000,"delay_ms":5,"loss_pct":0}'
apply_rule '{"interface":"lan_a_out","direction":"egress","bandwidth_kbit":100000,"delay_ms":5,"loss_pct":0}'
apply_rule '{"interface":"wan_b_in","direction":"egress","bandwidth_kbit":50000,"delay_ms":15,"jitter_ms":0,"loss_pct":1.5,"variation":{"enabled":true,"delay_range_ms":10,"jitter_range_ms":15,"loss_range_pct":1.0,"bandwidth_range_kbit":20000,"interval_s":3}}'
apply_rule '{"interface":"lan_b_out","direction":"egress","bandwidth_kbit":50000,"delay_ms":15,"jitter_ms":0,"loss_pct":1.5,"variation":{"enabled":true,"delay_range_ms":10,"jitter_range_ms":15,"loss_range_pct":1.0,"bandwidth_range_kbit":20000,"interval_s":3}}'
sleep 3
run_udp "10_wifi_interference"

echo "[11/11] both_varied"
clear_rules
apply_rule '{"interface":"wan_a_in","direction":"egress","bandwidth_kbit":50000,"delay_ms":30,"jitter_ms":0,"loss_pct":1.0,"variation":{"enabled":true,"delay_range_ms":20,"jitter_range_ms":15,"loss_range_pct":0.5,"bandwidth_range_kbit":20000,"interval_s":5}}'
apply_rule '{"interface":"lan_a_out","direction":"egress","bandwidth_kbit":50000,"delay_ms":30,"jitter_ms":0,"loss_pct":1.0,"variation":{"enabled":true,"delay_range_ms":20,"jitter_range_ms":15,"loss_range_pct":0.5,"bandwidth_range_kbit":20000,"interval_s":5}}'
apply_rule '{"interface":"wan_b_in","direction":"egress","bandwidth_kbit":30000,"delay_ms":20,"jitter_ms":0,"loss_pct":2.0,"variation":{"enabled":true,"delay_range_ms":15,"jitter_range_ms":10,"loss_range_pct":1.0,"bandwidth_range_kbit":15000,"interval_s":5}}'
apply_rule '{"interface":"lan_b_out","direction":"egress","bandwidth_kbit":30000,"delay_ms":20,"jitter_ms":0,"loss_pct":2.0,"variation":{"enabled":true,"delay_range_ms":15,"jitter_range_ms":10,"loss_range_pct":1.0,"bandwidth_range_kbit":15000,"interval_s":5}}'
sleep 3
run_udp "11_both_varied"

echo ""
echo "Cleanup..."
clear_rules
echo "Done!"
