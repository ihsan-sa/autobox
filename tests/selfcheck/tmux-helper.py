# tmux-helper's selfcheck: the cases behind `tmux-helper selfcheck` (check.sh and selftest.sh run it that way; there is no
# other entry point). Not a module: tmux-helper execs this file INSIDE ITS OWN NAMESPACE and calls the selfcheck() it
# defines, so every name here is the tool's, a `global` rebinds the tool's, and `__file__` is the tool. No
# module docstring (it would replace the tool's __doc__) and no top-level name but the defs below.

def selfcheck():
    n = f = 0

    def t(name, ok):
        nonlocal n, f
        n += 1
        if not ok:
            f += 1
            print("FAIL", name)

    d = tempfile.mkdtemp(prefix="tmux-helper-sc-")
    bindir = os.path.join(d, "bin")
    os.makedirs(bindir)
    log = os.path.join(d, "tmux.log")
    ans = os.path.join(d, "answer")
    prm = os.path.join(d, "prompt")
    # fake tmux: window ids @1 and @2 appear under two sessions each (grouped), @3 once
    with open(os.path.join(bindir, "tmux"), "w") as fh:
        fh.write('#!/bin/sh\necho "$*" >> "%s"\n'
                 'if [ "$1" = list-windows ]; then\n'
                 "printf '@1\\talpha\\tshop\\tbash\\t/w/shop\\t1000\\t%d\\n@1\\tbeta\\tshop\\tbash\\t/w/shop\\t1000\\t%d\\n"
                 "@2\\talpha\\tshop\\tbash\\t/w/shop2\\t900\\t%d\\n@2\\tbeta\\tshop\\tbash\\t/w/shop2\\t900\\t%d\\n"
                 "@3\\tgamma\\tnotes\\tvim\\t/w/notes\\t800\\t%d\\n'\n"
                 "elif [ \"$1\" = new-session ]; then echo grp-new; fi\n" % (log, os.getpid(), os.getpid(), os.getpid(), os.getpid(), os.getpid()))
    with open(os.path.join(bindir, "claude"), "w") as fh:
        fh.write('#!/bin/sh\ncat > "%s"\ncat "%s"\n' % (prm, ans))
    for x in ("tmux", "claude"):
        os.chmod(os.path.join(bindir, x), 0o755)
    env = dict(os.environ, PATH=bindir + ":" + os.environ["PATH"])
    env.pop("TMUX", None)
    me = os.path.realpath(__file__)

    def go(answer, args, stdin="", tmux=False):
        open(ans, "w").write(answer)
        open(log, "w").close()
        e = dict(env, TMUX="x") if tmux else env
        r = subprocess.run([sys.executable, me] + args, input=stdin, capture_output=True, text=True, env=e)
        return r, open(log).read()

    r, lg = go('{"match":"one","id":"@3"}', ["-ai", "--dry-run", "the", "notes", "one"])
    t("dry-run prints pick", "@3" in r.stdout and "gamma:notes" in r.stdout)
    t("dry-run switches nothing", "select-window" not in lg and "attach" not in lg and "switch-client" not in lg)
    t("window listed once", open(prm).read().count("@1 |") == 1 and open(prm).read().count("@2 |") == 1)
    t("prompt has words and old rule", "Words: the notes one" in open(prm).read() and "OLDER" in open(prm).read())
    r, lg = go('noise {"match":"one","id":"@2"} noise', ["-ai", "shop", "old"], tmux=True)
    t("inside tmux switches", "switch-client -t alpha" in lg and "select-window -t alpha:@2" in lg and "attach" not in lg)
    t("old words reach the model", "Words: shop old" in open(prm).read())
    os.path.exists(prm) and os.remove(prm)
    r, lg = go('{"match":"none"}', ["ntoes", "window"])
    t("typo and extra word match locally, no model", "attach -t grp-new" in lg and not os.path.exists(prm))
    r, lg = go('{"match":"none"}', ["shop"])
    t("same name: newest opens", "select-window -t grp-new:@1" in lg and not os.path.exists(prm))
    r, lg = go('{"match":"none"}', ["shop", "old"])
    t("same name + old: the older one", "select-window -t grp-new:@2" in lg)
    r, lg = go('{"match":"none"}', ["qqqqzz"], "")
    t("nothing close asks, no model", "Which one" in r.stdout and not os.path.exists(prm))
    r, lg = go('{"match":"none"}', ["Notes"])
    t("exact name opens without the model", "attach -t grp-new" in lg and not os.path.exists(prm))
    r, lg = go('{"match":"one","id":"@3"}', ["-ai", "notes"])
    t("outside tmux attaches", "attach -t grp-new" in lg and "switch-client" not in lg)
    t("outside tmux: own grouped session", "new-session -d -P -F #{session_name} -t gamma" in lg
      and "set-option -t grp-new destroy-unattached on" in lg and "select-window -t grp-new:@3" in lg
      and "select-window -t gamma" not in lg and "attach -t gamma" not in lg)
    r, lg = go('{"match":"several","question":"Which shop?","candidates":["@1","@2"]}', ["-ai", "shop"], "2\n")
    t("several asks numbered", "Which shop?" in r.stdout and "1) @1" in r.stdout and "2) @2" in r.stdout)
    t("number opens the pick", "attach -t grp-new" in lg and "select-window -t grp-new:@2" in lg)
    r, lg = go('{"match":"none"}', ["-ai", "zzz"], "3\n")
    t("none falls back to recent windows", "1) @1" in r.stdout and "3) @3" in r.stdout and "attach -t grp-new" in lg)
    r, lg = go('{"match":"none"}', ["-ai", "zzz"], "")
    t("no answer opens nothing", r.returncode == 1 and "attach" not in lg)
    r, lg = go('{"match":"none"}', ["-ai", "zzz"], "the vim one\n")
    t("free text asks once more, then stops", "Words: zzz the vim one" in open(prm).read() and r.returncode == 1)
    r, lg = go("not json", ["-ai", "x"])
    t("unreadable answer fails", r.returncode != 0 and "could not read" in r.stderr)
    r, lg = go("{}", [])
    t("no words opens the tree (attach outside tmux)", "attach ; choose-tree -Zw" in lg)
    r, lg = go("{}", [], tmux=True)
    t("no words inside tmux: tree only", lg.strip() == "choose-tree -Zw")
    print("tmux-helper selfcheck: %d passed, %d failed" % (n - f, f))
    return 1 if f else 0
