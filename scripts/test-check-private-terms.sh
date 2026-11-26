#!/usr/bin/env bash
# Test check-private-terms.sh and the tracked hooks in a scratch repo, with a made-up term.
# A push must pass when the commits the remote lacks are clean, even though history the
# remote holds matches, and must be refused when any commit the remote lacks carries the
# term in a file, a file name, its message, its author or committer, or a pushed tag. The
# remote's holdings come from the remote, not from local tracking refs. The hooks must
# refuse every commit and push while the list holds no terms or a bad regex.
# Setup commits skip the hooks, so only the line under test can be refused.
set -euo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
tmp=$(mktemp -d); trap 'rm -rf "$tmp"' EXIT
cd "$tmp"
git init -q --bare remote.git; git init -q --bare empty.git; git init -q --bare empty2.git
git clone -q remote.git work 2>/dev/null; cd work
git config user.email t@example.com; git config user.name t
git config core.hooksPath /dev/null
mkdir -p scripts/hooks; cp "$here/check-private-terms.sh" scripts/; cp "$here/hooks/pre-commit" "$here/hooks/pre-push" scripts/hooks/
list="$(git rev-parse --path-format=absolute --git-common-dir)/info/private-terms"
echo 'zzfaketerm' > "$list"
# History the remote holds: the term in an older tree, with clean messages.
echo zzfaketerm > a.txt; git add .; git commit -q -m "add a"
git rm -q a.txt; git commit -q -m "clean up"; git branch -M main
git push -q origin main
fail=0
zero=0000000000000000000000000000000000000000
expect() {  # name expected_status actual_status
  if [ "$2" = "$3" ]; then echo "ok   $1"; else echo "FAIL $1 (exit $3, wanted $2)"; fail=1; fi
}
push_check() {  # ref [remote [url]] -> exit status of the check
  echo "$1 $(git rev-parse "$1") $1 $zero" | scripts/check-private-terms.sh --push "${2:-origin}" "${3:-${2:-origin}}" >/dev/null 2>&1
}
staged_check() {  # -> exit status of the check on the index, then the index is emptied
  local s=0; scripts/check-private-terms.sh --staged >/dev/null 2>&1 || s=$?
  git reset -q --hard; git clean -q -fd -e scripts; return $s
}
commit() { git commit -q --allow-empty "$@"; }

git checkout -q -b clean main; echo ok > b.txt; git add b.txt; commit -m "clean change"
push_check refs/heads/clean && s=0 || s=$?; expect "new branch, clean commits, matching history on remote" 0 $s
git checkout -q -b dirtyfile main; echo zzfaketerm > c.txt; git add c.txt; commit -m "add c"
push_check refs/heads/dirtyfile && s=0 || s=$?; expect "new branch, the term in a file" 1 $s
git checkout -q -b dirtymsg main; commit -m "mentions zzfaketerm"
push_check refs/heads/dirtymsg && s=0 || s=$?; expect "new branch, the term in a message" 1 $s
git checkout -q -b oldtree main; echo zzfaketerm > m.txt; git add m.txt; commit -m "add m"
git rm -q m.txt; commit -m "remove m"
push_check refs/heads/oldtree && s=0 || s=$?; expect "new branch, the term only in an older new commit's tree" 1 $s
git checkout -q clean; git push -q origin clean; echo more > e.txt; git add e.txt; commit -m "more"
push_check refs/heads/clean && s=0 || s=$?; expect "existing branch, clean update" 0 $s
echo zzfaketerm > f.txt; git add f.txt; commit -m "add f"
push_check refs/heads/clean && s=0 || s=$?; expect "existing branch, the term in a file" 1 $s
git reset -q --hard origin/clean

# Finding 1: the remote's holdings come from the remote, not local tracking refs.
push_check refs/heads/clean empty "$tmp/empty.git" && s=0 || s=$?; expect "empty remote, history with the term only in an older tree" 1 $s
git remote set-url origin "$tmp/empty.git"
push_check refs/heads/clean && s=0 || s=$?; expect "remote repointed to an empty repo, stale tracking refs" 1 $s
git checkout -q --orphan fresh; git rm -q -r --cached . ; git clean -q -fd -e scripts; echo ok > n.txt; git add n.txt; commit -m "first"
push_check refs/heads/fresh && s=0 || s=$?; expect "remote repointed, a fresh clean root" 0 $s
git remote set-url origin "$tmp/remote.git"; git checkout -q -f clean
# Finding 4: file names.
git checkout -q -b names clean; echo ok > zzfaketerm-notes.md; git add .; commit -m "add notes"
push_check refs/heads/names && s=0 || s=$?; expect "push, the term only in a file name" 1 $s
scripts/check-private-terms.sh >/dev/null 2>&1 && s=0 || s=$?; expect "working tree, the term only in a file name" 1 $s
git checkout -q clean
echo ok > zzfaketerm-notes.md; git add .; staged_check && s=0 || s=$?; expect "staged, the term only in a file name" 1 $s
# Finding 5: author, committer and tag messages.
git checkout -q -b author clean; commit --author="a <me@zzfaketerm.com>" -m "clean"
push_check refs/heads/author && s=0 || s=$?; expect "push, the term in an author email" 1 $s
git checkout -q -b committer clean; GIT_COMMITTER_NAME=zzfaketerm commit -m "clean"
push_check refs/heads/committer && s=0 || s=$?; expect "push, the term in a committer name" 1 $s
git checkout -q clean; git tag -a v1 -m "release for zzfaketerm"
push_check refs/tags/v1 && s=0 || s=$?; expect "push, the term in an annotated tag's message" 1 $s
# A remote holding only a commit this clone lacks: a clean root still passes.
git init -q --bare "$tmp/foreign.git"; git init -q ../other
(cd ../other && git -c user.email=t@example.com -c user.name=t commit -q --allow-empty -m "elsewhere" && git push -q "$tmp/foreign.git" HEAD:refs/heads/elsewhere)
push_check refs/heads/fresh foreign "$tmp/foreign.git" && s=0 || s=$?; expect "push, the remote holds only a commit this clone lacks" 0 $s
# Review 3, C: an annotated tag naming a blob.
git tag -a blobtag -m "clean" "$(printf 'zzfaketerm\n' | git hash-object -w --stdin)"
push_check refs/tags/blobtag && s=0 || s=$?; expect "push, an annotated tag naming a blob with the term" 1 $s
# Review 3, A: a non-ASCII term in a file name (git quotes such names unless asked not to).
printf 'zzfaketerm\njos\303\251\n' > "$list"
git checkout -q -b accents clean; echo ok > "jos$(printf '\303\251')-notes.md"; git add .; commit -m "add notes"
push_check refs/heads/accents && s=0 || s=$?; expect "push, a non-ASCII term in a file name" 1 $s
scripts/check-private-terms.sh >/dev/null 2>&1 && s=0 || s=$?; expect "working tree, a non-ASCII term in a file name" 1 $s
git checkout -q clean
echo ok > "jos$(printf '\303\251')-notes.md"; git add .; staged_check && s=0 || s=$?; expect "staged, a non-ASCII term in a file name" 1 $s
# Review 3, B: a GNU-style escape the list check accepts must also match file contents.
printf 'zzfaketerm\n\\bzzword\\b\n' > "$list"
git checkout -q -b escape clean; echo "a zzword b" > t.txt; git add t.txt; commit -m "add t"; git rm -q t.txt; commit -m "remove t"
push_check refs/heads/escape && s=0 || s=$?; expect "push, a \\b term only in an older tree" 1 $s
git checkout -q clean
echo "a zzword b" > t.txt; git add t.txt; staged_check && s=0 || s=$?; expect "staged, a \\b term in a file" 1 $s
echo 'zzfaketerm' > "$list"
# Review 4: bytes that aren't valid UTF-8 must not hide a line, in a text file or a binary
# whose first NUL comes late (grep in a UTF-8 locale skips such lines).
# LC_ALL, not LANG: an exported LC_ALL would override LANG.
printf '\377\376\200 zzfaketerm\n' > u.txt; git add u.txt
LC_ALL=en_US.UTF-8 staged_check && s=0 || s=$?; expect "staged, the term on a line that isn't valid UTF-8" 1 $s
{ head -c 72000 /dev/zero | LC_ALL=C tr '\000' '\200'; printf ' zzfaketerm\n\000tail\n'; } > late.bin; git add late.bin
LC_ALL=en_US.UTF-8 staged_check && s=0 || s=$?; expect "staged, the term in a binary whose first NUL comes late" 1 $s
# After a match on an invalid-UTF-8 line, the run goes on: a later file is still reported,
# and the summary prints.
printf '\377 zzfaketerm\n' > u1.txt; echo zzfaketerm > v2.txt; git add u1.txt v2.txt
out=$(LC_ALL=en_US.UTF-8 scripts/check-private-terms.sh --staged 2>&1) && s=0 || s=$?
git reset -q --hard; git clean -q -fd -e scripts
{ [ $s = 1 ] && grep -q '^v2.txt' <<<"$out" && grep -q 'the lines above match' <<<"$out"; } && s=0 || s=1
expect "staged, an invalid-UTF-8 match doesn't stop the run" 0 $s
# A Latin-1 byte in the list must not drop the terms after it.
printf 'zzother\ncaf\351\nzzfaketerm\n' > "$list"
echo zzfaketerm > w.txt; git add w.txt
LC_ALL=en_US.UTF-8 staged_check && s=0 || s=$?; expect "staged, a term after a Latin-1 line in the list" 1 $s
echo 'zzfaketerm' > "$list"
# Nit 6: binary files.
printf 'zzfaketerm\0bin' > bin.dat; git add bin.dat; staged_check && s=0 || s=$?; expect "staged, the term in a binary file" 1 $s
# Finding 3: CRLF lists and trailing blanks.
echo zzfaketerm > p.txt
printf 'zzfaketerm\r\n' > "$list"; git add p.txt; staged_check && s=0 || s=$?; expect "staged, CRLF list" 1 $s
printf 'zzfaketerm  \n' > "$list"; echo zzfaketerm > p.txt; git add p.txt; staged_check && s=0 || s=$?; expect "staged, a term with trailing blanks" 1 $s
# Finding 2: an invalid regex in the list refuses rather than reading as clean.
printf 'zzfaketerm\nfoo(\n' > "$list"
echo zzfaketerm > p.txt; git add p.txt; staged_check && s=0 || s=$?; expect "staged, a list with an invalid regex" 1 $s
push_check refs/heads/dirtyfile && s=0 || s=$?; expect "push, a list with an invalid regex" 1 $s
echo 'zzfaketerm' > "$list"

# The tracked hooks, through a full core.hooksPath, on real commits and pushes.
git config core.hooksPath "$PWD/scripts/hooks"
git checkout -q -b hooks clean
echo zzfaketerm > i.txt; git add i.txt
git commit -q -m "add i" >/dev/null 2>&1 && s=0 || s=$?; expect "hook: commit with the term in a file" 1 $s
git reset -q --hard
echo ok > j.txt; git add j.txt
git commit -q -m "add j" >/dev/null 2>&1 && s=0 || s=$?; expect "hook: clean commit" 0 $s
git push -q origin hooks >/dev/null 2>&1 && s=0 || s=$?; expect "hook: clean push" 0 $s
git push -q "$tmp/empty2.git" hooks >/dev/null 2>&1 && s=0 || s=$?; expect "hook: push of matching history to an empty repo by URL" 1 $s
# Nit 7: a worktree on a branch without scripts/ is still checked.
git -c core.hooksPath=/dev/null worktree add -q ../bare-wt main 2>/dev/null
(cd ../bare-wt && git rm -q -r --cached scripts 2>/dev/null; rm -rf scripts; echo zzfaketerm > q.txt; git add -A
 git commit -q -m "add q" >/dev/null 2>&1) && s=0 || s=$?; expect "hook: commit with the term in a worktree without scripts/" 1 $s
(cd ../bare-wt && git reset -q q.txt; rm q.txt; echo ok > r.txt; git add r.txt
 git commit -q -m "add r" >/dev/null 2>&1) && s=0 || s=$?; expect "hook: clean commit in a worktree without scripts/" 0 $s
refused() {  # command... -> 0 if it fails and stderr names the missing terms
  local err; err=$("$@" 2>&1 >/dev/null) && return 1; grep -q "no terms in .*private-terms" <<<"$err"
}
mv "$list" "$list.off"
echo ok > k.txt; git add k.txt
refused git commit -q -m "add k" && s=1 || s=0; expect "hook: commit with no list" 1 $s
git -c core.hooksPath=/dev/null commit -q -m "add k"
refused git push -q origin hooks && s=1 || s=0; expect "hook: push with no list" 1 $s
printf '# only a comment\n\n' > "$list"
echo ok > l.txt; git add l.txt
refused git commit -q -m "add l" && s=1 || s=0; expect "hook: commit with a comment-only list" 1 $s
rm "$list"
scripts/check-private-terms.sh >/dev/null 2>&1 && s=0 || s=$?; expect "working-tree check with no list" 0 $s
mv "$list.off" "$list"
exit $fail
