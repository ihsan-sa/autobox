# cc-unfiled's selfcheck: the cases behind `cc-unfiled selfcheck` (check.sh and selftest.sh run it that way; there is no
# other entry point). Not a module: cc-unfiled execs this file INSIDE ITS OWN NAMESPACE and calls the selfcheck() it
# defines, so every name here is the tool's, a `global` rebinds the tool's, and `__file__` is the tool. No
# module docstring (it would replace the tool's __doc__) and no top-level name but the defs below.

def selfcheck():
    n = [0, 0]

    def ok(name, cond):
        n[0 if cond else 1] += 1
        print(("  ok   " if cond else "  FAIL ") + name)

    def mkpdf(d, name, body, opts=""):
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, name + ".tex"), "w") as f:
            f.write("\\documentclass{article}" + opts + "\\pagestyle{empty}\\begin{document}" + body
                    + "\\end{document}\n")
        subprocess.run(["pdflatex", "-interaction=batchmode", name + ".tex"], cwd=d, capture_output=True)
        return os.path.join(d, name + ".pdf")

    def docs(root, *args):
        return subprocess.run([os.path.join(BIN, "cc-docs"), *args], capture_output=True, text=True,
                              env={**os.environ, "CC_DOCS_ROOT": root, "HOME": root})

    print("cc-unfiled selfcheck")
    with tempfile.TemporaryDirectory(prefix="cc-unfiled-sc-") as t:
        # each case builds its own tree and register, so none leans on what an earlier one left behind
        dev, reg = os.path.join(t, "c1", "dev"), os.path.join(t, "c1", "docs")
        filed = mkpdf(os.path.join(dev, "proj", "out"), "report", "Filed report\\newpage page two")
        loose = mkpdf(os.path.join(dev, "kid1", "notes"), "notes", "Unfiled notes\\newpage page two")
        r = docs(reg, "file", filed, "--project", "proj", "--kind", "work", "--title", "Report",
                 "--source", filed[:-4] + ".tex")
        ok("fixture: cc-docs filed the one document", r.returncode == 0)
        found = [p for p, *_ in unfiled([dev], 24, reg)]
        ok("an unfiled finished PDF is named", loose in found)
        ok("a filed one is skipped", filed not in found)

        # an unchanged rebuild (new bytes, new mtime) is still filed; a changed one is not
        dev, reg = os.path.join(t, "c2", "dev"), os.path.join(t, "c2", "docs")
        a = mkpdf(os.path.join(dev, "p"), "guide", "Guide one\\newpage two")
        docs(reg, "file", a, "--project", "p", "--kind", "work", "--title", "Guide", "--source", a[:-4] + ".tex")
        time.sleep(1.1)
        mkpdf(os.path.join(dev, "p"), "guide", "Guide one\\newpage two")
        ok("an unchanged rebuild of a filed PDF is skipped", a not in [p for p, *_ in unfiled([dev], 24, reg)])
        mkpdf(os.path.join(dev, "p"), "guide", "Guide one, revised\\newpage two")
        ok("a changed rebuild that was not filed again is named", a in [p for p, *_ in unfiled([dev], 24, reg)])

        # the heuristics: figures, drafts, test output and inputs are skipped; an old PDF is outside the window
        dev, reg = os.path.join(t, "c3", "dev"), os.path.join(t, "c3", "docs")
        kept = mkpdf(os.path.join(dev, "w"), "handout", "One-page handout")
        fig = mkpdf(os.path.join(dev, "w"), "chart", "x", "\\usepackage[paperwidth=4in,paperheight=3in]{geometry}")
        skips = [mkpdf(os.path.join(dev, "w", "figures"), "a", "In a figures dir\\newpage two"),
                 mkpdf(os.path.join(dev, "w"), "draft-2", "A draft\\newpage two"),
                 mkpdf(os.path.join(dev, "w", "tests"), "out", "Test output\\newpage two"),
                 mkpdf(os.path.join(dev, "w", "references"), "paper", "Somebody else's\\newpage two")]
        skips.append(mkpdf(os.path.join(dev, "w"), "vendor-part", "\\pdfinfo{/Producer (Acrobat Distiller 9.5)}"
                           "A vendor's part\\newpage two"))
        words = [mkpdf(os.path.join(dev, "w"), n, "A finished one\\newpage two")
                 for n in ("latest-report", "configuration-guide")]
        skips.append(mkpdf(os.path.join(dev, "w"), "fig3", "A numbered figure\\newpage two"))
        old = mkpdf(os.path.join(dev, "w"), "old", "Last week\\newpage two")
        os.utime(old, (time.time() - 3 * 86400,) * 2)
        found = [p for p, *_ in unfiled([dev], 24, reg)]
        ok("a one-page PDF on paper size is named", kept in found)
        ok("a one-page PDF off paper size (a figure) is skipped", fig not in found)
        ok("figures/, a draft name, tests/, references/ and a PDF Acrobat made are skipped", not set(skips) & set(found))
        ok("a PDF older than the window is skipped", old not in found)
        ok("a skip word only counts whole: latest-report and configuration-guide are named", set(words) <= set(found))
        ok("…while draft-2 and fig3 are still skipped", not {skips[1], skips[-1]} & set(found))

        # a PDF left in the Slack files dir: one sent out is named, one Slack delivered in is skipped
        files, reg = os.path.join(t, "c7", "files"), os.path.join(t, "c7", "docs")
        sent = mkpdf(files, "guide", "A guide sent out\\newpage two")
        got = mkpdf(files, "20260909T062610Z-F0C0BKNN9S7-syllabus", "A syllabus sent in\\newpage two")
        found = [p for p, *_ in unfiled([files], 24, reg)]
        ok("a PDF sent to Slack is named", sent in found)
        ok("a PDF Slack delivered is skipped", got not in found)

        # a committed PDF checked out afresh is not a build; the same PDF rebuilt and changed in that checkout is
        repo = os.path.join(t, "c5", "dev", "repo")
        made = mkpdf(os.path.join(t, "c5", "src"), "manual", "Committed manual\\newpage two")
        os.makedirs(repo)
        shutil.copy(made, os.path.join(repo, "manual.pdf"))
        g = ["git", "-C", repo, "-c", "user.name=t", "-c", "user.email=t@t"]
        subprocess.run(g[:3] + ["init", "-q"], capture_output=True)
        subprocess.run(g + ["add", "-A"], capture_output=True)
        subprocess.run(g + ["commit", "-q", "-m", "m", "--date=2020-01-01T00:00:00"],
                       capture_output=True, env={**os.environ, "GIT_COMMITTER_DATE": "2020-01-01T00:00:00"})
        found = [p for p, *_ in unfiled([os.path.dirname(repo)], 24, reg)]
        ok("a PDF git holds unchanged from an old commit is skipped", os.path.join(repo, "manual.pdf") not in found)
        shutil.copy(mkpdf(os.path.join(t, "c5", "src"), "manual", "Manual, rebuilt\\newpage two"),
                    os.path.join(repo, "manual.pdf"))
        found = [p for p, *_ in unfiled([os.path.dirname(repo)], 24, reg)]
        ok("…and named once rebuilt and changed", os.path.join(repo, "manual.pdf") in found)
        dup = os.path.join(t, "c5", "dev", "copy", "manual.pdf")
        os.makedirs(os.path.dirname(dup))
        shutil.copy(os.path.join(repo, "manual.pdf"), dup)
        found = [p for p, *_ in unfiled([os.path.join(t, "c5", "dev")], 24, reg)]
        ok("the same bytes at two paths are listed once", len(found) == 1)

        # git runs only in a tree holding a PDF in the window: most worktrees hold none, and each cost three git
        # calls anyway in the scan killed at its timeout on 10-27
        trees = {}
        for name, age in (("quiet", 3 * 86400), ("busy", 0)):
            trees[name] = os.path.join(t, "c9", "dev", name)
            os.makedirs(trees[name])
            subprocess.run(["git", "-C", trees[name], "init", "-q"], capture_output=True)
            with open(os.path.join(trees[name], "book.pdf"), "wb") as f:
                f.write(b"%PDF-1.4 not a real one")
            os.utime(os.path.join(trees[name], "book.pdf"), (time.time() - age,) * 2)
        global checked_out
        real, asked = checked_out, []
        checked_out = lambda d, since: asked.append(d) or real(d, since)
        try:
            unfiled([os.path.join(t, "c9", "dev")], 24, os.path.join(t, "c9", "docs"))
        finally:
            checked_out = real
        ok("a git tree with no PDF in the window costs no git call", trees["quiet"] not in asked)
        ok("…while one holding a PDF in the window is still asked", trees["busy"] in asked)

        # the register's recorded hash is trusted, so a run never re-reads the whole library; an old revision with
        # no recorded hash still has its filed copy read
        reg = os.path.join(t, "c8", "docs")
        os.makedirs(os.path.join(reg, "files"))
        for name in ("new.pdf", "old.pdf"):
            with open(os.path.join(reg, "files", name), "wb") as f:
                f.write(name.encode())
        with open(os.path.join(reg, "register.json"), "w") as f:
            json.dump({"documents": {"1": {"revisions": [{"file": "files/new.pdf", "sha256": "recorded"}]},
                                     "2": {"revisions": [{"file": "files/old.pdf"}]}}}, f)
        global sha
        real, read = sha, []
        sha = lambda path: read.append(os.path.basename(path)) or real(path)
        try:
            shas = known(register(reg), reg)[0]
        finally:
            sha = real
        ok("a revision with a recorded hash is not read again", "new.pdf" not in read and "recorded" in shas)
        ok("…and one with none still has its filed copy read", read == ["old.pdf"])

        # --to appends one entry when there is something to say, and nothing when there is not
        dev, reg = os.path.join(t, "c6", "dev"), os.path.join(t, "c6", "docs")
        kept = mkpdf(os.path.join(dev, "w"), "summary", "A summary\\newpage two")
        j = os.path.join(t, "journal.md")
        with open(j, "w") as f:
            f.write("# journal\n")
        rc = main(["--root", dev, "--to", j], docs_root=reg, quiet=True)
        body = open(j).read()
        ok("--to appends a dated entry naming the PDF", rc == 0 and "unfiled PDFs" in body and kept in body)
        empty = os.path.join(t, "c4", "dev")
        os.makedirs(empty)
        main(["--root", empty, "--to", j], docs_root=reg, quiet=True)
        ok("…and appends nothing when nothing is unfiled", open(j).read() == body)
    print(f"cc-unfiled selfcheck: {n[0]} passed, {n[1]} failed")
    return 1 if n[1] else 0
