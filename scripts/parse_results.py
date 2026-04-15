#!/usr/bin/env python3
"""Parse iperf3 JSON results and produce summary table."""
import json, os, glob, re

results_dir = os.popen("ls -dt ~/iperf3_results_* | head -1").read().strip()
results_dir = os.path.expanduser(results_dir)
print(f"Results from: {results_dir}\n")

# Collect TCP data
tcp_data = {}
for f in sorted(glob.glob(f"{results_dir}/*_tcp.json")):
    base = os.path.basename(f).replace("_tcp.json", "")
    label = base.split("_", 1)[1] if "_" in base else base
    try:
        d = json.load(open(f))
        recv = d["end"]["sum_received"]
        sent = d["end"]["sum_sent"]
        tcp_data[label] = {
            "tcp_mbps": recv["bits_per_second"] / 1e6,
            "retrans": sent.get("retransmits", 0),
        }
    except Exception:
        tcp_data[label] = {"tcp_mbps": 0, "retrans": 0}

# Parse UDP server text output
udp_data = {}
file_to_profile = {
    "01_clean": "clean",
    "02_symmetric_loss": "symmetric_loss",
    "03_symmetric_latency": "symmetric_latency",
    "04_symmetric_congested": "symmetric_congested",
    "05_5g_degraded": "5g_degraded",
    "06_wifi_degraded": "wifi_degraded",
    "07_5g_high_latency": "5g_high_latency",
    "08_wifi_high_latency": "wifi_high_latency",
    "09_asymmetric_mixed": "asymmetric_mixed",
    "10_wifi_interference": "wifi_interference",
    "11_both_varied": "both_varied",
}

for f in sorted(glob.glob(f"{results_dir}/*_udp_sv.json")):
    base = os.path.basename(f).replace("_udp_sv.json", "")
    label = file_to_profile.get(base, base)

    try:
        d = json.load(open(f))
        text = d.get("server_output_text", "")
        lines = text.strip().split("\n")

        # Find summary line: contains "0.00-10." and lost/total pattern
        summary = None
        for line in reversed(lines):
            if re.search(r"0\.00-\d+\.\d+\s+sec", line) and "/" in line:
                summary = line.strip()
                break

        if summary:
            # Extract bitrate
            bps_m = re.search(r"([\d.]+)\s+(K|M|G)?bits/sec", summary)
            recv_mbps = 0.0
            if bps_m:
                val = float(bps_m.group(1))
                unit = bps_m.group(2) or "M"
                if unit == "G":
                    recv_mbps = val * 1000
                elif unit == "K":
                    recv_mbps = val / 1000
                else:
                    recv_mbps = val

            # Extract jitter
            jit_m = re.search(r"([\d.]+)\s+ms", summary)
            jitter_ms = float(jit_m.group(1)) if jit_m else 0.0

            # Extract lost/total (percentage)
            loss_m = re.search(r"(-?\d+)/(\d+)\s+\(([\d.e+-]+)%\)", summary)
            if loss_m:
                lost = int(loss_m.group(1))
                total = int(loss_m.group(2))
                loss_pct = float(loss_m.group(3))
                # Clamp negative loss to 0
                if loss_pct < 0:
                    loss_pct = 0.0
            else:
                lost, total, loss_pct = 0, 0, 0.0

            udp_data[label] = {
                "recv_mbps": recv_mbps,
                "jitter_ms": jitter_ms,
                "lost": lost,
                "total": total,
                "loss_pct": loss_pct,
                "raw": summary,
            }
        else:
            udp_data[label] = {"error": "no summary line"}
    except Exception as e:
        udp_data[label] = {"error": str(e)}

# Print combined table
all_profiles = [
    "clean", "symmetric_loss", "symmetric_latency", "symmetric_congested",
    "5g_degraded", "wifi_degraded", "5g_high_latency", "wifi_high_latency",
    "asymmetric_mixed", "5g_disconnect", "wifi_disconnect",
    "5g_intermittent", "wifi_intermittent", "wifi_interference", "both_varied",
]

hdr = f"{'Profile':<25} {'TCP(Mbps)':>12} {'Retrans':>10} {'UDP Recv(Mbps)':>15} {'UDP Loss%':>10} {'Jitter(ms)':>10}"
sep = "-" * len(hdr)
print("=" * len(hdr))
print("DOUBLINK MULTILINK IPERF3 TEST RESULTS")
print("=" * len(hdr))
print()
print(hdr)
print(sep)

for p in all_profiles:
    tcp = tcp_data.get(p, {})
    udp = udp_data.get(p, {})

    t_mbps = f"{tcp['tcp_mbps']:.2f}" if "tcp_mbps" in tcp else "N/A"
    t_ret = str(tcp.get("retrans", "-"))

    if "recv_mbps" in udp:
        u_mbps = f"{udp['recv_mbps']:.2f}"
        u_loss = f"{udp['loss_pct']:.2f}"
        u_jit = f"{udp['jitter_ms']:.3f}"
    else:
        u_mbps = "-"
        u_loss = "-"
        u_jit = "-"

    print(f"{p:<25} {t_mbps:>12} {t_ret:>10} {u_mbps:>15} {u_loss:>10} {u_jit:>10}")

print()
print("=== UDP Server-Side Raw Summary Lines ===")
print()
for p in all_profiles:
    u = udp_data.get(p, {})
    raw = u.get("raw", u.get("error", "-"))
    print(f"  {p}: {raw}")
print()
