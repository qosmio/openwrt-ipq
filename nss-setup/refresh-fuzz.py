#!/usr/bin/env python3
# refresh-fuzz.py -- regenerate NSS patch hunks so they apply with ZERO fuzz.
#
# Walks the same chain order as check-patches.sh, applying each patch to the
# pristine source with --fuzz=0. When a patch only applies with fuzz, the
# tree still ends up in the correct semantic state, so the patch's file
# section is regenerated from a before/after diff taken at the exact chain
# position. Afterwards all hunks anchor exactly.
#
# A patch is only considered clean when patch(1) exits 0 AND every declared
# hunk was actually applied. patch(1) returns 0 while silently dropping a
# malformed hunk (stray blank line before a hunk header / no trailing
# newline), so those patches are now reported as "structural damage" for
# manual repair instead of being mistaken for healthy.
#
# Usage: refresh-fuzz.py <workdir>
#   <workdir> must contain the pristine trees (linux-<kver>/,
#   backports-<bver>/) -- e.g. a check-patches.sh run directory.
#   Versions are auto-detected from the tree (works on 24.10 and 25.12).

import os, re, shutil, subprocess, sys

WORK = os.path.abspath(sys.argv[1])
REPO = os.path.abspath(os.path.dirname(os.path.abspath(__file__)) + '/..')
GENERIC = REPO + '/target/linux/generic'
MAC = REPO + '/package/kernel/mac80211/patches'

def detect_kver(repo):
    """内核完整版本号(如 6.6.157 / 6.12.112),兼容新旧两种版本文件布局。"""
    cands = []
    for prio, d in ((0, 'target/linux/generic'), (1, 'include')):
        p = os.path.join(repo, d)
        if os.path.isdir(p):
            for f in os.listdir(p):
                m = re.match(r'kernel-(\d+\.\d+)$', f)
                if m:
                    cands.append((prio, m.group(1), os.path.join(p, f)))
    if not cands:
        raise RuntimeError('kernel version file not found')
    _, mm, vf = sorted(cands)[0]
    txt = open(vf, encoding='utf-8', errors='replace').read()
    m = re.search(r'=\s*\.(\d+)', txt)          # 旧布局: LINUX_VERSION-6.6 = .157
    if m:
        return mm + '.' + m.group(1)
    m = re.search(r'(\d+\.\d+\.\d+)', txt)      # 新布局: 6.12.112
    if m:
        return m.group(1)
    raise RuntimeError('cannot parse kernel version from ' + vf)

def detect_bver(repo):
    mk = open(repo + '/package/kernel/mac80211/Makefile',
              encoding='utf-8', errors='replace').read()
    m = re.search(r'^PKG_VERSION\s*:?=\s*(\S+)', mk, re.M)
    if not m:
        raise RuntimeError('mac80211 PKG_VERSION not found')
    return m.group(1)

def run(cmd, cwd=None, check=False):
    r = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)
    if check and r.returncode != 0:
        raise RuntimeError(cmd, r.stdout, r.stderr)
    return r

def applied_hunks(out):
    return len(re.findall(r'^Hunk #\d+ succeeded', out, re.M))

def declared_hunks(patch):
    return sum(1 for l in open(patch, encoding='utf-8', errors='replace')
               if l.startswith('@@'))

def structural_ok(out, patch):
    """patch(1) exits 0 yet silently drops a hunk when the patch file is
    malformed (stray blank line before a hunk header, missing trailing
    newline). Treat 'exit 0' as clean ONLY if every declared hunk applied."""
    return ('unexpectedly ends in middle of line' not in out
            and applied_hunks(out) == declared_hunks(patch))

def restore_tree(tree, snap):
    for f, content in snap.items():
        fp = os.path.join(tree, f)
        if content is None:
            if os.path.exists(fp):
                os.remove(fp)
        else:
            os.makedirs(os.path.dirname(fp), exist_ok=True)
            open(fp, 'w', encoding='utf-8').write(content)

def clean_rej(tree):
    for root, _, files in os.walk(tree):
        for f in files:
            if f.endswith(('.rej', '.orig')):
                os.remove(os.path.join(root, f))

def files_in(patch):
    fs = []
    for l in open(patch, encoding='utf-8', errors='replace'):
        m = re.match(r'^\+\+\+ b/(.+)$', l)
        if m and m.group(1) not in fs:
            fs.append(m.group(1))
    return fs

def ensure_tree(work, name, tarball):
    tree = os.path.join(work, name)
    if os.path.isdir(tree):
        return tree
    print('解压', tarball)
    os.makedirs(tree, exist_ok=True)
    if tarball.endswith('.zst'):
        zst = REPO + '/staging_dir/host/bin/zstd'
        if not os.path.exists(zst):
            zst = 'zstd'
        run(['tar', '-xf', tarball, '-C', tree, '--strip-components=1',
             '-I', zst], check=True)
    else:
        run(['tar', '-xf', tarball, '-C', tree, '--strip-components=1'], check=True)
    return tree

def replace_file_section(patch, fname, newdiff):
    """Replace everything between '--- a/<fname>' and the next file section."""
    lines = open(patch, encoding='utf-8', errors='replace').read().split('\n')
    start = None
    for i, l in enumerate(lines):
        if l == '--- a/%s' % fname:
            start = i
            break
    if start is None:
        print('  ! section not found:', fname)
        return False
    end = len(lines)
    for j in range(start + 2, len(lines)):
        # 真正的节边界: '--- <path>' 且下一行是 '+++ <path>'
        if lines[j].startswith('--- ') and j + 1 < len(lines) \
                and lines[j + 1].startswith('+++ '):
            end = j
            break
    # 新段: --- a/f / +++ b/f / diff内容(去头)
    body = [l for l in newdiff.split('\n')]
    # 去掉 diff 自带头两行(---/+++),以及可能的 "diff --git" 行
    while body and (body[0].startswith('--- ') or body[0].startswith('+++ ')
                    or body[0].startswith('diff ') or body[0].startswith('index ')
                    or body[0] == ''):
        body.pop(0)
    newsec = ['--- a/%s' % fname, '+++ b/%s' % fname] + body
    lines[start:end] = newsec
    data = '\n'.join(lines)
    if not data.endswith('\n'):      # patch(1) drops the last hunk without a final EOL
        data += '\n'
    open(patch, 'w', encoding='utf-8').write(data)
    return True

def process(tree, chain_dirs):
    dirty = []
    for pdir in chain_dirs:
        if not os.path.isdir(pdir):
            continue
        patches = sorted(
            (f for f in os.listdir(pdir) if f.endswith('.patch')),
            key=lambda s: s.encode())
        for pf in patches:
            patch = os.path.join(pdir, pf)
            rel = os.path.relpath(patch, REPO)
            fs = files_in(patch)
            # 快照
            snap = {}
            for f in fs:
                fp = os.path.join(tree, f)
                snap[f] = open(fp, encoding='utf-8', errors='replace').read() \
                    if os.path.exists(fp) else None
            # 先试零 fuzz（--verbose 让 patch 打印每个 hunk，便于核对有没有被静默丢弃）
            r = run(['patch', '-p1', '-d', tree, '--fuzz=0', '--verbose',
                     '--no-backup-if-mismatch', '-i', patch])
            if r.returncode == 0 and structural_ok(r.stdout, patch):
                continue
            # 还原快照(dry-run 失败可能有部分写入?patch 原子性较好,但保险起见)
            restore_tree(tree, snap)
            # 清理失败遗留的 .rej
            clean_rej(tree)
            if r.returncode == 0:
                # 退出码 0 但有 hunk 被静默丢弃:目录状态不完整,不能自动重生成
                print('  !! 结构性损坏(退出码 0 但有 hunk 被静默丢弃,需手工修):', rel)
                print('     ', (r.stdout or '')[-500:].replace('\n', '\n      '))
                dirty.append(patch)
                continue
            # 带 fuzz 应用
            r2 = run(['patch', '-p1', '-d', tree, '--verbose',
                      '--no-backup-if-mismatch', '-i', patch])
            if r2.returncode != 0 or not structural_ok(r2.stdout, patch):
                print('  !! 真实失败(需手工处理):', rel)
                print(r2.stdout[-800:], r2.stderr[-400:])
                dirty.append(patch)
                continue
            if ' with fuzz ' not in r2.stdout:
                continue
            # 有 fuzz:用快照 vs 当前树重新生成涉及文件的段
            print('  ~ regen:', pf)
            for f in fs:
                fp = os.path.join(tree, f)
                before = os.path.join(WORK, '.before', f)
                after = os.path.join(WORK, '.after', f)
                os.makedirs(os.path.dirname(before), exist_ok=True)
                os.makedirs(os.path.dirname(after), exist_ok=True)
                open(before, 'w', encoding='utf-8').write(snap[f] or '')
                open(after, 'w', encoding='utf-8').write(
                    open(fp, encoding='utf-8', errors='replace').read()
                    if os.path.exists(fp) else '')
                d = run(['diff', '-u', before, after])
                if d.stdout:
                    if replace_file_section(patch, f, d.stdout):
                        dirty.append(patch)
                    else:
                        dirty.append(patch + ' (section miss!)')
                # 文件不存在于 after(disppeared)的情形极少,暂不处理
    return dirty

def main():
    DL = REPO + '/dl'
    kver = detect_kver(REPO)
    mm = '.'.join(kver.split('.')[:2])
    bver = detect_bver(REPO)
    print('kernel %s / backports %s' % (kver, bver))

    # ---- 内核链 ----
    kt = ensure_tree(WORK, 'linux-' + kver, '%s/linux-%s.tar.xz' % (DL, kver))
    kdirs = [GENERIC + '/backport-' + mm, GENERIC + '/pending-' + mm,
             GENERIC + '/hack-' + mm,
             REPO + '/target/linux/qualcommax/patches-' + mm]
    print('== kernel chain ==')
    dk = process(kt, kdirs)

    # ---- mac80211 链 ----
    bt = ensure_tree(WORK, 'backports-' + bver, '%s/backports-%s.tar.zst' % (DL, bver))
    dirs = ['build', 'subsys', 'ath', 'ath5k', 'ath9k', 'ath10k', 'ath11k',
            'ath12k', 'rt2x00', 'mt7601u', 'mwl', 'brcm', 'rtl']
    mdirs = [MAC + '/' + d for d in dirs]
    nss = run(['grep', '-oP', r'^NSS_PATCH:=\s*\K.*',
               REPO + '/package/kernel/mac80211/Makefile']).stdout.strip()
    for d in nss.split():
        mdirs.append(MAC + '/nss/' + d)
    print('== mac80211 chain ==')
    dm = process(bt, mdirs)

    print('\n== 受影响补丁 ==')
    for p in dict.fromkeys(dk + dm):
        print(' ', os.path.relpath(p, REPO))

if __name__ == '__main__':
    main()
