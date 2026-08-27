#!/bin/bash
# ccbox egress firewall — adapted from anthropics/claude-code .devcontainer/init-firewall.sh.
# Differences: the domain list is read from /etc/ccbox/allowed-domains (bind-mounted read-only from
# ~/ccbox/allowed-domains on the host) instead of being hardcoded; a domain that fails to resolve is skipped
# with a warning, not fatal; re-runnable — everything is resolved BEFORE the rules are touched and the ipset is
# swapped in atomically, so a second run works with the policy already at DROP and leaves identical rules.
set -euo pipefail
IFS=$'\n\t'
DOMAINS_FILE=/etc/ccbox/allowed-domains
NEW=allowed-domains-new

# --- 1. resolve everything first (still using the rules from the previous run, if any)
echo "Fetching GitHub IP ranges..."
gh_ranges=$(curl -s --max-time 20 https://api.github.com/meta)
if [ -z "$gh_ranges" ] || ! echo "$gh_ranges" | jq -e '.web and .api and .git' >/dev/null; then
  echo "ERROR: could not fetch GitHub IP ranges"; exit 1
fi
ipset destroy "$NEW" 2>/dev/null || true
ipset create "$NEW" hash:net
while read -r cidr; do
  [[ "$cidr" =~ ^[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}/[0-9]{1,2}$ ]] || { echo "ERROR: bad CIDR from GitHub meta: $cidr"; exit 1; }
  ipset add -exist "$NEW" "$cidr"
done < <(echo "$gh_ranges" | jq -r '(.web + .api + .git)[]' | aggregate -q)
if [ -r "$DOMAINS_FILE" ]; then
  mapfile -t DOMAINS < <(sed 's/#.*//' "$DOMAINS_FILE" | tr -d ' \t\r' | grep -v '^$')
else
  DOMAINS=(api.anthropic.com registry.npmjs.org sentry.io statsig.com)
fi
for domain in "${DOMAINS[@]}"; do
  ips=$(dig +noall +answer +time=3 +tries=2 A "$domain" | awk '$4 == "A" {print $5}')
  if [ -z "$ips" ]; then echo "WARN: could not resolve $domain (skipped)"; continue; fi
  while read -r ip; do
    [[ "$ip" =~ ^[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}$ ]] || { echo "WARN: bad IP for $domain: $ip"; continue; }
    ipset add -exist "$NEW" "$ip"
  done < <(echo "$ips")
  echo "allowed: $domain ($(echo "$ips" | wc -l) addrs)"
done
if ipset list -n allowed-domains >/dev/null 2>&1; then ipset swap "$NEW" allowed-domains; ipset destroy "$NEW"
else ipset rename "$NEW" allowed-domains; fi

# --- 2. rebuild the rules (nothing below needs the network)
DOCKER_DNS_RULES=$(iptables-save -t nat 2>/dev/null | grep "127\.0\.0\.11" || true)
iptables -F; iptables -X; iptables -t nat -F; iptables -t nat -X; iptables -t mangle -F; iptables -t mangle -X
if [ -n "$DOCKER_DNS_RULES" ]; then
  iptables -t nat -N DOCKER_OUTPUT 2>/dev/null || true
  iptables -t nat -N DOCKER_POSTROUTING 2>/dev/null || true
  echo "$DOCKER_DNS_RULES" | xargs -L 1 iptables -t nat
fi
iptables -A INPUT -i lo -j ACCEPT
iptables -A OUTPUT -o lo -j ACCEPT
for ns in $(awk '$1 == "nameserver" {print $2}' /etc/resolv.conf | grep -E '^[0-9.]+$'); do   # DNS only to our resolvers
  iptables -A OUTPUT -d "$ns" -p udp --dport 53 -j ACCEPT
  iptables -A OUTPUT -d "$ns" -p tcp --dport 53 -j ACCEPT
  echo "allowed: nameserver $ns (udp+tcp/53)"
done
iptables -P INPUT DROP; iptables -P FORWARD DROP; iptables -P OUTPUT DROP
iptables -A INPUT -m state --state ESTABLISHED,RELATED -j ACCEPT
iptables -A OUTPUT -m state --state ESTABLISHED,RELATED -j ACCEPT
iptables -A OUTPUT -m set --match-set allowed-domains dst -j ACCEPT
iptables -A OUTPUT -j REJECT --reject-with icmp-admin-prohibited
echo "Firewall configuration complete"
if curl --connect-timeout 5 -s https://example.com >/dev/null 2>&1; then echo "ERROR: firewall verification failed - example.com reachable"; exit 1; fi
echo "verified: example.com blocked"
if ! curl --connect-timeout 5 -s https://api.github.com/zen >/dev/null 2>&1; then echo "ERROR: firewall verification failed - api.github.com unreachable"; exit 1; fi
echo "verified: api.github.com reachable"
