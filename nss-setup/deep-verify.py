#!/usr/bin/env python3
# deep-verify.py -- prove that offset/fuzz hunks land in the right place.
#
# For every hunk that applied with fuzz or with |offset| > --max-offset,
# rebuild the file state RIGHT BEFORE its patch applied (pristine file +
# all predecessor sections, replayed in chain order), then verify the
# hunk matches that state at EXACTLY ONE position. One exact hit proves
# the placement is correct regardless of how stale the @@ header was;
# zero or multiple hits are flagged for human review.
#
# Inputs (produced by check-patches.sh):
#   $WORK/chain-order.txt        lines "<treename>|<logname>" in apply order
#   $WORK/pristine-manifest.txt  available pristine trees, one name per line
#   $WORK/pristine/<tree>/       unpatched source trees
#   $WORK/*.log                  patch-kernel.sh logs
#
# Exit codes: 0 = every suspicious hunk uniquely anchored; 1 = otherwise.
import argparse
import glob
import os
import re
import shutil
import subprocess
import sys
import tempfile

HUNK_LINE = re.compile(r"^Hunk #(\d+) succeeded at (\d+)(.*)$")


def parse_args():
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", required=True)
    ap.add_argument("--work", required=True)
    ap.add_argument("--max-offset", type=int, default=25)
    ap.add_argument("--patch-root", action="append", default=[])
    return ap.parse_args()


def parse_log(path):
    """Ordered events of one patch-kernel.sh log."""
    events, patch, curfile = [], None, None
    for line in open(path, errors="replace"):
        line = line.rstrip("\n")
        if line.startswith("Applying "):
            patch = line[len("Applying "):].split(" using")[0].strip()
        elif line.startswith("patching file "):
            curfile = line.split(None, 2)[2]
        else:
            m = HUNK_LINE.match(line)
            if m and patch and curfile:
                off = re.search(r"offset (-?\d+)", m.group(3))
                fuz = re.search(r"fuzz (\d+)", m.group(3))
                events.append(dict(
                    patch=patch, file=curfile, hunk=int(m.group(1)),
                    landed=int(m.group(2)),
                    offset=int(off.group(1)) if off else 0,
                    fuzz=int(fuz.group(1)) if fuz else 0))
    return events


def read_chain(work):
    """Ordered (treename, log) pairs from chain-order.txt."""
    order = []
    for line in open(os.path.join(work, "chain-order.txt")):
        line = line.strip()
        if line:
            tree, log = line.split("|", 1)
            order.append((tree, os.path.join(work, log)))
    return order


def patch_targets(path):
    """Files a patch touches (created files included)."""
    tgt = set()
    dev_null = False
    for line in open(path, errors="replace"):
        if line.startswith("--- a/"):
            tgt.add(line[6:].rstrip("\n"))
        elif line.rstrip("\n") == "--- /dev/null":
            dev_null = True
        elif dev_null and line.startswith("+++ b/"):
            tgt.add(line[6:].rstrip("\n"))
            dev_null = False
    return tgt


def extract_section(patchpath, fname):
    """The patch's section for one file, including its ---/+++ header."""
    out, ins = [], False
    hdr = "--- a/" + fname
    for line in open(patchpath, errors="replace"):
        if not ins:
            if line.rstrip("\n") == hdr:
                ins = True
                out.append(line)
            continue
        if line.startswith("--- "):
            break
        out.append(line)
    return "".join(out)


def parse_hunks(section_text):
    """hunk# -> dict(seq, os, ns, suffix): match lines + header info."""
    hunks, idx, cur = {}, 0, None
    for line in section_text.splitlines():
        if line.startswith("@@"):
            idx += 1
            m = re.match(r"@@ -(\d+)(?:,\d+)? \+(\d+)(?:,\d+)? @@(?: (.*))?$", line)
            if not m:
                cur = None
                continue
            cur = dict(seq=[], os=int(m.group(1)), ns=int(m.group(2)),
                       suffix=(m.group(3) or "").strip())
            hunks[idx] = cur
            continue
        if cur is None:
            continue
        if line.startswith("+") or line.startswith("\\"):
            continue  # added lines and '\ No newline' don't consume file lines
        if line.startswith("-") or line.startswith(" "):
            cur["seq"].append(line[1:])
    return hunks


def count_hits(lines, seq):
    n = len(seq)
    return [i for i in range(len(lines) - n + 1) if lines[i:i + n] == seq]


def run_patch_section(section_text, cwd):
    r = subprocess.run(["patch", "-f", "-s", "-p1", "-d", cwd],
                       input=section_text.encode(), capture_output=True)
    if r.returncode != 0:
        raise RuntimeError("section apply failed:\n"
                           + r.stdout.decode(errors="replace")
                           + r.stderr.decode(errors="replace"))


class Prestate:
    def __init__(self, args, order, targets_cache):
        self.args = args
        self.order = order           # ordered list of patch paths (global)
        self.targets = targets_cache
        self.cache = {}

    def pristine_file(self, tree, fname):
        src = os.path.join(self.args.work, "pristine", tree, fname)
        if not os.path.exists(src):
            raise RuntimeError(f"pristine file missing: {src}")
        return src

    def build(self, tree, fname, patchpath):
        key = (tree, fname, patchpath)
        if key in self.cache:
            return self.cache[key]
        try:
            idx = self.order.index(patchpath)
        except ValueError:
            raise RuntimeError(f"patch not in chain order: {patchpath}")
        preds = [p for p in self.order[:idx] if fname in self.targets[p]]

        d = tempfile.mkdtemp(prefix="deep-", dir=os.path.join(self.args.work, "deep-tmp"))
        os.makedirs(os.path.dirname(os.path.join(d, fname)), exist_ok=True)
        shutil.copyfile(self.pristine_file(tree, fname), os.path.join(d, fname))
        for p in preds:
            run_patch_section(extract_section(p, fname), d)
        self.cache[key] = d
        return d


def main():
    args = parse_args()
    work = args.work
    order_log = read_chain(work)
    trees = [l.strip() for l in open(os.path.join(work, "pristine-manifest.txt"))
             if l.strip()]

    events, order = [], []
    for tree, log in order_log:
        if not os.path.exists(log):
            continue
        for ev in parse_log(log):
            ev["tree"] = tree
            events.append(ev)
        for line in open(log, errors="replace"):  # ordered patch paths
            if line.startswith("Applying "):
                p = line[len("Applying "):].split(" using")[0].strip()
                if p not in order:
                    order.append(p)

    targets = {p: patch_targets(p) for p in order}
    pre = Prestate(args, order, targets)

    # Defense in depth: every declared hunk must appear as "Hunk #N succeeded".
    # patch(1) exits 0 while silently dropping a malformed hunk, which then
    # never shows up as an offset/fuzz event, so catch it here too.
    evset = {(ev["patch"], ev["file"], ev["hunk"]) for ev in events}
    missing = []
    for p in order:
        for f in sorted(targets.get(p, ())):
            try:
                sec = extract_section(p, f)
            except OSError:
                continue
            for idx in parse_hunks(sec):
                if (p, f, idx) not in evset:
                    missing.append((p, f, idx))
    if missing:
        print(f"deep: {len(missing)} declared hunk(s) with no successful apply line "
              "(silently dropped or FAILED):")
        for p, f, idx in missing:
            print(f"CHECK {os.path.basename(p)}#{idx} {f}")

    suspicious = [ev for ev in events
                  if ev["fuzz"] > 0 or abs(ev["offset"]) > args.max_offset]
    if not suspicious:
        if missing:
            return 1
        print("deep: nothing to verify (no fuzz, no offsets beyond "
              f"{args.max_offset} lines)")
        return 0

    os.makedirs(os.path.join(work, "deep-tmp"), exist_ok=True)
    nbad = 0
    print(f"deep: verifying {len(suspicious)} suspicious hunks "
          f"(fuzz>0 or |offset|>{args.max_offset}) at application time")
    for ev in suspicious:
        ppath = ev["patch"]
        if not os.path.exists(ppath):  # resolve by basename via patch roots
            cands = []
            for root in args.patch_root:
                cands += glob.glob(os.path.join(root, "**",
                                                os.path.basename(ppath)),
                                   recursive=True)
            ppath = cands[0] if cands else ev["patch"]

        sec = extract_section(ppath, ev["file"])
        seq = parse_hunks(sec).get(ev["hunk"])
        try:
            d = pre.build(ev["tree"], ev["file"], ppath)
        except RuntimeError as e:
            print(f"CHECK {os.path.basename(ppath)}#{ev['hunk']} "
                  f"{ev['file']}: prestate error: {e}")
            nbad += 1
            continue
        if seq is None:
            print(f"CHECK {os.path.basename(ppath)}#{ev['hunk']} {ev['file']}: "
                  "hunk not found in patch")
            nbad += 1
            continue
        prestate = open(os.path.join(d, ev["file"]), errors="replace").read().split("\n")
        hits = count_hits(prestate, seq["seq"])
        base = os.path.basename(ppath)
        if len(hits) == 1:
            print(f"ok    {base}#{ev['hunk']:<3} {ev['file']}  "
                  f"(off={ev['offset']} fuzz={ev['fuzz']}) unique anchor at line "
                  f"{hits[0] + 1}")
        elif ev["landed"] and (ev["landed"] - (seq["ns"] - seq["os"]) - 1) in hits:
            # multi-hit frame: use the build log's authoritative landing
            # (succeeded_at is in new-file coords; ns-os = lines added by
            # this section before the hunk) to see which hit patch took.
            landed = ev["landed"] - (seq["ns"] - seq["os"])  # old-file, 1-based
            ann = seq["suffix"]
            note = f"multi-hit({len(hits)}) picked line {landed}"
            if ann:
                window = prestate[max(0, landed - 300):landed + 5]
                if any(ann[:40] in l for l in window):
                    print(f"ok    {base}#{ev['hunk']:<3} {ev['file']}  "
                          f"(off={ev['offset']} fuzz={ev['fuzz']}) {note}, "
                          f"@@ function confirmed")
                    continue
                print(f"CHECK {base}#{ev['hunk']:<3} {ev['file']}  {note} but "
                      f"@@ function '{ann[:40]}' not found near landing")
                nbad += 1
            else:
                print(f"ok    {base}#{ev['hunk']:<3} {ev['file']}  "
                      f"(off={ev['offset']} fuzz={ev['fuzz']}) {note} "
                      f"(no @@ annotation to cross-check)")
        else:
            nbad += 1
            print(f"CHECK {base}#{ev['hunk']:<3} {ev['file']}  "
                  f"(off={ev['offset']} fuzz={ev['fuzz']}) {len(hits)} matching "
                  f"positions: {hits[:8]}{' ...' if len(hits) > 8 else ''}")

    print(f"deep: {len(suspicious) - nbad}/{len(suspicious)} hunks uniquely "
          f"anchored, {nbad} need review"
          + (f", {len(missing)} declared hunk(s) dropped/failed" if missing else ""))
    return 0 if (nbad == 0 and not missing) else 1


if __name__ == "__main__":
    sys.exit(main())
