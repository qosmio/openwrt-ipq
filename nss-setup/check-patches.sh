#!/bin/bash
# check-patches.sh -- replay OpenWrt patch chains against pristine sources.
#
# Re-extracts sources from dl/ and applies every patch chain in the exact
# order the real build does (scripts/patch-kernel.sh), then reports
# failures, fuzz and offsets. Use it after merging upstream / bumping
# kernels to catch broken NSS patches before they hit a build.
#
# Chains:
#   kernel    target/linux/generic/{backport,pending,hack}-<ver> then
#             target/linux/<target>/patches-<ver>
#   mac80211  package/kernel/mac80211/patches/{build,subsys,ath,...} then
#             patches/nss/<driver> (from NSS_PATCH in the Makefile)
#   pkgs      patches/ of each package (default: qca-nss-dp qca-ssdk)
#
# Usage:
#   check-patches.sh [--target qualcommax] [--only kernel,mac80211,pkgs]
#                    [--pkgs "qca-nss-dp qca-ssdk"] [--deep]
#                    [--max-offset 25] [--keep] [--strict] [-h]
#
# --deep additionally verifies that every hunk which applied with fuzz or
# with an offset beyond --max-offset landed in the right place: the file
# state right before that patch is replayed from a pristine copy and the
# hunk must match it at exactly one position. Needs roughly one extra
# copy of each source tree on disk (removed with the workdir).
#
# Every run also lints the patch files (no stray blank line before a hunk
# header, trailing newline present) and accounts declared @@ hunks against
# the hunks patch(1) reports as applied. patch(1) exits 0 AND writes no
# reject when it silently drops a hunk (that is how a broken 0981-1 patch
# reached a build), so these two checks are what actually catch it.
#
# Exit codes: 0 = clean; 1 = chain failure (or fuzz found with --strict);
#             2 = fuzz found (warnings only by default).
#
# Env: WORKDIR=... keep artifacts in an existing dir; patch(1) options may be
# tweaked via PATCH_OPTS (appended to patch-kernel.sh's PATCH override).

set -u -o pipefail

REPO=$(cd "$(dirname "$0")/.." && pwd)
TARGET=qualcommax
ONLY="kernel mac80211 pkgs"
PKGS="qca-nss-dp qca-ssdk"
KEEP=0
STRICT=0
DEEP=0
MAX_OFFSET=25

usage() { sed -n '2,38p' "$0"; exit 0; }
while [ $# -gt 0 ]; do
	case "$1" in
	--target) TARGET=$2; shift 2 ;;
	--only) ONLY=$(echo "$2" | tr ',' ' '); shift 2 ;;
	--pkgs) PKGS=$2; shift 2 ;;
	--deep) DEEP=1; shift ;;
	--max-offset) MAX_OFFSET=$2; shift 2 ;;
	--keep) KEEP=1; shift ;;
	--strict) STRICT=1; shift ;;
	-h|--help) usage ;;
	*) echo "unknown option: $1" >&2; usage ;;
	esac
done

DL=$REPO/dl
STAGING=$REPO/staging_dir/host/bin
SCRIPTDIR=$REPO/scripts
WORK=${WORKDIR:-$(mktemp -d /tmp/opencode/check-patches.XXXXXX)}
mkdir -p "$WORK"
FAILED_CHAINS=0
FUZZY_CHAINS=0

log() { printf '[check-patches] %s\n' "$*"; }
# --verbose makes patch(1) print "Hunk #N succeeded" for EVERY hunk (even
# offset-0 ones), which account_hunks() relies on to detect silently dropped
# hunks. PATCH_OPTS is still appended so callers can add --fuzz=0 etc.
export PATCH="patch --verbose ${PATCH_OPTS:-}"

# ---------------------------------------------------- patch hygiene helpers
# A hunk that patch(1) silently drops (e.g. a stray blank line before "@@",
# or a missing trailing newline at EOF) produces NO log line and exit code 0,
# so the old checks (exit code / " fuzz " / .rej) missed it entirely. These
# helpers close that gap.

lint_patches() { # lint_patches <patch-dir>... : structural sanity of *.patch
	local d f bad=0 nf=0
	for d in "$@"; do
		[ -d "$d" ] || continue
		while IFS= read -r f; do
			nf=$((nf+1))
			if [ -n "$(tail -c 1 "$f" 2>/dev/null)" ]; then
				log "  LINT $(basename "$f"): no trailing newline (patch(1) may drop the last hunk)"
				bad=1
			fi
			if awk 'prev=="" && /^@@/{found=1} {prev=$0} END{exit !found}' "$f"; then
				log "  LINT $(basename "$f"): blank line before a hunk header (@@) -> the hunk is silently dropped"
				bad=1
			fi
		done < <(find "$d" -maxdepth 1 -type f -name '*.patch' 2>/dev/null | sort)
	done
	[ "$nf" -gt 0 ] && log "  lint: $nf patch file(s) checked, issues=$bad"
	return $bad
}

account_hunks() { # account_hunks <log> -> "patch: declared=X applied=Y" on mismatch
	awk '
	function declared(f,   n, ln) {
		n = 0
		while ((getline ln < f) > 0) if (ln ~ /^@@/) n++
		close(f)
		return n
	}
	function check(   d) {
		if (p == "") return
		d = declared(p)
		# d==0 means the patch could not be read as plain text (e.g. gz) -- skip
		if (d > 0 && d != appl) {
			printf "%s: declared=%d applied=%d\n", p, d, appl
			bad = 1
		}
	}
	/^Applying / { check(); p = $2; sub(/ using.*/, "", p); appl = 0; next }
	/^Hunk #[0-9]+ succeeded/ { appl++ }
	END { check(); if (bad) exit 1 }
	' "$1"
}

keep_pristine() { # keep_pristine <archive> <tree-name> -- pristine copy for --deep
	[ $DEEP -eq 1 ] || return 0
	log "  extracting pristine copy of $2 for deep verification"
	untar "$1" "$WORK/pristine/$2" || return 1
	echo "$2" >> "$WORK/pristine-manifest.txt"
}

untar() { # untar <archive> <dest-dir>
	local ar=$1 dest=$2
	mkdir -p "$dest"
	case "$ar" in
	*.tar.zst)
		local z
		z=$(command -v zstd || true)
		[ -z "$z" ] && [ -x "$STAGING/zstd" ] && z=$STAGING/zstd
		[ -z "$z" ] && { echo "zstd not found (need it for $ar)" >&2; return 1; }
		"$z" -dc "$ar" | tar -x -C "$dest" --strip-components=1
		;;
	*.tar.xz) tar -xJ -C "$dest" --strip-components=1 -f "$ar" ;;
	*.tar.bz2) tar -xj -C "$dest" --strip-components=1 -f "$ar" ;;
	*.tar.gz|*.tgz) tar -xz -C "$dest" --strip-components=1 -f "$ar" ;;
	*) echo "unknown archive type: $ar" >&2; return 1 ;;
	esac
}

resolve_source() { # resolve_source <name> <glob hint...> -> echoes archive path
	local name=$1; shift
	local ar pat
	if [ $# -gt 0 ]; then
		for pat in "$@"; do
			for ar in "$DL"/$pat; do [ -f "$ar" ] && { echo "$ar"; return; }; done
		done
	fi
	local cands
	cands=$(ls -1 "$DL/$name"-*.tar.* 2>/dev/null)
	if [ -n "$cands" ]; then
		if [ "$(printf '%s\n' "$cands" | wc -l)" -gt 1 ]; then
			log "warn: $name: multiple dl/ candidates, picking newest; pass a Makefile hint if wrong"
		fi
		echo "$(printf '%s\n' "$cands" | sort | tail -1)"
		return
	fi
	echo "" # not found
}

apply_chain() { # apply_chain <src-tree> <patch-dir> <log-name>
	local tree=$1 pdir=$2 lname=$3
	[ -d "$pdir" ] || return 0
	local n
	n=$(find "$pdir" -maxdepth 1 -type f | wc -l)
	[ "$n" -eq 0 ] && return 0
	if ! lint_patches "$pdir"; then
		FAIL_BAD=1
		log "  FAILED: structural lint failed in $(basename "$pdir")"
		return 1
	fi
	log "  applying $(basename "$pdir") ($n patches)"
	if ! "$SCRIPTDIR/patch-kernel.sh" "$tree" "$pdir" >"$WORK/$lname" 2>&1; then
		log "  FAILED: see $WORK/$lname (tail below)"
		tail -20 "$WORK/$lname" | sed 's/^/    /'
		return 1
	fi
	echo "$CHAIN_TREE_NAME|$lname" >> "$WORK/chain-order.txt"
	return 0
}

scan_log() { # scan_log <log> <chain-label> ; sets FAIL_BAD / FAIL_FUZZ
	local llog=$1 label=$2
	local fuzz off warn acct
	fuzz=$(grep -c ' fuzz ' "$llog" || true)
	off=$(grep -c '(offset ' "$llog" || true)

	# (a) signs of a malformed patch that patch(1) may still exit 0 on
	warn=$(grep -icE 'unexpectedly ends in middle of line|trailing garbage|Hunk #[0-9]+ FAILED|out of [0-9]+ hunk|can.t find file to patch|Skipping patch' "$llog" || true)
	if [ "$warn" -gt 0 ]; then
		FAIL_BAD=1
		log "  $label: MALFORMED PATCH OUTPUT:"
		grep -inE 'unexpectedly ends in middle of line|trailing garbage|Hunk #[0-9]+ FAILED|out of [0-9]+ hunk|can.t find file to patch|Skipping patch' "$llog" | sed 's/^/    /'
	fi

	# (b) reject files
	if find "$CHAIN_TREE" -name '*.rej' | grep -q .; then
		FAIL_BAD=1
		log "  $label: REJECT FILES: "
		find "$CHAIN_TREE" -name '*.rej' | sed 's/^/    /'
	fi

	# (c) hunk accounting: declared @@ vs "Hunk #N succeeded" in the log
	acct=$(account_hunks "$llog") || true
	if [ -n "$acct" ]; then
		FAIL_BAD=1
		log "  $label: HUNK COUNT MISMATCH (silently dropped hunk):"
		printf '%s\n' "$acct" | sed 's/^/    /'
	fi

	log "  $label: fuzz=$fuzz offset=$off"
	if [ "$fuzz" -gt 0 ]; then
		FAIL_FUZZ=1
		awk '/^Applying/{n=split($0,a,"/"); p=a[n]; sub(/ using.*/,"",p)}
		     /^patching file/{f=$3}
		     / fuzz /{print "    " p "  [" f "]  " $0}' "$llog"
	fi
}

# ---------------------------------------------------------------- kernel chain
check_kernel() {
	local ver point full ar tree
	ver=$(grep -oP '^KERNEL_PATCHVER:=\K.*' "$REPO/target/linux/$TARGET/Makefile")
	point=$(grep -oP "^LINUX_VERSION-$ver = \K.*" "$REPO/target/linux/generic/kernel-$ver" 2>/dev/null || grep -oP "^LINUX_VERSION-$ver = \K.*" "$REPO/include/kernel-$ver")
	full="$ver$point"
	ar=$(resolve_source "linux-$full" "linux-$full.tar.xz")
	if [ -z "$ar" ]; then log "kernel: source dl/linux-$full.tar.* not found"; return 1; fi

	log "kernel: linux-$full from $(basename "$ar")"
	tree=$WORK/linux-$full
	untar "$ar" "$tree" || return 1
	CHAIN_TREE=$tree
	CHAIN_TREE_NAME=linux-$full
	keep_pristine "$ar" "$CHAIN_TREE_NAME" || return 1
	local g=$REPO/target/linux/generic t=$REPO/target/linux/$TARGET rc=0
	local d name
	for d in "$g/backport-$ver:generic-backport" "$g/pending-$ver:generic-pending" \
		 "$g/hack-$ver:generic-hack" "$t/patches-$ver:target"; do
		name=${d##*:}; d=${d%%:*}
		apply_chain "$tree" "$d" "kernel-$name.log" || { rc=1; break; }
		scan_log "$WORK/kernel-$name.log" "$name"
	done
	return $rc
}

# ------------------------------------------------------------- mac80211 chain
check_mac80211() {
	local mf=$REPO/package/kernel/mac80211/Makefile
	local ver ar tree
	ver=$(grep -oP '^PKG_VERSION:=\K.*' "$mf")
	ar=$(resolve_source "backports-$ver" "backports-$ver.tar.zst")
	if [ -z "$ar" ]; then log "mac80211: source dl/backports-$ver.tar.* not found"; return 1; fi

	log "mac80211: backports-$ver from $(basename "$ar")"
	tree=$WORK/backports-$ver
	untar "$ar" "$tree" || return 1
	CHAIN_TREE=$tree
	CHAIN_TREE_NAME=backports-$ver
	keep_pristine "$ar" "$CHAIN_TREE_NAME" || return 1
	local P=$REPO/package/kernel/mac80211/patches rc=0
	local d
	for d in build subsys ath ath5k ath9k ath10k ath11k ath12k rt2x00 mt7601u mwl brcm rtl; do
		apply_chain "$tree" "$P/$d" "mac-$d.log" || { rc=1; break; }
		scan_log "$WORK/mac-$d.log" "$d"
	done
	# NSS patches last, order from NSS_PATCH in the Makefile
	local nssd
	for nssd in $(grep -oP '^NSS_PATCH:=\s*\K.*' "$mf"); do
		apply_chain "$tree" "$P/nss/$nssd" "mac-nss-$nssd.log" || { rc=1; break; }
		scan_log "$WORK/mac-nss-$nssd.log" "nss/$nssd"
	done
	return $rc
}

# ------------------------------------------------------------ packages chain
check_pkgs() {
	local rc=0 pkg ar ver tree mf
	for pkg in $PKGS; do
		mf=$REPO/package/kernel/$pkg/Makefile
		if [ ! -f "$mf" ]; then log "pkgs: $pkg has no Makefile"; rc=1; continue; fi
		ver=$(grep -oP '^PKG_VERSION:=\K.*' "$mf" | head -1)
		d=$(grep -oP '^PKG_SOURCE_DATE:=\K.*' "$mf" | head -1 | tr '-' '.')
		ar=$(resolve_source "$pkg" ${ver:+"$pkg-$ver*.tar.*"} ${d:+"$pkg-$d*.tar.*"})
		if [ -z "$ar" ]; then log "pkgs: $pkg source not found in dl/"; rc=1; continue; fi
		log "pkgs: $pkg from $(basename "$ar")"
		tree=$WORK/$pkg
		rm -rf "$tree"; untar "$ar" "$tree" || { rc=1; continue; }
		CHAIN_TREE=$tree
		CHAIN_TREE_NAME=$pkg
		keep_pristine "$ar" "$CHAIN_TREE_NAME" || { rc=1; continue; }
		apply_chain "$tree" "$REPO/package/kernel/$pkg/patches" "pkg-$pkg.log" || { rc=1; continue; }
		scan_log "$WORK/pkg-$pkg.log" "$pkg"
	done
	return $rc
}

# ----------------------------------------------------------------------- main
log "workdir: $WORK"
overall=0
for chain in $ONLY; do
	FAIL_FUZZ=0
	FAIL_BAD=0
	log "== chain: $chain"
	case $chain in
	kernel) check_kernel; crc=$? ;;
	mac80211) check_mac80211; crc=$? ;;
	pkgs) check_pkgs; crc=$? ;;
	*) log "unknown chain: $chain"; crc=1 ;;
	esac
	if [ $crc -ne 0 ] || [ $FAIL_BAD -ne 0 ]; then
		FAILED_CHAINS=$((FAILED_CHAINS+1)); overall=1
		log "== chain: $chain -> FAILED"
	elif [ $FAIL_FUZZ -ne 0 ]; then
		FUZZY_CHAINS=$((FUZZY_CHAINS+1))
		log "== chain: $chain -> applied, but with FUZZ"
	else
		log "== chain: $chain -> OK"
	fi
done

log "summary: failed_chains=$FAILED_CHAINS fuzzy_chains=$FUZZY_CHAINS"
if [ $overall -eq 0 ] && [ $FUZZY_CHAINS -gt 0 ] && [ $STRICT -eq 1 ]; then overall=2; fi

if [ $DEEP -eq 1 ] && [ $overall -eq 0 ]; then
	log "== deep verification (fuzz/large-offset hunks at application time)"
	if python3 "$REPO/nss-setup/deep-verify.py" --repo "$REPO" --work "$WORK" \
		--max-offset "$MAX_OFFSET" \
		--patch-root "$REPO/target/linux/$TARGET" \
		--patch-root "$REPO/package/kernel" > "$WORK/deep-report.txt" 2>&1; then
		log "deep: PASS ($(grep -c '^ok ' "$WORK/deep-report.txt") hunks uniquely anchored)"
	else
		overall=1
		log "deep: FAIL (report below)"
		cat "$WORK/deep-report.txt" | sed 's/^/    /'
	fi
fi

if [ $overall -eq 0 ] && [ $KEEP -eq 0 ]; then
	rm -rf "$WORK"
	log "clean (workdir removed; use --keep to inspect logs)"
else
	log "artifacts kept in $WORK"
fi
exit $overall
