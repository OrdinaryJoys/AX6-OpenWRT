// Pure snapshot validator. No subprocesses, firewall/config writes or reloads.
import { stdin, stderr } from 'fs';

function fail(message, status) {
	stderr.write(`AX6 ingress check: ${message}\n`);
	exit(status);
}

function number(value) {
	if (type(value) == 'int') return value;
	if (type(value) != 'string' || !match(value, /^(0x[0-9a-fA-F]+|[0-9]+)$/)) return null;
	return int(value, match(value, /^0x/) ? 16 : 10);
}

function scalar(value) {
	if (type(value) == 'object' && type(value.set) == 'array' && length(value.set) == 1)
		return value.set[0];
	return value;
}

if (length(ARGV) != 6) fail('invalid arguments', 2);
let identity = match(ARGV[0], /^iifname "([a-zA-Z0-9_.:-]{1,15})" meta iif ([1-9][0-9]*)$/);
if (!identity) fail('invalid LAN identity', 2);
let mode = ARGV[1], v6 = ARGV[2], v6mode = ARGV[3], udp = ARGV[4], v6udp = ARGV[5];
if (!match(mode, /^(fake-ip|redir-host)(-tun|-mix)?$/) ||
	!match(v6, /^[01]$/) || !match(v6mode, /^[0-3]$/) ||
	!match(udp, /^[01]$/) || !match(v6udp, /^[01]$/)) fail('unsupported configuration', 2);
let tun = match(mode, /-tun$/) != null, mixed = match(mode, /-mix$/) != null;
let mark4 = tun || mixed || udp == '1' || mode == 'fake-ip';
let mark6 = v6 == '1' && (v6udp == '1' || v6mode != '1');
let expected = {};
function need(target, chain, family, protocol) {
	expected[target] = { chain, family, protocol, lan: 0, lo: 0 };
}
if (!tun) need('openclash', 'dstnat', 'ipv4', 'tcp');
if (mark4) need('openclash_mangle', 'mangle_prerouting', 'ipv4', tun || mixed ? null : 'udp');
if (v6 == '1' && (v6mode == '1' || v6mode == '3')) need('openclash_v6', 'dstnat', 'ipv6', 'tcp');
if (mark6) need('openclash_mangle_v6', 'mangle_prerouting', 'ipv6', null);

let data;
try { data = json(stdin.read('all')); }
catch (error) { fail('malformed snapshot', 2); }
if (type(data?.fw4?.nftables) != 'array') fail('invalid fw4 JSON', 2);
for (let key in ['rule4', 'route4', 'rule6', 'route6'])
	if (type(data[key]) != 'array') fail(`invalid ${key} JSON`, 2);

let chains = {}, backends = {};
for (let item in data.fw4.nftables) {
	let chain = item.chain;
	if (chain?.family == 'inet' && chain.table == 'fw4') chains[chain.name] = chain;
	let rule = item.rule;
	if (!rule || rule.family != 'inet' || rule.table != 'fw4') continue;
	if (type(rule.expr) != 'array') fail('invalid rule expressions', 2);
	backends[rule.chain] ??= [];
	push(backends[rule.chain], rule);
	if (rule.chain != 'dstnat' && rule.chain != 'mangle_prerouting') continue;
	let targets = filter(rule.expr, e => e.jump || e.goto);
	for (let verdict in targets) {
		let target = (verdict.jump || verdict.goto).target;
		if (!match(target, /^openclash(_v6|_mangle|_mangle_v6)?$/)) continue;
		let want = expected[target];
		if (!want || verdict.goto || want.chain != rule.chain) fail(`unexpected ${target} entry`, 1);
		let values = {};
		for (let expr in rule.expr) {
			if ('counter' in expr || expr.jump) continue;
			let m = expr.match;
			if (!m || m.op != '==') fail(`unsupported ${target} entry expression`, 1);
			let key = m.left?.meta?.key;
			if (m.left?.payload) key = `${m.left.payload.protocol}.${m.left.payload.field}`;
			if (!key || key in values) fail(`ambiguous ${target} match`, 1);
			values[key] = scalar(m.right);
			if (key == 'nfproto' && type(values[key]) == 'int')
				values[key] = values[key] == 2 ? 'ipv4' : values[key] == 10 ? 'ipv6' : values[key];
			if ((key == 'ip.protocol' || key == 'ip6.nexthdr') && type(values[key]) == 'int')
				values[key] = values[key] == 6 ? 'tcp' : values[key] == 17 ? 'udp' : values[key];
		}
		let proto = want.family == 'ipv4' ? 'ip.protocol' : 'ip6.nexthdr';
		// nft omits redundant nfproto when an ip/ip6 payload match implies it.
		// The protocol-specific key (not just the TCP/UDP value) binds the family.
		let implicit = want.protocol && values.nfproto == null && values[proto] == want.protocol;
		if ((!implicit && values.nfproto != want.family) || (want.protocol && values[proto] != want.protocol))
			fail(`wrong ${target} family/protocol`, 1);
		let base = (want.protocol ? 2 : 1) - (implicit ? 1 : 0);
		if (values.iifname == identity[1] && number(values.iif) == int(identity[2]) &&
			length(keys(values)) == base + 2) want.lan++;
		else if (rule.chain == 'mangle_prerouting' && values.iifname == 'lo' &&
			number(values.mark) == 354 && length(keys(values)) == base + 2) want.lo++;
		else fail(`unscoped/stale ${target} ingress`, 1);
	}
}
for (let name, want in expected) {
	let base = chains[want.chain];
	if (!base || base.hook != 'prerouting' || base.type != (want.chain == 'dstnat' ? 'nat' : 'filter'))
		fail(`missing/wrong ${want.chain} hook`, 1);
	if (want.lan != 1 || want.lo != (want.chain == 'mangle_prerouting' ? 1 : 0))
		fail(`missing/duplicate ${name} entry`, 1);
	// Reject counter/RETURN-only remnants. This is not reachability proof.
	let functional = false;
	for (let rule in backends[name] || []) for (let expr in rule.expr) {
		if (name == 'openclash' || name == 'openclash_v6') {
			if (expr.redirect) functional = true;
		}
		else if (expr.tproxy || (expr.mangle?.key?.meta?.key == 'mark' && number(expr.mangle.value) == 354))
			functional = true;
	}
	if (!chains[name] || !functional) fail(`missing functional ${name} backend`, 1);
}

function policy(family, needed, tunnel) {
	if (!needed) return;
	let rules = filter(data[`rule${family}`], r => number(r.fwmark) == 354);
	if (length(rules) != 1 || number(rules[0].table) != 354 ||
		(rules[0].fwmask != null && number(rules[0].fwmask) != 4294967295) ||
		(rules[0].src && rules[0].src != 'all') || rules[0].dst || rules[0].iif || rules[0].oif || rules[0].not)
		// TUN routes/rules belong to upstream check_core_status, not the
		// synchronous manual set_firewall path. Do not pretend it repairs them.
		fail(`missing/ambiguous IPv${family} mark rule`, tunnel ? 2 : 1);
	let defaults = filter(data[`route${family}`], r => number(r.table) == 354 && r.dst == 'default');
	let routes = filter(defaults, r =>
		r.dev == (tunnel ? 'utun' : 'lo') && (tunnel ? !r.type || r.type == 'unicast' : r.type == 'local') &&
		!r.gateway && !r.nexthops && index(r.flags || [], 'linkdown') == -1);
	if (length(defaults) != 1 || length(routes) != 1)
		fail(`missing/ambiguous IPv${family} proxy route`, tunnel ? 2 : 1);
}
policy(4, mark4, tun || mixed);
policy(6, mark6, v6mode == '2' || v6mode == '3');
print('PASS: owned LAN/marked-loopback ingress and required policy routes (not full proxy health)\n');
