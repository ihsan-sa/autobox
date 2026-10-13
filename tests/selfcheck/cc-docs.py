# cc-docs's selfcheck: the cases behind `cc-docs selfcheck` (check.sh and selftest.sh run it that way; there is no
# other entry point). Not a module: cc-docs execs this file INSIDE ITS OWN NAMESPACE and calls the selfcheck() it
# defines, so every name here is the tool's, a `global` rebinds the tool's, and `__file__` is the tool. No
# module docstring (it would replace the tool's __doc__) and no top-level name but the defs below.

def selfcheck():
    """The cases, in a config of their own: no key of the box's ~/.cc/config (a live DOCS_SOURCE_CHECK or
    DOCS_CHECK_CHANNEL) reaches them, and each case sets the keys it tests in the environment, which wins."""
    keys = ("CC_CONFIG", "DOCS_SOURCE_CHECK", "DOCS_TEX_TREES", "DOCS_CHECK_CHANNEL", "DOCS_PUBLIC_HOOK", "CC_SLACK_BIN",
            "CC_DOCS_GH",
            "TEXINPUTS", "LIBRARY_URL", "LIBRARY_LINK_CLIENT_ID", "LIBRARY_LINK_CLIENT_SECRET",
            "LIBRARY_FEEDBACK_CLIENT_ID", "LIBRARY_FEEDBACK_CLIENT_SECRET")
    saved = {k: os.environ.pop(k, None) for k in keys}
    os.environ["CC_CONFIG"] = "/nonexistent/cc-docs-selfcheck-config"
    try:
        return _selfcheck()
    finally:
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


def _selfcheck():
    global ROOT, MEMBERS, HOME, IN_SANDBOX, SLACKSOCK, MEMBER_CAP, ATTACH_FILE_CAP, ATTACH_TOTAL_CAP, ATTACH_REV_CAP
    n = [0, 0]

    def ok(name, cond):
        n[0 if cond else 1] += 1
        print(("  ok   " if cond else "  FAIL ") + name)

    def mkpdf(d, name, body):
        """A one-page PDF saying `body`, built by pdflatex in d."""
        with open(os.path.join(d, name + ".tex"), "w") as f:
            f.write("\\documentclass{article}\\pagestyle{empty}\\begin{document}" + body + "\\end{document}\n")
        subprocess.run(["pdflatex", "-interaction=batchmode", name + ".tex"], cwd=d, capture_output=True)
        return os.path.join(d, name + ".pdf")

    def run(*args):
        out, err = sys.stdout, sys.stderr
        import io
        sys.stdout, sys.stderr = io.StringIO(), io.StringIO()
        try:
            rc = main(list(args))
        finally:
            o, e = sys.stdout.getvalue(), sys.stderr.getvalue()
            sys.stdout, sys.stderr = out, err
        return rc, o + e

    print("cc-docs selfcheck")
    ok("letters: A, H→J (I skipped), N→P (O skipped), Z, then AA", [letter(i) for i in (0, 8, 13, 23, 24, 25)]
       == ["A", "J", "P", "Z", "AA", "AB"])
    ok("slug: lowercase with hyphens", slugify("The Autobox: Explanation (v2)") == "the-autobox-explanation-v2")
    with tempfile.TemporaryDirectory(prefix="cc-docs-sc-") as t:
        src = os.path.join(t, "src")
        os.makedirs(src)
        MEMBERS = os.path.join(t, "members")
        wid = "0123456789abcdef"
        os.makedirs(os.path.join(MEMBERS, "kid1"))
        with open(os.path.join(MEMBERS, "kid1", "workspace-id"), "w") as f:
            f.write(wid + "\n")
        # numbering: each case files into a register of its own
        ROOT = os.path.join(t, "r1")
        a = mkpdf(src, "a", "Alpha one")
        b = mkpdf(src, "b", "Beta one\\newpage Beta two\\newpage Beta three")
        rc, o = run("file", a, "--project", "Box", "--title", "Alpha doc")
        ok("a new project with no kind is refused, nothing filed", rc == 2 and not os.path.exists(regpath()))
        run("file", a, "--project", "Box", "--kind", "work", "--title", "Alpha doc")
        rc, o = run("file", b, "--project", "Box", "--title", "Beta doc")
        run("file", b, "--project", "Course X", "--kind", "course", "--title", "Beta doc")
        run("file", a, "--project", "Kid", "--member", "kid1", "--title", "Alpha doc")
        reg = load()
        ok("the first work project is 001, its documents 001-0001 then 001-0002",
           sorted(n for n, d in reg["documents"].items() if d["project"] == "001") == ["001-0001", "001-0002"])
        ok("a course project starts at 101, a member project at 901",
           reg["projects"]["101"]["name"] == "Course X" and reg["projects"]["901"]["member"] == "kid1")
        ok("a member document is visible to that member and the owner, an owner document to the owner only",
           reg["documents"]["901-0001"]["visibility"] == ["owner", wid] and reg["documents"]["001-0001"]["visibility"] == ["owner"])
        v = os.path.join(ROOT, "ws", wid)
        with open(os.path.join(v, "register.json")) as fh:
            view = json.load(fh)
        vf = os.path.join(v, view["documents"]["901-0001"]["revisions"][0]["file"])
        ok("the member's view holds its own document and project and none of the owner's",
           list(view["documents"]) == ["901-0001"] and list(view["projects"]) == ["901"])
        ok("the view's file is the filed copy, linked and not copied",
           os.path.samefile(vf, os.path.join(ROOT, reg["documents"]["901-0001"]["revisions"][0]["file"])))
        owner_root, ROOT = ROOT, v
        rc, o = run("find", "alpha")
        rc2, o2 = run("find", "001-0001")
        ROOT = owner_root
        ok("find inside the view finds the member's document and not the owner's",
           rc == 0 and o.strip() == vf and rc2 == 1)
        ok("no view is made for the owner's documents alone", sorted(os.listdir(os.path.join(ROOT, "ws"))) == [wid])
        f = os.path.join(ROOT, reg["documents"]["001-0002"]["revisions"][0]["file"])
        ok("the filed copy is named PPP-NNNN-R_slug.pdf, read-only", os.path.basename(f) == "001-0002-A_beta-doc.pdf"
           and (os.geteuid() == 0 or not os.access(f, os.W_OK)))
        ok("an unstamped PDF gets the stamp overlaid on every page, and the original is left alone",
           "001-0002-A" not in pdftext(b) and pages(f) == 3 and pdftext(f).count("001-0002-A · ") == 3)
        # the stamp is appended, not re-rendered: links, outline and metadata survive, on both cross-reference kinds
        def marks(path):
            p = _PDF(open(path, "rb").read())
            links = sum(p.get(x).get("Subtype") == "Link" for _, pg, _ in p.pages() for x in p.get(pg.get("Annots")) or [])
            info = subprocess.run(["pdfinfo", path], capture_output=True, text=True).stdout
            return links, "Outlines" in p.get(p.trailer["Root"]), "".join(re.findall(r"^Title:\s*(.*)$", info, re.M))
        body = ("\\tableofcontents\\section{One}\\label{a}See \\ref{b}.\\newpage\\section{Two}\\label{b}See \\ref{a}"
                " and \\url{https://example.org}.")
        for name, pre in (("xs", ""), ("xt", "\\pdfobjcompresslevel=0 ")):
            with open(os.path.join(src, name + ".tex"), "w") as fh:
                fh.write(pre + "\\documentclass{article}\\usepackage[pdftitle={Hyper doc}]{hyperref}\\begin{document}"
                         + body + "\\end{document}\n")
            for _ in range(2):
                subprocess.run(["pdflatex", "-interaction=batchmode", name + ".tex"], cwd=src, capture_output=True)
            h, hs = os.path.join(src, name + ".pdf"), os.path.join(src, name + "-s.pdf")
            stamp(h, hs, "001-0009-A · 25 Sep 2026")
            with open(h, "rb") as f1, open(hs, "rb") as f2:
                kept = f2.read().startswith(f1.read())
            ok(f"a stamp keeps links, outline and title ({'classic table' if pre else 'xref stream'}), appended to "
               "the original bytes", marks(h)[0] > 0 and marks(hs) == marks(h) == (marks(h)[0], True, "Hyper doc")
               and kept and pdftext(hs).count("001-0009-A · 25 Sep 2026") == 2)
        real, err = overlay, sys.stderr
        import io
        sys.stderr = io.StringIO()

        def unreadable(*_):
            raise _Unreadable("encrypted")
        try:
            globals()["overlay"] = unreadable
            stamp(h, os.path.join(src, "fb.pdf"), "001-0009-B · 25 Sep 2026")
        finally:
            globals()["overlay"], said, sys.stderr = real, sys.stderr.getvalue(), err
        fb = os.path.join(src, "fb.pdf")
        ok("a PDF the appender cannot read is re-rendered instead, stamped, and says its links are lost",
           pdftext(fb).count("001-0009-B · 25 Sep 2026") == 2 and marks(fb)[0] == 0 and "links and outline are lost" in said)
        # stars, public links and what each viewer is sent: r1 as the cases above left it, rebuilt here on its own
        ROOT = os.path.join(t, "r1s")
        run("file", a, "--project", "Box", "--kind", "work", "--title", "Alpha doc")
        run("file", a, "--project", "Kid", "--member", "kid1", "--title", "Kid doc")
        run("star", "001-0001", "on")
        run("star", "901-0001", "on", "--viewer", wid)
        rc, o = run("star", "001-0001", "on", "--viewer", wid)
        reg = load()
        ok("stars are per viewer, and a member cannot star a document it cannot see",
           reg["documents"]["001-0001"]["starred_by"] == ["owner"] and reg["documents"]["901-0001"]["starred_by"] == [wid]
           and rc == 2)
        rc, o = run("library", "--viewer", wid)
        mine = json.loads(o)
        ok("a member's library holds its own documents and projects and nothing of the owner's",
           rc == 0 and [d["number"] for d in mine["documents"]] == ["901-0001"]
           and [p["number"] for p in mine["projects"]] == ["901"] and mine["viewer"]["role"] == "member"
           and mine["documents"][0]["starred"] is True)
        rc, o = run("library", "--viewer", "owner")
        own = json.loads(o)
        ok("the owner's library holds every document, with the owner's own stars only",
           [d["number"] for d in own["documents"]] == ["001-0001", "901-0001"]
           and [d["starred"] for d in own["documents"]] == [True, False] and own["viewer"]["role"] == "owner")
        rc, o = run("library", "--viewer", "fedcba9876543210")
        rc2, o2 = run("library", "--viewer", "someone")
        ok("an unknown workspace sees nothing, and a viewer that is not an id is refused",
           rc == 0 and json.loads(o)["documents"] == [] and json.loads(o)["projects"] == [] and rc2 == 2)
        rc, tok = run("public", "901-0001-A", "on")
        tok = tok.strip()
        rc2, again = run("public", "901-0001-A", "on")
        ok("public mints an unguessable token for the revision, and on again keeps it",
           rc == 0 and len(tok) >= 32 and again.strip() == tok)
        rc, o = run("token", tok, "901-0001-A")
        rc2, o2 = run("token", tok, "001-0001-A")
        rc3, o3 = run("token", tok[:-1] + ("A" if tok[-1] != "A" else "B"), "901-0001-A")
        ok("the token serves its own revision and no other, and a wrong token serves nothing",
           rc == 0 and o.strip().endswith("901-0001-A_kid-doc.pdf") and rc2 == 1 and rc3 == 1)
        mine = json.loads(run("library", "--viewer", wid)[1])
        own = json.loads(run("library", "--viewer", "owner")[1])
        with open(os.path.join(ROOT, "ws", wid, "register.json")) as fh:
            vtext = fh.read()
        ok("the owner is sent the token; the member and the member's view never are",
           own["documents"][1]["revisions"][0].get("token") == tok and tok not in json.dumps(mine) and tok not in vtext)
        run("public", "901-0001-A", "off")
        rc, o = run("token", tok, "901-0001-A")
        rc2, tok2 = run("public", "901-0001-A", "on")
        rc3, o3 = run("token", tok, "901-0001-A")
        ok("private deletes the token for good: the old one never serves again, and public again is a new one",
           rc == 1 and rc2 == 0 and tok2.strip() != tok and rc3 == 1 and run("token", tok2.strip(), "901-0001-A")[0] == 0)
        # DOCS_PUBLIC_HOOK: where the link is served hears on and off; off that can't reach it changes nothing
        hook, hlog = os.path.join(t, "hook.py"), os.path.join(t, "hook.log")
        with open(hook, "w") as fh:
            fh.write("import os, sys\nopen(sys.argv[1], 'a').write(' '.join(sys.argv[2:]) + '\\n')\n"
                     "if os.path.exists(sys.argv[1] + '.fail'): sys.exit('site unreachable')\n"
                     "print('https://lib.example/p/' + sys.argv[3])\n")
        os.environ["DOCS_PUBLIC_HOOK"] = f"{sys.executable} {hook} {hlog}"
        tok2 = tok2.strip()
        rc, o = run("public", "901-0001-A", "on")
        ok("with a hook, on hands it the token and prints the address it answers under the token",
           rc == 0 and o.splitlines() == [tok2, f"https://lib.example/p/{tok2}"]
           and open(hlog).read().splitlines() == [f"on {tok2} 901-0001-A"])
        open(hlog + ".fail", "w").close()
        rc, o = run("public", "901-0001-A", "off")
        ok("off whose hook fails refuses and keeps the token, so the link is never half revoked",
           rc == 2 and "still public" in o and run("token", tok2, "901-0001-A")[0] == 0)
        rc, o = run("public", "901-0001-A", "on")
        ok("on whose hook fails prints the token, exits 1 and keeps it for a retry",
           rc == 1 and o.splitlines()[0] == tok2 and "again retries" in o and run("token", tok2, "901-0001-A")[0] == 0)
        os.remove(hlog + ".fail")
        rc, o = run("public", "901-0001-A", "off")
        ok("off whose hook answers tells it the token first, then deletes it",
           rc == 0 and open(hlog).read().splitlines()[-1] == f"off {tok2} 901-0001-A"
           and run("token", tok2, "901-0001-A")[0] == 1)
        calls = len(open(hlog).read().splitlines())
        run("public", "901-0001-A", "off")
        ok("off on a revision with no token calls no hook", len(open(hlog).read().splitlines()) == calls)
        os.environ.pop("DOCS_PUBLIC_HOOK")
        # revisions: a register of its own
        ROOT = os.path.join(t, "r2")
        v1 = mkpdf(src, "v1", "Gamma first version")
        v2 = mkpdf(src, "v2", "Gamma second version")
        tex = os.path.join(src, "gamma.tex")
        open(tex, "w").write("\\documentclass{article}\n")   # a --source must exist now
        run("file", v1, "--project", "Box", "--kind", "work", "--title", "Gamma", "--source", tex)
        rc, o = run("file", v1, "--project", "Box", "--title", "Gamma", "--source", tex)
        d = load()["documents"]["001-0001"]
        ok("the same content again files nothing and names the current revision",
           rc == 0 and "unchanged" in o and "001-0001-A" in o and len(d["revisions"]) == 1)
        rc, o = run("file", v2, "--project", "Box", "--title", "Gamma renamed", "--source", tex)
        d = load()["documents"]["001-0001"]
        ok("changed content from the same source is the next letter of the same number",
           rc == 0 and "001-0001-B" in o and [r["rev"] for r in d["revisions"]] == ["A", "B"] and len(load()["documents"]) == 1)
        ok("revision A's file is kept and not rewritten", os.path.isfile(os.path.join(ROOT, d["revisions"][0]["file"]))
           and "Gamma first" in pdftext(os.path.join(ROOT, d["revisions"][0]["file"])))
        rc, o = run("file", v1, "--project", "Box", "--title", "Gamma renamed")
        ok("the same title with no source is the same document too (C, not a new number)",
           "001-0001-C" in o and len(load()["documents"]) == 1)
        # --source on an unchanged rebuild: a session attaches a .tex it found after the PDF was filed
        ROOT = os.path.join(t, "r2d")
        alone2 = os.path.join(t, "alone2")
        os.makedirs(alone2)
        shutil.copy(mkpdf(src, "z1", "Zeta first version"), os.path.join(alone2, "z1.pdf"))
        z1 = os.path.join(alone2, "z1.pdf")
        run("file", z1, "--project", "Box", "--kind", "work", "--title", "Zeta")
        d = load()["documents"]["001-0001"]
        ok("filed with nothing findable keeps no source and packs nothing",
           d.get("source") is None and "sources" not in d["revisions"][0])
        found = os.path.join(alone2, "found.tex")
        with open(found, "w") as f:
            f.write("\\documentclass{article}\\begin{document}Zeta\\end{document}\n")
        rc, o = run("file", z1, "--project", "Box", "--title", "Zeta", "--source", found)
        d = load()["documents"]["001-0001"]
        ok("--source on an unchanged rebuild records the found source and packs it, filing no new revision",
           rc == 0 and "unchanged" in o and len(d["revisions"]) == 1
           and d["source"] == os.path.abspath(found) and d["revisions"][0].get("source_files") == ["found.tex"])
        moved = found + ".moved"
        os.replace(found, moved)
        rc, o = run("file", z1, "--project", "Box", "--title", "Zeta", "--source", moved)
        d = load()["documents"]["001-0001"]
        ok("a recorded source whose path is gone is replaced on an unchanged rebuild too",
           rc == 0 and "unchanged" in o and len(d["revisions"]) == 1 and d["source"] == os.path.abspath(moved))
        # a --source or --latex that is not there (another branch checked out) refuses the filing outright
        ROOT = os.path.join(t, "r2e")
        absent = os.path.join(alone2, "absent", "resume.tex")
        rc, o = run("file", z1, "--project", "Box", "--kind", "work", "--title", "Zeta", "--source", absent)
        rc2, o2 = run("file", z1, "--project", "Box", "--kind", "work", "--title", "Zeta", "--latex", absent)
        ok("a --source or --latex path that does not exist is refused and nothing is filed",
           rc == 2 and rc2 == 2 and "--source " + absent in o and "--latex " + absent in o2
           and "filed" not in o.replace("nothing filed", "") and not os.path.exists(regpath()))
        rc, o = run("file", z1, "--project", "Box", "--kind", "work", "--title", "Zeta", "--source", moved)
        ok("the same filing with a --source that exists files and keeps it",
           rc == 0 and "\tfiled" in o and load()["documents"]["001-0001"]["revisions"][0].get("source_files"))
        # board revision, note and cost: a register of its own
        ROOT = os.path.join(t, "r2c")
        rc, o = run("file", v1, "--project", "Boards", "--kind", "work", "--title", "Board doc", "--describes", "PCB-1")
        rc2, o2 = run("file", v1, "--project", "Boards", "--kind", "work", "--title", "Board doc", "--cost", "draft=x")
        ok("a board revision not like PCB-0001-B, or a cost not step=usd, is refused and nothing filed",
           rc == 2 and rc2 == 2 and not os.path.exists(regpath()))
        rc, o = run("number", "--project", "Boards", "--kind", "work", "--title", "Board doc", "--describes", "PCB-0001-B", "--tex")
        ok("number --tex puts the board revision in the stamp", "\\docstamp{001-0001-A · PCB-0001-B · " in o)
        rc, o = run("file", v1, "--project", "Boards", "--kind", "work", "--title", "Board doc", "--describes", "PCB-0001-B",
                    "--note", "First cut", "--cost", "draft=0.80", "--cost", "review=0.43")
        r = load()["documents"]["001-0001"]["revisions"][0]
        ok("file records the board revision, note and cost on the revision, and stamps `number · board · date`",
           rc == 0 and r["describes"] == "PCB-0001-B" and r["note"] == "First cut"
           and r["cost"] == {"total": 1.23, "steps": [{"step": "draft", "usd": 0.8}, {"step": "review", "usd": 0.43}]}
           and "001-0001-A · PCB-0001-B · " in pdftext(os.path.join(ROOT, r["file"])))
        rc, o = run("file", v1, "--project", "Boards", "--title", "Board doc", "--describes", "PCB-0001-C")
        lib = json.loads(run("library", "--viewer", "owner")[1])["documents"][0]["revisions"]
        ok("an unchanged rebuild records nothing, and the library sends board revision, cost, pages and bytes",
           "unchanged" in o and len(lib) == 1 and lib[0]["describes"] == "PCB-0001-B" and lib[0]["cost"]["total"] == 1.23
           and lib[0]["pages"] == 1 and lib[0]["bytes"] > 0 and lib[0]["file"] == "/files/001-0001-A.pdf")
        rc, o = run("file", v2, "--project", "Boards", "--title", "Board doc")
        r = load()["documents"]["001-0001"]["revisions"][1]
        ok("a revision filed with no board revision or cost carries neither",
           rc == 0 and "describes" not in r and "cost" not in r and "note" not in r)
        ROOT = os.path.join(t, "r2")
        # figures: a register of its own; same words, a different drawing
        ROOT = os.path.join(t, "r2b")
        f1 = mkpdf(src, "f1", "Delta schematic\\par\\rule{2cm}{1cm}")
        f2 = mkpdf(src, "f2", "Delta schematic\\par\\rule{6cm}{3cm}")
        run("file", f1, "--project", "Box", "--kind", "work", "--title", "Delta")
        rc, o = run("file", f1, "--project", "Box", "--title", "Delta")
        ok("the same drawing again files nothing", rc == 0 and "unchanged" in o)
        rc, o = run("file", f2, "--project", "Box", "--title", "Delta")
        ok("the same text with a different drawing is the next letter",
           rc == 0 and "001-0001-B" in o and pdftext(f1) == pdftext(f2))
        reg = load()
        reg["documents"]["001-0001"]["revisions"][-1]["fingerprint"] = textprint(pdftext(f2))
        save(reg)
        rc, o = run("file", f2, "--project", "Box", "--title", "Delta")
        ok("a revision filed with the old text-only print is unchanged on an unchanged rebuild",
           rc == 0 and "unchanged" in o and len(load()["documents"]["001-0001"]["revisions"]) == 2)
        rc, o = run("file", mkpdf(src, "f3", "Delta schematic rev\\par\\rule{6cm}{3cm}"), "--project", "Box", "--title", "Delta")
        ok("changed text still bumps the letter past a text-only print", rc == 0 and "001-0001-C" in o)
        ROOT = os.path.join(t, "r2")
        # a build that took its number
        rc, o = run("number", "--project", "Box", "--title", "Gamma renamed", "--tex")
        ok("number --tex gives a changed build the next letter as TeX macros",
           rc == 0 and o.startswith("\\def\\docnumber{001-0001-D}") and "\\docstamp{001-0001-D · " in o)
        w = mkpdf(src, "w", "Gamma fourth 001-0001-D")
        rc, o = run("file", w, "--project", "Box", "--title", "Gamma renamed")
        d = load()["documents"]["001-0001"]
        ok("a PDF carrying its own number is filed as it is, not stamped twice",
           rc == 0 and d["revisions"][-1]["stamped"] == "carried" and pdftext(os.path.join(ROOT, d["revisions"][-1]["file"])).count("001-0001-D") == 1)
        x = mkpdf(src, "x", "Gamma fifth 001-0001-B")
        rc, o = run("file", x, "--project", "Box", "--title", "Gamma renamed")
        ok("a PDF carrying another number is refused", rc == 2 and "001-0001-B" in o and len(load()["documents"]["001-0001"]["revisions"]) == 4)
        rc, o = run("file", v2, "--project", "Box", "--title", "Resume", "--no-stamp")
        rc2, o2 = run("file", v1, "--project", "Box", "--title", "Resume")
        rv = load()["documents"]["001-0002"]["revisions"]
        ok("--no-stamp files the bytes as they are, and the document's later revisions stay unstamped",
           [r["stamped"] for r in rv] == ["none", "none"] and "001-0002" not in pdftext(os.path.join(ROOT, rv[1]["file"])))
        # find
        rc, o = run("find", "001-0001")
        ok("find by number prints the current revision's file", rc == 0 and o.strip().endswith("001-0001-D_gamma-renamed.pdf"))
        rc, o = run("find", "001-0001-A")
        ok("find by number and letter prints that revision", rc == 0 and o.strip().endswith("001-0001-A_gamma.pdf"))
        rc, o = run("find", "gamma")
        ok("find by a word of the title", rc == 0 and "001-0001-D" in o)
        rc, o = run("find", "zeta")
        ok("find with no match exits 1", rc == 1)
        rc, o = run("find", "box")
        ok("an ambiguous find lists the candidates and exits 3", rc == 3 and "001-0001-D" in o and "001-0002-B" in o)
        rc, o = run("find", "001-0009")
        ok("an unknown number is no match", rc == 1)
        # projects at the scheme's numbers
        ROOT = os.path.join(t, "r3")
        run("project", "Chip", "--number", "004")
        rc, o = run("project", "Other", "--number", "004")
        ok("project --number keeps a number for a named project and refuses to reuse it",
           load()["projects"]["004"]["kind"] == "work" and rc == 2)
        rc, o = run("project", "Tools", "--kind", "work")
        ok("the next work project takes the first free number", o.startswith("001\t"))
        rc, o = run("project", "Kid2", "--kind", "member")
        ok("a member project with no member is refused", rc == 2 and "Kid2" not in json.dumps(load()))
        rc, o = run("project", "Kid3", "--member", "nobody")
        ok("a member with no workspace id is refused", rc == 2 and "workspace id" in o and "Kid3" not in json.dumps(load()))
        # fold: three documents, the keeper's revision newest, the others older and out of order
        ROOT = os.path.join(t, "r4")
        e1, e2, e3 = (mkpdf(src, f"e{i}", f"Epsilon version {w}") for i, w in ((1, "one"), (2, "two"), (3, "three")))
        etex = os.path.join(src, "eps.tex")
        open(etex, "w").write("\\documentclass{article}\n")
        run("file", e3, "--project", "Box", "--kind", "work", "--title", "Eps", "--source", etex, "--date", "2026-09-20")
        run("file", e1, "--project", "Box", "--title", "Eps (v1)", "--date", "2026-09-10")
        run("file", e2, "--project", "Box", "--title", "Eps (v2)", "--date", "2026-09-15")
        tok = run("public", "001-0002-A", "on")[1].strip()
        before = json.dumps(load(), sort_keys=True)
        rc, o = run("fold", "001-0001", "001-0003", "001-0001")
        rc2, o2 = run("fold", "001-0003", "001-0001")
        ok("fold refuses a document named twice, and a keeper whose current revision is not the newest",
           rc == 2 and rc2 == 2 and "must stay the newest" in o2 and json.dumps(load(), sort_keys=True) == before)
        os.environ["DOCS_PUBLIC_HOOK"] = f"{sys.executable} {hook} {hlog}.fold"
        open(hlog + ".fold.fail", "w").close()
        rc, o = run("fold", "001-0001", "001-0003", "001-0002")
        ok("fold whose hook can't stop a dropped link refuses and folds nothing, so no letter serves another revision",
           rc == 2 and "nothing was folded" in o and json.dumps(load(), sort_keys=True) == before)
        os.remove(hlog + ".fold.fail")
        rc, o = run("fold", "001-0001", "001-0003", "001-0002")
        os.environ.pop("DOCS_PUBLIC_HOOK")
        reg = load()
        d = reg["documents"]["001-0001"]
        files = [os.path.join(ROOT, r["file"]) for r in d["revisions"]]
        ok("fold makes three documents A, B, C of the keeper, oldest first, the keeper's own revision last",
           rc == 0 and list(reg["documents"]) == ["001-0001"] and [r["rev"] for r in d["revisions"]] == ["A", "B", "C"]
           and [r.get("folded_from") for r in d["revisions"]] == ["001-0002-A", "001-0003-A", None]
           and d["title"] == "Eps" and d["source"] == etex)
        ok("the filed copies are renamed to match, and each still holds its own version",
           [os.path.basename(f) for f in files] == ["001-0001-A_eps.pdf", "001-0001-B_eps.pdf", "001-0001-C_eps.pdf"]
           and ["one" in pdftext(files[0]), "two" in pdftext(files[1]), "three" in pdftext(files[2])] == [True] * 3
           and sorted(os.listdir(os.path.join(ROOT, "files", "001"))) == ["001-0001-A_eps.pdf", "001-0001-B_eps.pdf",
                                                                           "001-0001-C_eps.pdf"])
        rc, o = run("file", e3, "--project", "Box", "--title", "Eps", "--source", etex)
        ok("a rebuild of the keeper's source still matches its current revision and files nothing",
           rc == 0 and "unchanged" in o and "001-0001-C" in o and len(load()["documents"]["001-0001"]["revisions"]) == 3)
        ok("a folded revision's public link stops working, under its old number and its new one",
           run("token", tok, "001-0002-A")[0] == 1 and run("token", tok, "001-0001-A")[0] == 1
           and tok not in json.dumps(load()))
        ok("fold tells the hook to stop the dropped token where it is served, and nothing else",
           open(hlog + ".fold").read().splitlines() == [f"off {tok} 001-0002-A"] * 2)
        ok("the folded numbers are retired, their entries kept under retired/",
           sorted(reg["retired"]) == ["001-0002", "001-0003"]
           and json.load(open(os.path.join(ROOT, "retired", "001-0002.json")))["entry"]["title"] == "Eps (v1)")
        rc, o = run("file", e1, "--project", "Box", "--title", "Zeta")
        ok("the next document takes a number past the retired ones", rc == 0 and o.startswith("001-0004-A"))
        # retire: a member's document with a public link, and one revision of another
        ROOT = os.path.join(t, "r5")
        run("file", e1, "--project", "Kid", "--member", "kid1", "--title", "Junk")
        run("file", e1, "--project", "Kid", "--title", "Keep")
        run("file", e2, "--project", "Kid", "--title", "Keep")
        run("file", e3, "--project", "Kid", "--title", "Keep")
        tok = run("public", "901-0001-A", "on")[1].strip()
        junk = os.path.join(ROOT, load()["documents"]["901-0001"]["revisions"][0]["file"])
        vjunk = os.path.join(ROOT, "ws", wid, os.path.relpath(junk, ROOT))
        ok("before the retire, the member's view links the document", os.path.exists(vjunk))
        os.environ["DOCS_PUBLIC_HOOK"] = f"{sys.executable} {hook} {hlog}.retire"
        rc, o = run("retire", "901-0001")
        os.environ.pop("DOCS_PUBLIC_HOOK")
        with open(os.path.join(ROOT, "ws", wid, "register.json")) as fh:
            view = json.load(fh)
        ok("retire takes the document out of the register and its member view, and its files move under retired/",
           rc == 0 and "901-0001" not in load()["documents"] and not os.path.exists(junk) and not os.path.exists(vjunk)
           and list(view["documents"]) == ["901-0002"]
           and os.path.isfile(os.path.join(ROOT, "retired", os.path.relpath(junk, ROOT)))
           and os.path.isfile(os.path.join(ROOT, "retired", "901-0001.json")))
        ok("a retired document's public link stops working, and the hook is told to stop serving it",
           run("token", tok, "901-0001-A")[0] == 1 and open(hlog + ".retire").read().splitlines() == [f"off {tok} 901-0001-A"])
        rc, o = run("file", e1, "--project", "Kid", "--title", "Junk")
        ok("a retired number is never handed out again: the same title files as a new number",
           rc == 0 and o.startswith("901-0003-A") and "901-0001" not in load()["documents"])
        rc, o = run("retire", "901-0002-C")
        rc2, o2 = run("file", e3, "--project", "Kid", "--title", "Keep")
        d = load()["documents"]["901-0002"]
        ok("retiring one revision keeps the document, and its letter is not filed again",
           rc == 0 and rc2 == 0 and [r["rev"] for r in d["revisions"]] == ["A", "B", "D"] and d["retired_revs"] == ["C"])
        rc, o = run("retire", "901-0001")
        rc2, o2 = run("fold", "901-0002", "901-0003")
        ok("retiring a retired number is refused, and so is folding a document with a retired revision",
           rc == 2 and rc2 == 2 and "901-0003" in load()["documents"])
        # groups and move: a Career project whose letters move into projects of their own under a Career group
        ROOT = os.path.join(t, "r7")
        g1, g2, g3, g4 = (mkpdf(src, f"g{i}", f"Gamma paper {w}") for i, w in enumerate(("one", "two", "three", "four"), 1))
        run("file", g1, "--project", "Career", "--kind", "work", "--title", "Resume, AI")
        run("file", g2, "--project", "Career", "--title", "Cover letter, Acme", "--source", os.path.join(src, "g2.tex"))
        run("file", g4, "--project", "Kid", "--member", "kid1", "--title", "Kid paper")
        tok = run("public", "001-0002-A", "on")[1].strip()
        run("star", "001-0002", "on")
        rc, o = run("file", g3, "--project", "Career/Cover letter", "--title", "Cover letter, Zeta")
        ok("a group cannot share its name with a project outside any group: nothing filed, no project made",
           rc == 2 and "--rename" in o and sorted(load()["projects"]) == ["001", "901"])
        rc, o = run("project", "001", "--rename", "Career/Resume")
        p1 = load()["projects"]["001"]
        ok("rename puts a project in a group and keeps its number", rc == 0 and (p1["group"], p1["name"]) == ("Career", "Resume"))
        rc, o = run("file", g3, "--project", "Career/Cover letter", "--title", "Cover letter, Zeta")
        rc2, o2 = run("file", g3, "--project", "Cover letter", "--title", "Cover letter, Zeta")
        p2 = load()["projects"].get("002", {})
        ok("filing under Group/Name makes a project of the group's kind, and its bare name finds it again",
           rc == 0 and o.startswith("002-0001-A") and (p2.get("group"), p2.get("name"), p2.get("kind"))
           == ("Career", "Cover letter", "work") and rc2 == 0 and "unchanged" in o2)
        rc, o = run("project", "Career")
        rc2, o2 = run("file", g3, "--project", "Career", "--title", "Loose")
        ok("a group lists its projects, and filing under the group's own name is refused",
           rc == 0 and o.splitlines() == ["001\tCareer/Resume\twork", "002\tCareer/Cover letter\twork"]
           and rc2 == 2 and "is a group" in o2 and "Loose" not in json.dumps(load()))
        old = load()["documents"]["001-0002"]["revisions"][0]["file"]
        open(hlog + ".move.fail", "w").close()
        os.environ["DOCS_PUBLIC_HOOK"] = f"{sys.executable} {hook} {hlog}.move"
        rc, o = run("move", "001-0002", "Career/Cover letter")
        os.environ.pop("DOCS_PUBLIC_HOOK")
        ok("a move whose hook can't stop the dropped link still moves, and says how to stop it by hand",
           rc == 0 and open(hlog + ".move").read().splitlines() == [f"off {tok} 001-0002-A"]
           and f"off {tok} 001-0002-A`" in o and "still answers" in o)
        reg = load()
        d = reg["documents"].get("002-0002", {})
        nf = os.path.join(ROOT, "files", "002", "002-0002-A_cover-letter-acme.pdf")
        ok("move renumbers a document into the project and renames its files",
           rc == 0 and o.split("\t")[:2] == ["001-0002-A", "002-0002-A"] and "001-0002" not in reg["documents"]
           and d.get("revisions", [{}])[0].get("file") == os.path.relpath(nf, ROOT)
           and os.path.isfile(nf) and not os.path.exists(os.path.join(ROOT, old)))
        ok("a moved document keeps a note of its old number, its stars and its source",
           d.get("moved_from") == ["001-0002"] and "owner" in starred_by(d) and d.get("source", "").endswith("g2.tex"))
        ok("the old number is retired with where it went, and its public link stops working",
           reg["retired"].get("001-0002", {}).get("moved_to") == "002-0002"
           and json.load(open(os.path.join(ROOT, "retired", "001-0002.json")))["entry"]["title"] == "Cover letter, Acme"
           and run("token", tok, "001-0002-A")[0] == 1 and run("token", tok, "002-0002-A")[0] == 1)
        rc, o = run("file", g2, "--project", "Career/Cover letter", "--title", "Cover letter, Acme",
                    "--source", os.path.join(src, "g2.tex"))
        rc2, o2 = run("file", g4, "--project", "Resume", "--title", "Resume, VLSI")
        ok("its rebuild finds it under its new number, and the old number is never handed out again",
           rc == 0 and o.startswith("002-0002-A") and "unchanged" in o and rc2 == 0 and o2.startswith("001-0003-A"))
        rc, o = run("move", "002-0001", "Career/Reference letter")
        rc2, o2 = run("move", "002-0002", "Cover letter")
        rc3, o3 = run("move", "001-0002", "Career/Resume")
        rc4, o4 = run("move", "901-0001", "Career/Resume")
        ok("move makes a missing project in the group; refuses the same project, a retired number and a member's document",
           rc == 0 and o.startswith("002-0001-A\t003-0001-A") and load()["projects"]["003"]["group"] == "Career"
           and rc2 == 2 and rc3 == 2 and rc4 == 2 and "901-0001" in load()["documents"])
        lib = library(load(), "owner")
        ok("the library carries a project's group, and no group key for a project outside any",
           {p["number"]: p.get("group", "none") for p in lib["projects"]} == {"001": "Career", "002": "Career", "003": "Career", "901": "none"})
        run("project", "Other/Resume", "--kind", "work")
        rc, o = run("list", "--project", "Resume")
        rc2, o2 = run("list", "--project", "Career")
        ok("a bare name two groups share is refused; a group lists its projects' documents",
           rc == 2 and "name its group" in o and rc2 == 0
           and [x.split("\t")[0] for x in o2.splitlines()] == ["001-0001-A", "001-0003-A", "002-0002-A", "003-0001-A"])
        # the library editor files a draft the site let an address write (--filer-editor): each case on a register of
        # its own, holding one work document and one member document (the latter --no-stamp when asked)
        def ed_fixture(name, nostamp=False):
            global ROOT
            ROOT = os.path.join(t, "r-ed-" + name)
            src = os.path.join(t, "ed-src-" + name)
            os.makedirs(src)
            run("file", mkpdf(src, "w", "Owner notes first"), "--project", "Owner stuff", "--kind", "work",
                "--title", "Owner notes")
            run("file", mkpdf(src, "k", "Kid one notes first"), "--project", "Kid1 docs", "--member", "kid1",
                "--title", "Kid notes", *(["--no-stamp"] if nostamp else []))
            dr = os.path.join(t, "ed-draft-" + name)
            os.makedirs(dr)
            return mkpdf(dr, "main", "Notes second, edited on the library"), os.path.join(dr, "main.tex")
        revs = lambda n: load()["documents"][n]["revisions"]
        dp, dt = ed_fixture("next")
        rc, o = run("file", dp, "--project", "Owner stuff", "--title", "Owner notes", "--latex", dt,
                    "--filer-editor", " Kid1@Example.COM ")
        ok("--filer-editor files the draft as the document's next revision, filer the address lower-cased, on any "
           "project the site allows", rc == 0 and o.startswith("001-0001-B\t") and [r["rev"] for r in revs("001-0001")] == ["A", "B"]
           and revs("001-0001")[-1].get("filer") == {"editor": "kid1@example.com"})
        lo = {x["rev"]: x.get("filed_by") for d in library(load(), "owner")["documents"] if d["number"] == "001-0001"
              for x in d["revisions"]}
        ok("the owner is told which address filed an editor's revision, and nothing for the box's own",
           lo == {"A": None, "B": "kid1@example.com"})
        dp, dt = ed_fixture("new")
        rc, o = run("file", dp, "--project", "Owner stuff", "--title", "Fresh notes", "--latex", dt,
                    "--filer-editor", "kid1@example.com")
        rc2, o2 = run("file", dp, "--project", "Brand new", "--kind", "work", "--title", "Fresh notes", "--latex", dt,
                      "--filer-editor", "kid1@example.com")
        ok("--filer-editor never files a new document, nor makes a project",
           rc == 2 and "existing document only" in o and rc2 == 2 and "existing document only" in o2
           and sorted(load()["documents"]) == ["001-0001", "901-0001"] and not find_project(load(), "Brand new"))
        dp, dt = ed_fixture("nolatex")
        rc, o = run("file", dp, "--project", "Owner stuff", "--title", "Owner notes", "--filer-editor", "kid1@example.com")
        ok("--filer-editor without --latex is refused, and files nothing",
           rc == 2 and "needs --latex" in o and len(revs("001-0001")) == 1)
        dp, dt = ed_fixture("bademail")
        rc, o = run("file", dp, "--project", "Owner stuff", "--title", "Owner notes", "--latex", dt,
                    "--filer-editor", "kid1")
        ok("--filer-editor with no email address is refused, and files nothing",
           rc == 2 and "not an email address" in o and len(revs("001-0001")) == 1)
        dp, dt = ed_fixture("title")
        rc, o = run("file", dp, "--project", "Owner stuff", "--title", "OWNER NOTES", "--latex", dt,
                    "--filer-editor", "kid1@example.com")
        ok("--filer-editor naming the document under another title is refused, and the title stays",
           rc == 2 and "keeps the document's title" in o and len(revs("001-0001")) == 1
           and load()["documents"]["001-0001"]["title"] == "Owner notes")
        dp, dt = ed_fixture("nostamp", nostamp=True)
        rc, o = run("file", dp, "--project", "Kid1 docs", "--title", "Kid notes", "--latex", dt,
                    "--filer-editor", "kid1@example.com")
        rv = revs("901-0001")
        ok("a document filed --no-stamp stays unstamped when the editor files its draft with --filer-editor",
           rc == 0 and [r["stamped"] for r in rv] == ["none", "none"]
           and "901-0001" not in pdftext(os.path.join(ROOT, rv[1]["file"])))
        dp, dt = ed_fixture("keep")
        before = json.loads(json.dumps(load()))
        rc, o = run("file", dp, "--project", "Kid1 docs", "--member", "kid2", "--kind", "work", "--title", "Kid notes",
                    "--latex", dt, "--filer-editor", "kid1@example.com")
        after = load()
        ok("--filer-editor leaves the document's project, title and visibility, and the project, as they were",
           rc == 0 and len(revs("901-0001")) == 2 and after["projects"] == before["projects"]
           and all(after["documents"]["901-0001"][k] == before["documents"]["901-0001"][k]
                   for k in ("project", "title", "visibility", "member", "stamp"))
           and after["documents"]["901-0001"]["visibility"] == ["owner", wid])
        dp, dt = ed_fixture("md")
        md = os.path.join(os.path.dirname(dt), "notes.md")
        with open(md, "w") as f:
            f.write("# Fresh\n\nA member's Markdown.\n")
        before = json.loads(json.dumps(load()))
        rc, o = run("file", md, "--project", "Owner stuff", "--title", "Fresh md", "--filer-editor", "kid1@example.com")
        rc2, o2 = run("file", md, "--project", "Owner stuff", "--title", "Owner notes", "--latex", dt,
                      "--filer-editor", "kid1@example.com")
        ok("--filer-editor on a Markdown file is refused outright, new document or old, and files nothing",
           rc == 2 and "never Markdown" in o and rc2 == 2 and "never Markdown" in o2 and load() == before)
        dp, dt = ed_fixture("fb")
        fbi = {"items": {"1": {"id": "1", "number": "001-0001", "rev": "A", "status": "delivered"},
                         "2": {"id": "2", "number": "001-0001-A", "status": "new"}}}
        with open(feedback_path(), "w") as f:
            json.dump(fbi, f)
        rc, o = run("file", dp, "--project", "Owner stuff", "--title", "Owner notes", "--latex", dt,
                    "--filer-editor", "kid1@example.com")
        ok("a revision --filer-editor files answers none of the owner's open feedback on the document",
           rc == 0 and o.startswith("001-0001-B\t") and "answers" not in o
           and json.load(open(feedback_path())) == fbi)
        # a member workspace files across its socket: each case on a register and a HOME of its own
        HOME, ROOT = os.path.join(t, "home"), os.path.join(t, "r6")
        for h, i in (("kid1", wid), ("kid2", "fedcba9876543210")):
            os.makedirs(os.path.join(HOME, "dev", h), exist_ok=True)
            os.makedirs(os.path.join(MEMBERS, h), exist_ok=True)
            with open(os.path.join(MEMBERS, h, "workspace-id"), "w") as f:
                f.write(i + "\n")
        ws = os.path.join(HOME, "dev", "kid1")
        m1 = mkpdf(ws, "m1", "Member physics one")

        def ask(h, **k):
            try:
                return member_ask(h, dict({"op": "file", "title": "Physics"}, **k)), ""
            except Refused as e:
                return None, str(e)
        run("project", "Owner work", "--kind", "work")
        run("project", "Kid2 stuff", "--member", "kid2")
        o, e = ask("kid1", pdf=m1, project="Owner work")
        reg = load()
        k1 = [p for p, d in reg["projects"].items() if d.get("member") == "kid1"]
        ok("a workspace with no project files under a new one of its own, not the owner project it named",
           o and o.endswith("filed") and len(k1) == 1 and reg["documents"][f"{k1[0]}-0001"]["visibility"] == ["owner", wid]
           and not [d for d in reg["documents"].values() if d["project"] != k1[0]])
        o, e = ask("kid1", pdf=m1, project="Kid2 stuff", title="Other")
        ok("another member's project is refused, and nothing is filed", o is None and "another member's" in e
           and len(load()["documents"]) == 1)
        o, e = ask("kid1", pdf=m1, member="kid2", title="Other")
        ok("--member naming another member is refused", o is None and "only for itself" in e and len(load()["documents"]) == 1)
        qm = os.path.join(MEMBERS, "kid1", "quarantined")   # QUARANTINE: the marker, set here and lifted below
        os.makedirs(os.path.dirname(qm), exist_ok=True)
        open(qm, "w").close()
        o, e = ask("kid1", pdf=m1, title="Quarantined")
        rc, o2 = run("file", m1, "--project", k1[0], "--title", "Quarantined owner filing")
        os.remove(qm)
        o3, e3 = ask("kid1", pdf=m1, title="Physics")
        ok("a quarantined workspace's own ask and an owner's filing into its project are refused and file nothing; "
           "deleting the marker lets it file again", o is None and "quarantined" in e and rc != 0 and "quarantined" in o2
           and len(load()["documents"]) == 1 and bool(o3))
        out = mkpdf(src, "out", "Outside the workspace")
        o, e = ask("kid1", pdf=out, title="Other")
        os.symlink(out, os.path.join(ws, "link.pdf"))
        o2, e2 = ask("kid1", pdf=os.path.join(ws, "link.pdf"), title="Other")
        os.symlink(src, os.path.join(ws, "dirlink"))
        o3, e3 = ask("kid1", pdf=os.path.join(ws, "dirlink", "out.pdf"), title="Other")
        ok("a PDF outside the workspace is refused, through a link to it or a linked directory too",
           o is None and o2 is None and o3 is None and all("not a file inside this workspace" in x for x in (e, e2, e3))
           and len(load()["documents"]) == 1)
        o, e = ask("kid1", pdf=m1, source=os.path.join(src, "a.tex"), title="Other")
        ok("a source outside the workspace is refused", o is None and "not a path inside" in e)
        # --no-source across the socket: a workspace's generated PDF (no .tex beside it) is marked gone at filing
        keep, ROOT = ROOT, os.path.join(t, "r6-nosrc")
        os.makedirs(os.path.join(ws, "gen"), exist_ok=True)
        shutil.copy(m1, os.path.join(ws, "gen", "stock.pdf"))
        o, e = ask("kid1", pdf=os.path.join(ws, "gen", "stock.pdf"), title="Stock", no_source="generated from live data")
        o2, e2 = ask("kid1", pdf=m1, title="Stock", no_source=7)
        rs = [r for d in load()["documents"].values() for r in d["revisions"]]
        ok("a workspace's no_source marks the revision it files gone, and one that is not a string is refused",
           bool(o) and len(rs) == 1 and rs[0].get("source_gone", {}).get("why") == "generated from live data"
           and o2 is None and "no_source must be a string" in e2)
        ROOT = keep
        with open(os.path.join(ws, "notes.pdf"), "w") as f:
            f.write("just text\n")
        o, e = ask("kid1", pdf=os.path.join(ws, "notes.pdf"), title="Other")
        ok("a file that is not a PDF is refused, whatever its name", o is None and "not a PDF" in e)
        cap, MEMBER_CAP = MEMBER_CAP, 100
        o, e = ask("kid1", pdf=m1, title="Other")
        MEMBER_CAP = cap
        ok("a PDF over the cap is refused", o is None and "at most" in e and len(load()["documents"]) == 1)
        o, e = ask("kid1", pdf=m1, title="Other", note="x" * (NOTE_CAP + 1))
        o2, e2 = ask("kid1", pdf=mkpdf(ws, "m1b", "Member physics one, again"), title="Physics", note="y" * NOTE_CAP)
        rv = load()["documents"][f"{k1[0]}-0001"]["revisions"]
        lo = [x for d in library(load(), "owner")["documents"] for x in d["revisions"] if x["rev"] == rv[-1]["rev"]
              and d["number"] == f"{k1[0]}-0001"]
        lm = [x for d in library(load(), wid)["documents"] for x in d["revisions"]]
        ok("a note over the cap is refused and files nothing; one at the cap files, and the owner is told who filed it",
           o is None and "at most 2000" in e and len(load()["documents"]) == 1 and o2 and len(rv) == 2
           and rv[-1].get("note") == "y" * NOTE_CAP and lo and lo[0].get("filed_by") == "kid1"
           and lm and not any("filed_by" in x for x in lm))
        o, e = ask("kid1", op="public")
        o2, e2 = ask("kid1", op="star")
        ok("public and star are not ops a workspace can ask for", o is None and o2 is None and "not 'public'" in e
           and "not 'star'" in e2)
        # the whole route: `cc-docs file` inside the sandbox, over a socket the fixture serves as the daemon does
        import socket
        import threading
        SLACKSOCK = os.path.join(t, "sock")
        srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        srv.bind(SLACKSOCK)
        srv.listen(4)

        def serve():
            while True:
                try:
                    c, _ = srv.accept()
                except OSError:
                    return
                with c:
                    f = c.makefile("rb")
                    q = json.loads(f.readline())["docs"]
                    try:
                        r = {"ok": True, "text": member_ask("kid1", q)}
                    except Refused as x:
                        r = {"ok": False, "error": str(x)}
                    c.sendall((json.dumps(r) + "\n").encode())
        threading.Thread(target=serve, daemon=True).start()
        m2 = mkpdf(ws, "m2", "Member physics two")
        IN_SANDBOX = True
        try:
            rc, o = run("file", "--title", "Physics two", m2)
            rcp, op_ = run("public", f"{k1[0]}-0001-A", "on")
            rct, ot = run("token", "x", f"{k1[0]}-0001-A")
            rcr, orr = run("retire", f"{k1[0]}-0001")
            rcf, of = run("fold", f"{k1[0]}-0001", f"{k1[0]}-0002")
            os.environ["LIBRARY_URL"] = "http://127.0.0.1:1"
            rcl, ol = run("link", f"{k1[0]}-0001", "--kind", "public")
        finally:
            os.environ.pop("LIBRARY_URL", None)
            IN_SANDBOX = False
            srv.close()
        reg = load()
        d2 = reg["documents"].get(f"{k1[0]}-0002") or {}
        with open(os.path.join(ROOT, "ws", wid, "register.json")) as fh:
            view = json.load(fh)
        ok("inside a workspace `cc-docs file --title T <pdf>` files under its project, next number, stamped, in its view",
           rc == 0 and o.startswith(f"{k1[0]}-0002-A\t") and d2.get("revisions", [{}])[0].get("stamped") == "overlay"
           and d2["revisions"][0]["from"] == m2 and f"{k1[0]}-0002" in view["documents"]
           and f"{k1[0]}-0002-A" in pdftext(os.path.join(ROOT, d2["revisions"][0]["file"])))
        ok("inside a workspace public and token are refused, and no revision gains a token",
           rcp == 2 and rct == 2 and "the host's" in op_ + ot
           and not any("public_token" in r for d in reg["documents"].values() for r in d["revisions"]))
        ok("inside a workspace retire and fold are refused, and both documents stay",
           rcr == 2 and rcf == 2 and "the host's" in orr + of
           and f"{k1[0]}-0001" in reg["documents"] and d2)
        ok("inside a workspace link is refused: a member mints no link on the box's token",
           rcl == 2 and "the host's" in ol and "http" not in ol)
        ok("no incoming copy is left behind", not [x for x in os.listdir(ROOT) if x.startswith(".incoming.")])
        # sources, filer and feedback: a register of their own, a scratch Slack dir, a fixed chain of cwds
        import tarfile
        ROOT = os.path.join(t, "r-src")
        sd = os.path.join(t, "slackdir")
        os.makedirs(sd)
        old_env, old_cwds = os.environ.get("CC_SLACK_DIR"), _cwds
        os.environ["CC_SLACK_DIR"] = sd
        try:
            lx = os.path.join(t, "lx")
            os.makedirs(os.path.join(lx, "fig"))
            for fn, body in (("sec.tex", "Section \\includegraphics{plot}"), ("local.sty", "\\RequirePackage{inner}"),
                             ("inner.sty", ""), ("refs.bib", "@misc{x}"), ("fig/plot.png", "png"),
                             ("secret.tex", "never"), ("unused.txt", "never")):
                with open(os.path.join(lx, fn), "w") as f:
                    f.write(body)
            with open(os.path.join(lx, "main.tex"), "w") as f:
                f.write("\\documentclass{article}\\usepackage{local,amsmath}\\graphicspath{{fig/}}\n"
                        "% \\input{secret}\n\\begin{document}\\input{sec}\\bibliography{refs}\\end{document}\n")
            lp = mkpdf(src, "lx1", "Latex source one")
            rc, o = run("file", lp, "--project", "Src", "--kind", "work", "--title", "Latex doc",
                        "--latex", os.path.join(lx, "main.tex"))
            r = load()["documents"]["001-0001"]["revisions"][-1]
            names = sorted(tarfile.open(os.path.join(ROOT, r.get("sources", "x"))).getnames()) if r.get("sources") else []
            ok("--latex keeps the .tex and what it includes (input, figure via graphicspath, local .sty and what it "
               "requires, .bib) and not a commented-out input, a stray file or TeX's own amsmath, with its manifest",
               rc == 0 and r.get("sources") == "sources/001/001-0001-A.tar.gz" and MANIFEST in names
               and [x for x in names if x != MANIFEST] == ["fig/plot.png", "inner.sty", "local.sty", "main.tex", "refs.bib", "sec.tex"]
               and r.get("source_files") == [x for x in names if x != MANIFEST])
            tb = open(os.path.join(ROOT, r["sources"]), "rb").read()
            os.remove(os.path.join(ROOT, r["sources"]))
            keep_sources(tex_sources(os.path.join(lx, "main.tex")), "001", "001-0001-A")
            ok("the same source packs to the same bytes", open(os.path.join(ROOT, r["sources"]), "rb").read() == tb)
            # a LaTeX build found by itself: a .tex of the PDF's own name beside it (the way mkpdf leaves one)
            sib = mkpdf(src, "sib", "Sibling tex one")
            run("file", sib, "--project", "Src", "--title", "Sibling doc")
            r = load()["documents"]["001-0002"]["revisions"][-1]
            ok("a .tex beside the PDF with its name is kept with no flag",
               r.get("source_files") == ["sib.tex"])
            # a plain --source, and a PDF with nothing findable
            alone = os.path.join(t, "alone")
            os.makedirs(alone)
            shutil.copy(mkpdf(src, "pl", "Plain source one"), os.path.join(alone, "pl.pdf"))
            shutil.copy(mkpdf(src, "no", "Nothing found one"), os.path.join(alone, "no.pdf"))
            notes = os.path.join(t, "notes.md")
            with open(notes, "w") as f:
                f.write("# notes\n")
            run("file", os.path.join(alone, "pl.pdf"), "--project", "Src", "--title", "Plain doc", "--source", notes)
            run("file", os.path.join(alone, "no.pdf"), "--project", "Src", "--title", "Bare doc")
            reg = load()
            ok("a --source that is not LaTeX is kept alone; a PDF with no source findable keeps none",
               reg["documents"]["001-0003"]["revisions"][-1].get("source_files") == ["notes.md"]
               and "sources" not in reg["documents"]["001-0004"]["revisions"][-1])
            # a member's .tex that reaches outside its trees: the outside file is never read
            mt = os.path.join(t, "mtree")
            os.makedirs(mt)
            with open(os.path.join(mt, "m.tex"), "w") as f:
                f.write("\\input{" + os.path.join(lx, "secret") + "}\\input{mine}")
            with open(os.path.join(mt, "mine.tex"), "w") as f:
                f.write("mine")
            os.symlink(os.path.join(lx, "unused.txt"), os.path.join(mt, "link.txt"))
            got = [n for _, n in tex_sources(os.path.join(mt, "m.tex"), [os.path.realpath(mt)])]
            ok("a member's source keeps only files inside its trees", sorted(got) == ["m.tex", "mine.tex"])
            kept, _ = pack([(os.path.join(mt, "link.txt"), "link.txt"), (os.path.join(mt, "mine.tex"), "mine.tex")],
                           os.path.join(t, "m.tar.gz"), [os.path.realpath(mt)])
            ok("packing for a member refuses a link, even one tex_sources did not see", kept == ["mine.tex"])
            # backfill (a register of its own): the current revision of a document with a findable --source gains
            # it; one with none is listed; one that already keeps its source is left alone
            ROOT = os.path.join(t, "r-bf")
            run("file", os.path.join(alone, "pl.pdf"), "--project", "Src", "--kind", "work", "--title", "Plain doc",
                "--source", notes)
            run("file", os.path.join(alone, "no.pdf"), "--project", "Src", "--title", "Bare doc")
            run("file", sib, "--project", "Src", "--title", "Sibling doc")
            reg = load()
            reg["documents"]["001-0001"]["revisions"][-1].pop("sources", None)
            save(reg)
            rc, o = run("backfill-sources")
            reg = load()
            ok("backfill keeps what a recorded --source finds, lists a document with none, skips one that has its own",
               rc == 0 and "001-0001-A\tkept\t1 file(s)" in o and "001-0002-A\tno source" in o
               and reg["documents"]["001-0001"]["revisions"][-1].get("sources_backfilled") is True
               and "001-0003" not in o and "sources_backfilled" not in reg["documents"]["001-0003"]["revisions"][-1])
            ROOT = os.path.join(t, "r-filer")
            # filer: a track worktree, its thread from track-threads.json
            wt = os.path.join(t, "wt", "sub")
            os.makedirs(os.path.join(t, "wt", ".cc"))
            os.makedirs(wt)
            with open(os.path.join(t, "wt", ".cc", "track"), "w") as f:
                f.write("repo1\ntrack1\nid\n")
            with open(os.path.join(sd, "track-threads.json"), "w") as f:
                json.dump({"repo1/track1": {"chat": "C1", "ts": "111.222"}}, f)
            with open(os.path.join(sd, "channels.json"), "w") as f:
                json.dump({"repo1": "CREPO"}, f)
            with open(os.path.join(sd, "orchs.json"), "w") as f:
                json.dump({"CORCH": {"target": "repo1", "alias": "lib"},
                           "COLD": {"target": "repo1", "alias": "gone", "archived": True}}, f)
            globals()["_cwds"] = lambda: [os.path.join(t, "scratch-build"), wt]
            rc, o = run("file", mkpdf(src, "f1", "Filer one"), "--project", "Src", "--kind", "work", "--title", "Filer doc")
            f1 = load()["documents"]["001-0001"]["revisions"][-1].get("filer")
            ok("a filing from a track worktree records repo, track, target and its thread",
               f1 == {"repo": "repo1", "session": "track1", "target": "repo1/track1", "channel": "C1", "thread": "111.222"})
            globals()["_cwds"] = lambda: [os.path.join(t, "nowhere")]
            os.environ["CC_SLACK_ALIAS"] = "lib"
            try:
                run("file", mkpdf(src, "f2", "Filer two"), "--project", "Src", "--title", "Filer two")
                os.environ["CC_SLACK_ALIAS"] = "gone"
                run("file", mkpdf(src, "f3", "Filer three"), "--project", "Src", "--title", "Filer three")
            finally:
                os.environ.pop("CC_SLACK_ALIAS", None)
            run("file", mkpdf(src, "f4", "Filer four"), "--project", "Src", "--title", "Filer four")
            reg = load()
            fs = [reg["documents"][dn]["revisions"][-1].get("filer") for dn in ("001-0002", "001-0003", "001-0004")]
            ok("an orch's alias records its live channel; an archived orch's is not used; nothing known records none",
               fs[0] == {"alias": "lib", "session": "lib", "channel": "CORCH", "repo": "repo1", "target": "repo1"}
               and fs[1] == {"alias": "gone", "session": "gone"} and fs[2] is None)
            # feedback (a register of its own): a new revision answers its document's open items, and only those
            ROOT = os.path.join(t, "r-fb")
            globals()["_cwds"] = lambda: [wt]
            run("file", mkpdf(src, "x1", "Feedback x"), "--project", "Src", "--kind", "work", "--title", "X doc")
            run("file", mkpdf(src, "y1", "Feedback y"), "--project", "Src", "--title", "Y doc")
            fb = {"items": {"1": {"id": "1", "number": "001-0001", "rev": "A", "status": "delivered"},
                            "2": {"id": "2", "number": "001-0002-A", "status": "delivered"},
                            "3": {"id": "3", "number": "001-0001", "rev": "A", "status": "done", "reply": "by hand",
                                  "synced": True},
                            "4": {"id": "4", "number": "001-0001", "rev": "A", "status": "posting"}}}
            with open(feedback_path(), "w") as f:
                json.dump(fb, f)
            rc0, o0 = run("file", mkpdf(src, "x1", "Feedback x"), "--project", "Src", "--title", "X doc")
            unchanged = json.load(open(feedback_path())) == fb
            rc, o = run("file", mkpdf(src, "x1", "Feedback x changed"), "--project", "Src", "--title", "X doc")
            items = json.load(open(feedback_path()))["items"]
            ok("an unchanged rebuild answers nothing; a new revision marks its document's delivered feedback done "
               "(answered by rev B, unsynced) and leaves another document's, an already-done and a not-yet-posted "
               "item alone", "unchanged" in o0 and unchanged and rc == 0 and "answers 1 feedback" in o
               and o.startswith("001-0001-B\t")
               and items["1"]["status"] == "done" and items["1"]["reply"] == "answered by rev B"
               and items["1"]["synced"] is False and items["2"] == fb["items"]["2"]
               and items["3"] == fb["items"]["3"] and items["4"] == fb["items"]["4"])
            # a move (a register of its own): the kept source moves with its revision; feedback on the old number
            # is answered by the next revision under the new one
            ROOT = os.path.join(t, "r-mv")
            ms = os.path.join(t, "mv.md")
            with open(ms, "w") as f:
                f.write("moved source")
            run("file", mkpdf(src, "m1", "Move one"), "--project", "Src", "--kind", "work", "--title", "M doc",
                "--source", ms)
            with open(feedback_path(), "w") as f:
                json.dump({"items": {"1": {"id": "1", "number": "001-0001", "rev": "A", "status": "delivered"}}}, f)
            rcm, om = run("move", "001-0001", "Other", "--kind", "work")
            mr = load()["documents"].get("002-0001", {}).get("revisions", [{}])[0]
            ok("move carries a revision's kept source to the new number, and the old path is gone",
               rcm == 0 and mr.get("sources") == "sources/002/002-0001-A.tar.gz"
               and os.path.isfile(os.path.join(ROOT, mr["sources"]))
               and not os.path.exists(os.path.join(ROOT, "sources", "001", "001-0001-A.tar.gz")))
            rc, o = run("file", mkpdf(src, "m1", "Move one changed"), "--project", "Other", "--title", "M doc")
            it = json.load(open(feedback_path()))["items"]["1"]
            ok("a new revision under the new number answers feedback left on the old one",
               rc == 0 and o.startswith("002-0001-B\t") and it["status"] == "done"
               and it["reply"] == "answered by rev B")
            # a member view (a register of its own) never carries the filer the owner's copy does
            ROOT = os.path.join(t, "r-view")
            run("file", mkpdf(src, "v1", "View one"), "--project", "Src", "--kind", "work", "--title", "V doc")
            reg = load()
            reg["documents"]["001-0001"]["visibility"].append(wid)
            save(reg)
            write_views(reg, {wid})
            with open(os.path.join(ROOT, "ws", wid, "register.json")) as fh:
                vr = json.load(fh)["documents"]["001-0001"]["revisions"]
            ok("a member view carries no filer, while the register has it",
               vr and not any("filer" in x for x in vr) and reg["documents"]["001-0001"]["revisions"][0].get("filer"))
            # related files (a register of its own): added and removed by number, an old number taken as the moved one,
            # and a member's view names only the related documents it can see
            ROOT = os.path.join(t, "r-rel")
            for i in (1, 2, 3):
                run("file", mkpdf(src, f"rl{i}", f"Rel {i}"), "--project", "Rel", "--kind", "work", "--title", f"R{i}")
            reg = load()
            for nm in ("001-0001", "001-0002"):
                reg["documents"][nm]["visibility"].append(wid)
            save(reg)
            run("move", "001-0003", "Rel2", "--kind", "work")
            rc, o = run("related", "001-0001", "001-0002", "001-0003")
            rel = load()["documents"]["001-0001"].get("related")
            with open(os.path.join(ROOT, "ws", wid, "register.json")) as fh:
                vrel = json.load(fh)["documents"]["001-0001"].get("related")
            ok("related adds by number, an old number as the one it moved to, and a member's view drops one it cannot see",
               rc == 0 and rel == ["001-0002", "002-0001"] and vrel == ["001-0002"]
               and "001-0001\t002-0001\tadded" in o and "001-0003 is 002-0001" in o)
            rcs, _ = run("related", "001-0001", "001-0001")
            rcu, _ = run("related", "001-0001", "009-0009")
            rcr, _ = run("related", "001-0001", "--remove", "001-0003", "--remove", "009-0009")
            ok("related refuses the document itself, an unknown number and a --remove it does not hold, nothing changed",
               rcs == rcu == rcr == 2 and load()["documents"]["001-0001"].get("related") == rel)
            rc, o = run("related", "001-0001", "--remove", "002-0001")
            rcl, ol = run("related", "001-0001")
            rc2, _ = run("related", "001-0001", "--remove", "001-0002")
            ok("related --remove takes one off and leaves the rest; the last one gone leaves no related field",
               rc == 0 and "002-0001\tremoved" in o and ol.strip() == "001-0001\t001-0002\tR2"
               and rc2 == 0 and "related" not in load()["documents"]["001-0001"])
            # a related document that moves after it was added: the list stored its old number
            run("related", "001-0001", "001-0002")
            run("move", "001-0002", "Rel2", "--kind", "work")
            stored = load()["documents"]["001-0001"].get("related")
            rcl, ol = run("related", "001-0001")
            ok("related lists an entry stored under a moved document's old number as its current one, and saves nothing",
               stored == ["001-0002"] and rcl == 0 and ol.strip() == "001-0001\t002-0002\tR2"
               and load()["documents"]["001-0001"].get("related") == ["001-0002"])
            rco, oo = run("related", "001-0001", "--remove", "001-0002")
            gone_old = "related" not in load()["documents"]["001-0001"]
            reg = load()
            reg["documents"]["001-0001"]["related"] = ["001-0002"]
            save(reg)
            rcn, on = run("related", "001-0001", "--remove", "002-0002")
            ok("related --remove takes off an entry stored under a moved document's old number, by either number",
               rco == 0 and "002-0002\tremoved" in oo and gone_old
               and rcn == 0 and "002-0002\tremoved" in on and "related" not in load()["documents"]["001-0001"])
            # a retired related document: --remove takes its stored number off, and a later add drops it when saving
            reg = load()
            reg["documents"]["001-0001"]["related"] = ["001-0002", "009-0009"]
            save(reg)
            rcg, og = run("related", "001-0001", "001-0003")
            ok("related drops a retired (gone) entry when saving an add",
               rcg == 0 and load()["documents"]["001-0001"].get("related") == ["002-0002", "002-0001"])
            reg = load()
            reg["documents"]["001-0001"]["related"] = ["009-0009"]
            save(reg)
            rcx, ox = run("related", "001-0001", "--remove", "009-0009")
            ok("related --remove takes off a stored number whose document is gone",
               rcx == 0 and "009-0009\tremoved" in ox and "related" not in load()["documents"]["001-0001"])
            # a member's view follows a moved related document: the stored old number shows as the current one
            reg = load()
            reg["documents"]["001-0001"]["related"] = ["001-0002"]
            save(reg)
            write_views(reg, {wid})
            with open(os.path.join(ROOT, "ws", wid, "register.json")) as fh:
                vm = json.load(fh)["documents"]["001-0001"].get("related")
            ok("a member view maps a related number through moved_from", vm == ["002-0002"])
            # the compile gate (a register of its own): a fake DOCS_SOURCE_CHECK honouring the JSON contract fails a
            # main holding BROKEN, a NEEDLUA one on any engine but lualatex, and exits 3 on CANTRUN
            ROOT = os.path.join(t, "r-gate")
            fake, flog = os.path.join(t, "fakecheck.py"), os.path.join(t, "fakecheck.log")
            with open(fake, "w") as f:
                f.write(
                    "import json, os, sys, tarfile\n"
                    "log, args, eng = sys.argv[1], sys.argv[2:], None\n"
                    "if args[0] == '--engine':\n    eng, args = args[1], args[2:]\n"
                    "t = tarfile.open(args[0])\n"
                    "man = json.load(t.extractfile('.source.json')) if '.source.json' in t.getnames() else {}\n"
                    "eng = eng or man.get('engine') or 'pdflatex'\n"
                    "main = man.get('main') or [n for n in t.getnames() if n.endswith('.tex')][0]\n"
                    "body = t.extractfile(main).read().decode()\n"
                    "open(log, 'a').write(eng + ' ' + main + '\\n')\n"
                    "if 'CANTRUN' in body:\n    sys.exit(3)\n"
                    "if 'SAYSNO' in body:\n    print(json.dumps({'ok': False, 'errors': [{'message': 'no main named'}]}))\n"
                    "    sys.exit(2)\n"
                    "errs, miss = [], []\n"
                    "if 'BROKEN' in body:\n    errs.append({'path': main, 'line': 3, 'message': 'Undefined control sequence.'})\n"
                    "if 'NEEDLUA' in body and eng != 'lualatex':\n    errs.append({'path': main, 'line': 1, 'message': 'needs LuaTeX'})\n"
                    "import re\n"
                    "for x in re.findall(r'NEED\\{([^}]*)\\}', body):\n"
                    "    if x not in t.getnames():\n"
                    "        errs.append({'path': main, 'line': 4, 'message': 'File `' + x + chr(39) + ' not found.'})\n"
                    "if 'MISSINGPKG' in body:\n    miss.append('fancypkg')\n"
                    "    errs.append({'path': main, 'line': 2, 'message': 'File fancypkg.sty not found.'})\n"
                    "print(json.dumps({'ok': not errs, 'engine': eng, 'main': main, 'errors': errs, 'missing': miss,"
                    " 'log_tail': ''}))\n"
                    "sys.exit(1 if errs else 0)\n")
            os.environ["DOCS_SOURCE_CHECK"] = f"{sys.executable} {fake} {flog}"

            def texdir(name, body, extra=()):
                dd = os.path.join(t, "gate", name)
                os.makedirs(dd, exist_ok=True)
                for fn, b in ((("main.tex", body),) + tuple(extra)):
                    os.makedirs(os.path.dirname(os.path.join(dd, fn)), exist_ok=True)
                    with open(os.path.join(dd, fn), "w") as fh:
                        fh.write(b)
                return os.path.join(dd, "main.tex")

            def tried():
                try:
                    lines = open(flog).read().split()
                finally:
                    open(flog, "w").close()
                return lines[0::2]

            def man(rel):
                with tarfile.open(os.path.join(ROOT, rel)) as tf:
                    return json.load(tf.extractfile(MANIFEST)), sorted(tf.getnames())
            open(flog, "w").close()
            g1 = texdir("good", "\\documentclass{article}\\begin{document}fine\\end{document}\n")
            rc, o = run("file", mkpdf(src, "gate1", "Gate one"), "--project", "Gate", "--kind", "work", "--title", "Good",
                        "--latex", g1)
            r = load()["documents"]["001-0001"]["revisions"][-1]
            m = man(r["sources"])[0] if r.get("sources") else {}
            ok("the gate keeps a source that compiles: .source.json names its main and engine, and the revision "
               "records source_main, source_engine and source_checked", rc == 0 and tried() == ["pdflatex"]
               and m == {"main": "main.tex", "engine": "pdflatex"} and r.get("source_main") == "main.tex"
               and r.get("source_engine") == "pdflatex" and re.match(r"\d{4}-\d\d-\d\dT", r.get("source_checked", ""))
               and r.get("source_files") == ["main.tex"])
            g2 = texdir("bad", "\\documentclass{article}\\begin{document}BROKEN\\end{document}\n")
            rc, o = run("file", mkpdf(src, "gate2", "Gate two"), "--project", "Gate", "--title", "Bad", "--latex", g2)
            r = load()["documents"]["001-0002"]["revisions"][-1]
            ok("a source that does not compile on either engine is not kept, stderr names its first error, and the "
               "PDF is still filed", rc == 0 and "sources" not in r and "source_main" not in r
               and not os.path.exists(os.path.join(ROOT, "sources", "001", "001-0002-A.tar.gz"))
               and "cc-docs: 001-0002-A: source not kept, it does not compile: main.tex:3: Undefined control sequence." in o
               and os.path.isfile(os.path.join(ROOT, r["file"])) and tried() == ["pdflatex", "lualatex"]
               and not [x for x in os.listdir(ROOT) if x.startswith(".source.")])
            g3 = texdir("lua", "\\documentclass{article}\\begin{document}NEEDLUA\\end{document}\n")
            rc, o = run("file", mkpdf(src, "gate3", "Gate three"), "--project", "Gate", "--title", "Lua", "--latex", g3)
            r = load()["documents"]["001-0003"]["revisions"][-1]
            ok("a source failing on pdflatex is tried once on lualatex and kept with that engine in its manifest",
               rc == 0 and tried() == ["pdflatex", "lualatex"] and r.get("source_engine") == "lualatex"
               and man(r["sources"])[0]["engine"] == "lualatex")
            g4 = texdir("pin", "% !TEX program = xelatex\n\\documentclass{article}\\begin{document}BROKEN\\end{document}\n")
            rc, o = run("file", mkpdf(src, "gate4", "Gate four"), "--project", "Gate", "--title", "Pinned", "--latex", g4)
            ok("an engine pinned by `% !TEX program` is the only one tried", rc == 0 and tried() == ["xelatex"]
               and "sources" not in load()["documents"]["001-0004"]["revisions"][-1])
            g5 = texdir("cant", "\\documentclass{article}\\begin{document}CANTRUN\\end{document}\n")
            rc, o = run("file", mkpdf(src, "gate5", "Gate five"), "--project", "Gate", "--title", "Cant", "--latex", g5)
            ok("a check that cannot run keeps nothing, says so, and is not retried",
               rc == 0 and tried() == ["pdflatex"] and "the compile check could not run: exit 3" in o
               and "sources" not in load()["documents"]["001-0005"]["revisions"][-1])
            # a figure named through a macro: kept when the picture is beside the .tex in a folder, and a source
            # whose figure is nowhere is still refused by the check
            fig = "\\documentclass{article}\\newcommand\\sysfig[1]{\\includegraphics{figures/#1}}\\begin{document}" \
                  "\\sysfig{00-overview} NEED{figures/00-overview.pdf}\\end{document}\n"
            gf = texdir("macrofig", fig, (("figures/00-overview.pdf", "%PDF-1.4\n"),
                                          ("figures/00-overview.json", "{}"), ("figures/unused.png", "png")))
            got = keep_sources(tex_sources(gf), "009", "009-0011-A")
            ok("a figure named through a macro (\\sysfig{00-overview} -> figures/00-overview.pdf) is packed and the "
               "source kept; its .json and an unused picture are not", tried() == ["pdflatex"]
               and got.get("source_files") == ["figures/00-overview.pdf", "main.tex"])
            gf2 = texdir("macrofig-missing", fig, (("figures/other.pdf", "%PDF-1.4\n"),))
            got = keep_sources(tex_sources(gf2), "009", "009-0012-A")
            ok("a macro's figure found nowhere is not packed, and the check refuses that source",
               got == {} and tried() == ["pdflatex", "lualatex"])
            # a file named from a directory above the .tex (a board's design doc built from the board's root):
            # packed under _cwd/ and _cwd put on texinputs; one missing everywhere is still refused
            brd = os.path.join(HOME, "dev", "board1")
            bt = "\\documentclass{article}\\usepackage{pdfpages}\\begin{document}x" \
                 "\\includepdf[pages=-]{reports/schematic.pdf} NEED{_cwd/reports/schematic.pdf}\\end{document}\n"
            for fn, b in (("reports/design_doc/main.tex", bt), ("reports/schematic.pdf", "%PDF-1.4\n")):
                os.makedirs(os.path.dirname(os.path.join(brd, fn)), exist_ok=True)
                with open(os.path.join(brd, fn), "w") as f:
                    f.write(b)
            got = keep_sources(tex_sources(os.path.join(brd, "reports/design_doc/main.tex")), "009", "009-0013-A")
            ok("a file found from a directory above the .tex is packed as _cwd/<its name> and _cwd goes on texinputs",
               tried() == ["pdflatex"] and got.get("source_files") == ["_cwd/reports/schematic.pdf", "main.tex"]
               and man(got["sources"])[0].get("texinputs") == ["_cwd"])
            os.unlink(os.path.join(brd, "reports/schematic.pdf"))
            got = keep_sources(tex_sources(os.path.join(brd, "reports/design_doc/main.tex")), "009", "009-0014-A")
            ok("a file found neither beside the .tex nor above it is not packed, and the check refuses that source",
               got == {} and tried() == ["pdflatex", "lualatex"])
            # fontspec's Path= folder is packed with its fonts; a Path= to no folder packs nothing and is refused
            ft = "\\documentclass{article}\\usepackage{fontspec}\\setmainfont{Body}[Path=fonts/, Extension=.otf]" \
                 "\\begin{document}NEED{fonts/Body-Regular.otf}\\end{document}\n"
            gft = texdir("pathfont", ft, (("fonts/Body-Regular.otf", "otf"), ("fonts/Body-Bold.otf", "otf"),
                                          ("fonts/LICENSE.md", "no")))
            got = keep_sources(tex_sources(gft), "009", "009-0017-A")
            ok("fontspec's Path=fonts/ packs every .otf there (not its licence) and the source is kept",
               tried() == ["lualatex"] and got.get("source_files") == ["fonts/Body-Bold.otf", "fonts/Body-Regular.otf",
                                                                       "main.tex"])
            got = keep_sources(tex_sources(texdir("pathfont-none", ft)), "009", "009-0018-A")
            ok("…and with no fonts/ folder nothing is packed for it and the check refuses the source",
               got == {} and tried() == ["lualatex", "pdflatex"])
            # a .tex reaching up (a résumé's \\input{../Inc/head.tex}) is kept with the tree it reaches, the main in
            # its folder; with the file gone it is not packed and the check refuses the source
            cv = os.path.join(HOME, "dev", "cv")
            ct = "\\documentclass{article}\\begin{document}\\input{../Inc/head.tex} NEED{Inc/head.tex}\\end{document}\n"
            for fn, b in (("asic/main.tex", ct), ("Inc/head.tex", "Head.\n")):
                os.makedirs(os.path.dirname(os.path.join(cv, fn)), exist_ok=True)
                with open(os.path.join(cv, fn), "w") as f:
                    f.write(b)
            got = keep_sources(tex_sources(os.path.join(cv, "asic/main.tex")), "009", "009-0015-A")
            ok("a .tex that inputs ../Inc/head.tex is kept rooted at their common folder: asic/main.tex is the main",
               tried() == ["pdflatex"] and got.get("source_files") == ["Inc/head.tex", "asic/main.tex"]
               and got.get("source_main") == "asic/main.tex" and man(got["sources"])[0]["main"] == "asic/main.tex")
            os.unlink(os.path.join(cv, "Inc/head.tex"))
            got = keep_sources(tex_sources(os.path.join(cv, "asic/main.tex")), "009", "009-0016-A")
            ok("…and with ../Inc/head.tex gone the main stays at the root and the check refuses the source",
               got == {} and tried() == ["pdflatex", "lualatex"])
            # a macro's picture reaching up (a board guide's \hsdiagram[page=5]{../schematic.pdf}) is kept the same way
            bd = os.path.join(HOME, "dev", "board", "reports")
            for fn, b in (("guide/g.tex", "\\documentclass{article}\\begin{document}\\hsdiagram[page=5]{../schematic.pdf}"
                                          "\\x{../gone.pdf}\\y{../notes.txt}\\end{document}\n"),
                          ("schematic.pdf", "%PDF-1.4\n"), ("notes.txt", "n\n")):
                os.makedirs(os.path.dirname(os.path.join(bd, fn)), exist_ok=True)
                with open(os.path.join(bd, fn), "w") as f:
                    f.write(b)
            fb = tex_sources(os.path.join(bd, "guide/g.tex"))
            ok("a macro's ../schematic.pdf is kept beside the guide's folder, the main in it; a missing picture and a "
               "file that is no picture are not", sorted(nm for _, nm in fb) == ["guide/g.tex", "schematic.pdf"]
               and fb.main == "guide/g.tex")
            g6 = texdir("fs", "\\documentclass{article}\\usepackage{mine}\\begin{document}x\\end{document}\n",
                        (("mine.sty", "\\RequirePackage{fontspec}\n"),))
            os.environ.pop("DOCS_SOURCE_CHECK")
            got = keep_sources(tex_sources(g6), "009", "009-0001-A")
            ok("fontspec loaded in a kept .sty makes the manifest lualatex; with no DOCS_SOURCE_CHECK it is kept "
               "unchecked", got.get("source_engine") == "lualatex" and "source_checked" not in got
               and man(got["sources"])[0]["engine"] == "lualatex" and tried() == [])
            # a package found by kpsewhich under ~ goes at the tarball's root; a style tree under _style/ with its fonts
            kp = os.path.join(HOME, "texmf", "house")
            os.makedirs(kp, exist_ok=True)
            with open(os.path.join(kp, "kphouse.sty"), "w") as f:
                f.write("% house\n")
            os.environ["TEXINPUTS"] = kp + "//:"
            try:
                g7 = texdir("kp", "\\documentclass{article}\\usepackage{kphouse}\\begin{document}x\\end{document}\n")
                names = [nm for _, nm in tex_sources(g7)]
            finally:
                os.environ.pop("TEXINPUTS", None)
            ok("a package kpsewhich finds under ~ is packed at the tarball's root, not under _ext/",
               shutil.which("kpsewhich") is None or names == ["main.tex", "kphouse.sty"])
            sr = os.path.join(t, "styleroot")
            for fn, b in (("tex/house/sub/housestyle.sty", "\\RequirePackage{fontspec}\\input{housebits}\n"),
                          ("tex/house/housebits.tex", "bits\n"), ("assets/fonts/Body.otf", "otf"),
                          ("assets/fonts/Mono.TTF", "ttf"), ("assets/readme.txt", "no"), ("other/x.sty", "no")):
                os.makedirs(os.path.dirname(os.path.join(sr, fn)), exist_ok=True)
                with open(os.path.join(sr, fn), "w") as f:
                    f.write(b)
            os.environ["DOCS_TEX_TREES"] = f"{sr}:tex/house"
            g8 = texdir("tree", "\\documentclass{article}\\usepackage{housestyle}\\begin{document}x\\end{document}\n")
            got = keep_sources(tex_sources(g8), "009", "009-0002-A")
            mm, tn = man(got["sources"]) if got.get("sources") else ({}, [])
            member_names = [nm for _, nm in tex_sources(g8, [os.path.realpath(os.path.dirname(g8))])]
            os.environ.pop("DOCS_TEX_TREES")
            ok("DOCS_TEX_TREES: a package under ROOT/SUB is packed at _style/<path under ROOT>, with what it inputs "
               "and every font under ROOT, _style/SUB goes in texinputs; a member's filing packs the same style",
               tn == [".source.json", "_style/assets/fonts/Body.otf", "_style/assets/fonts/Mono.TTF",
                      "_style/tex/house/housebits.tex", "_style/tex/house/sub/housestyle.sty", "main.tex"]
               and mm == {"main": "main.tex", "engine": "lualatex", "texinputs": ["_style/tex/house"]}
               and member_names == ["main.tex", "_style/tex/house/sub/housestyle.sty", "_style/tex/house/housebits.tex",
                                    "_style/assets/fonts/Body.otf", "_style/assets/fonts/Mono.TTF"])
            # check: every document's current revision listed, passes cached, failures re-run each time
            ROOT = os.path.join(t, "r-chk")
            open(flog, "w").close()
            run("file", os.path.join(alone, "no.pdf"), "--project", "Chk", "--kind", "work", "--title", "No source")
            run("file", os.path.join(alone, "pl.pdf"), "--project", "Chk", "--title", "Plain", "--source", notes)
            c3 = texdir("chkbad", "\\documentclass{article}\\begin{document}BROKEN MISSINGPKG\\end{document}\n")
            run("file", mkpdf(src, "chk3", "Check three"), "--project", "Chk", "--title", "Failing", "--latex", c3)
            run("file", mkpdf(src, "chk4", "Check four"), "--project", "Chk", "--title", "Fine", "--latex", g1)
            os.environ["DOCS_SOURCE_CHECK"] = f"{sys.executable} {fake} {flog}"
            rc, o = run("check")
            first = tried()
            rc2, o2 = run("check")
            ok("check lists no source and fails with its first error, the missing packages and the count",
               rc == 1 and o.splitlines() == [
                   "001-0001-A\tno source\tno --source recorded",
                   "001-0003-A\tfails\tmain.tex:3: Undefined control sequence.", "missing TeX packages: fancypkg",
                   "1 of 2 kept sources compile"] and len(first) == 2)
            ok("a kept source with no .tex (notes.md) is neither listed nor counted", "notes.md" not in o and "no .tex" not in o)
            ok("a cached pass is not compiled again, a failure is", rc2 == 1 and o2 == o and tried() == ["pdflatex"])
            with open(os.path.join(ROOT, ".check.lock"), "w") as held:
                fcntl.flock(held, fcntl.LOCK_EX)
                rc, o = run("check")
            ok("a second check while one runs says so and exits 0", rc == 0 and "another check" in o and tried() == [])
            # gone: a source looked for and not found is named by check, not failed on; a Markdown one is skipped
            ROOT = os.path.join(t, "r-gone")
            run("file", os.path.join(alone, "no.pdf"), "--project", "Gone", "--kind", "work", "--title", "Lost")
            gmd = os.path.join(t, "gone-notes.md")
            with open(gmd, "w") as fh:
                fh.write("# Notes\n")
            run("file", gmd, "--project", "Gone", "--title", "Notes")
            rc, o = run("check")
            rcg, og = run("gone", "001-0001-A", "--why", "built in a scratch dir  since deleted")
            rcm, om = run("gone", "001-0002-A", "--why", "x")
            rc2, o2 = run("check")
            ok("gone marks a sourceless revision, check names it and passes; one keeping its source is refused",
               rc == 1 and o.splitlines()[0] == "001-0001-A\tno source\tno --source recorded"
               and rcg == 0 and og.strip() == "001-0001-A\tgone\tbuilt in a scratch dir since deleted"
               and rcm == 2 and "keeps its source" in om
               and rc2 == 0 and o2.splitlines() == ["001-0001-A\tgone\tbuilt in a scratch dir since deleted",
                                                    "0 of 0 kept sources compile"])
            # a new revision with no source carries the mark of the one before; with no mark before, it still fails
            ROOT = os.path.join(t, "r-inherit")
            bare = os.path.join(t, "bare")
            os.makedirs(bare, exist_ok=True)
            for nm, body in (("s1", "Stock one"), ("s2", "Stock two"), ("u1", "Upload one"), ("u2", "Upload two")):
                shutil.copy(mkpdf(src, nm, body), os.path.join(bare, nm + ".pdf"))
            bp = lambda nm: os.path.join(bare, nm + ".pdf")     # noqa: E731
            run("file", bp("s1"), "--project", "Inh", "--kind", "work", "--title", "Stock")
            run("file", bp("u1"), "--project", "Inh", "--title", "Upload")
            run("gone", "001-0001-A", "--why", "generated from live Odoo data")
            rcs, os_ = run("file", bp("s2"), "--project", "Inh", "--title", "Stock")
            rcu, ou = run("file", bp("u2"), "--project", "Inh", "--title", "Upload")
            rc, o = run("check")
            revs = {n: d["revisions"] for n, d in load()["documents"].items()}
            ok("a new revision filed with no source carries the gone mark of the one before; one whose revision before "
               "has no mark is not marked and still fails check",
               rcs == 0 and "001-0001-B" in os_ and "marked gone as it was" in os_
               and revs["001-0001"][1].get("source_gone", {}).get("why") == "generated from live Odoo data"
               and rcu == 0 and "source_gone" not in revs["001-0002"][1] and "marked gone" not in ou
               and rc == 1 and o.splitlines() == ["001-0002-B\tno source\tno --source recorded",
                                                  "001-0001-B\tgone\tgenerated from live Odoo data",
                                                  "0 of 0 kept sources compile"])
            # --no-source marks at filing; an unchanged rebuild with it marks a sourceless current revision
            ROOT = os.path.join(t, "r-nosource")
            rcr = [run("file", bp("s1"), "--project", "Nos", "--kind", "work", "--title", "T", *x)[0]
                   for x in (("--no-source", "  "), ("--no-source", "x", "--source", bp("s2")),
                             ("--no-source", "x", "--latex", c3))]
            nothing = not os.path.exists(os.path.join(ROOT, "register.json")) or not load()["documents"]
            rcn, on = run("file", bp("s1"), "--project", "Nos", "--kind", "work", "--title", "Stock",
                          "--no-source", "generated  from live Odoo data")
            run("file", bp("u1"), "--project", "Nos", "--title", "Upload")
            rc, o = run("check")
            rcb, ob = run("file", bp("u1"), "--project", "Nos", "--title", "Upload", "--no-source", "a Notability note")
            rc2, o2 = run("check")
            ok("--no-source marks the revision it files gone; an unchanged rebuild with it marks the sourceless current "
               "one; an empty why, or --no-source with --source or --latex, is refused and files nothing",
               rcr == [2, 2, 2] and nothing and rcn == 0 and "001-0001-A" in on
               and rc == 1 and o.splitlines()[0] == "001-0002-A\tno source\tno --source recorded"
               and rcb == 0 and "unchanged" in ob and "source gone" in ob
               and rc2 == 0 and o2.splitlines() == ["001-0001-A\tgone\tgenerated from live Odoo data",
                                                    "001-0002-A\tgone\ta Notability note",
                                                    "0 of 0 kept sources compile"])
            # gone on a kept source: only one that fails now (a cached pass is no help), and check then says gone
            ROOT = os.path.join(t, "r-partial")
            checker = os.environ.pop("DOCS_SOURCE_CHECK")          # filed unchecked, so a failing source is kept
            run("file", mkpdf(src, "pt1", "Partial one"), "--project", "Part", "--kind", "work", "--title", "Broken", "--latex", c3)
            run("file", mkpdf(src, "pt2", "Partial two"), "--project", "Part", "--title", "Fine", "--latex", g1)
            os.environ["DOCS_SOURCE_CHECK"] = checker
            run("check")                                           # caches the pass of the second
            rcn, on = run("gone", "001-0002-A", "--why", "needs nothing")
            rcp, op = run("gone", "001-0001-A", "--why", "figures lost  with the old scratch dir")
            with open(os.path.join(ROOT, "register.json")) as fh:
                gone_rec = json.load(fh)["documents"]["001-0001"]["revisions"][0].get("source_gone", {})
            rc2, o2 = run("check")
            ok("gone accepts a kept source that fails and refuses one that compiles; check then lists it as gone, "
               "not a problem",
               rcn == 2 and "compiles" in on and rcp == 0
               and op.strip() == "001-0001-A\tgone\tfigures lost with the old scratch dir"
               and gone_rec.get("partial") is True and gone_rec.get("why") == "figures lost with the old scratch dir"
               and rc2 == 0 and o2.splitlines() == ["001-0001-A\tgone\tfigures lost with the old scratch dir",
                                                    "1 of 1 kept sources compile"])
            ROOT = os.path.join(t, "r-chk")
            # a check that could not run: its own first message when it printed a verdict, else its exit code
            vt = {}
            for word in ("SAYSNO", "CANTRUN"):
                vt[word] = os.path.join(t, f"verdict-{word}.tar.gz")
                with tarfile.open(vt[word], "w:gz") as tf:
                    b = f"\\documentclass{{article}}\\begin{{document}}{word}\\end{{document}}\n".encode()
                    ti = tarfile.TarInfo("main.tex")
                    ti.size = len(b)
                    tf.addfile(ti, io.BytesIO(b))
            (vs, rs), (vc, rcn) = (run_check(os.environ["DOCS_SOURCE_CHECK"], vt[w]) for w in ("SAYSNO", "CANTRUN"))
            ok("a check that cannot run says its own reason when it printed one, else its exit code",
               not rs and first_error(vs, rs).endswith("exit 2: no main named")
               and not rcn and "exit 3, no verdict" in first_error(vc, rcn))
            fslack, slog = os.path.join(t, "fakeslack.py"), os.path.join(t, "fakeslack.log")
            with open(fslack, "w") as f:
                f.write(f"#!{sys.executable}\nimport json, sys\nopen({slog!r}, 'a').write(json.dumps(sys.argv[1:]) + '\\n')\n")
            os.chmod(fslack, 0o755)
            os.environ["CC_SLACK_BIN"] = fslack
            os.environ["DOCS_CHECK_CHANNEL"] = "#docs-check"

            def posts():
                try:
                    return [json.loads(x) for x in open(slog)]
                except OSError:
                    return []
            run("check", "--post")
            run("check", "--post")
            p = posts()
            ok("--post posts the summary once, and not again for the same problems",
               len(p) == 1 and p[0][:4] == ["post", "-c", "#docs-check", "--id"] and p[0][4].startswith("docs-check-")
               and p[0][5] == "--major" and "1 of 2 kept sources compile" in p[0][6] and "001-0003-A" in p[0][6]
               and "fancypkg" in p[0][6] and len(p[0][6]) < 800)
            update_checks(lambda c: c["post"].update(at="2020-01-01T00:00:00Z"))
            run("check", "--post")
            ok("the same problems are posted again once the last post is over 20 h old", len(posts()) == 2)
            shutil.copy(mkpdf(src, "chk5", "Check five"), os.path.join(alone, "chk5.pdf"))   # no .tex beside it
            rc, o = run("file", os.path.join(alone, "chk5.pdf"), "--project", "Chk", "--title", "Another bare")
            for _ in range(1200):    # a loaded box can take a while to start the detached check
                if len(posts()) > 2:
                    break
                time.sleep(0.1)
            ok("a filing with DOCS_CHECK_CHANNEL set starts `check --post` on its own, and a new problem is posted",
               rc == 0 and len(posts()) == 3 and "001-0005-A" not in posts()[1][6] and "No source (2)" in posts()[2][6])
            for k in ("CC_SLACK_BIN", "DOCS_CHECK_CHANNEL"):
                os.environ.pop(k)
            # backfill --from, and a re-keep of a source with no manifest or failing the check
            ROOT = os.path.join(t, "r-bf2")
            os.environ.pop("DOCS_SOURCE_CHECK")
            run("file", os.path.join(alone, "no.pdf"), "--project", "Bf", "--kind", "work", "--title", "Bare")
            b2 = texdir("bf2", "\\documentclass{article}\\begin{document}old\\end{document}\n")
            b3 = texdir("bf3", "\\documentclass{article}\\begin{document}BROKEN\\end{document}\n")
            b4 = texdir("bf4", "\\documentclass{article}\\begin{document}fine\\end{document}\n")
            run("file", mkpdf(src, "bf2", "Backfill two"), "--project", "Bf", "--title", "Old", "--source", b2)
            run("file", mkpdf(src, "bf3", "Backfill three"), "--project", "Bf", "--title", "Failing", "--source", b3)
            run("file", mkpdf(src, "bf4", "Backfill four"), "--project", "Bf", "--title", "Fine", "--source", b4)
            reg = load()
            r2 = reg["documents"]["001-0002"]["revisions"][-1]
            pack([(b2, "main.tex")], os.path.join(ROOT, r2["sources"]))      # an old tarball, no manifest
            for k in ("source_main", "source_engine"):
                r2.pop(k)
            save(reg)
            badtar = open(os.path.join(ROOT, "sources", "001", "001-0003-A.tar.gz"), "rb").read()
            os.environ["DOCS_SOURCE_CHECK"] = f"{sys.executable} {fake} {flog}"
            run("check")
            tried()
            tsv = os.path.join(t, "from.tsv")
            with open(tsv, "w") as f:
                f.write(f"# picked by hand\n001-0001\t{g1}\n001-0003\tnone\n001-0002\t/elsewhere.tex\n")
            rc, o = run("backfill-sources", "--from", tsv)
            reg = load()
            ok("backfill --from sets a missing source and keeps it; re-keeps a tarball with no manifest; a failing "
               "source is not kept and its old tarball stays; a cached pass is skipped",
               rc == 0 and "001-0001-A\tkept\t1 file(s), pdflatex, compiles" in o
               and reg["documents"]["001-0001"]["source"] == g1
               and reg["documents"]["001-0001"]["revisions"][-1].get("source_main") == "main.tex"
               and "001-0002-A\tkept\t" in o and reg["documents"]["001-0002"]["source"] == b2
               and reg["documents"]["001-0002"]["revisions"][-1].get("source_engine") == "pdflatex"
               and "001-0003-A\tnot kept\tdoes not compile: main.tex:3: Undefined control sequence." in o
               and open(os.path.join(ROOT, "sources", "001", "001-0003-A.tar.gz"), "rb").read() == badtar
               and "001-0004" not in o)
            # backfill --from's `nearest` column: recorded on the revision it keeps, and only there
            ROOT = os.path.join(t, "r-bf3")
            n1 = texdir("near1", "\\documentclass{article}\\begin{document}near\\end{document}\n")
            n2 = texdir("near2", "\\documentclass{article}\\begin{document}exact\\end{document}\n")
            bare = os.path.join(t, "bare-near")                  # PDFs filed with no .tex beside them
            os.makedirs(bare)
            for nm, body in (("nr1", "Near one"), ("nr2", "Near two")):
                shutil.copy(mkpdf(src, nm, body), os.path.join(bare, nm + ".pdf"))
            run("file", os.path.join(bare, "nr1.pdf"), "--project", "Nr", "--kind", "work", "--title", "Near")
            run("file", os.path.join(bare, "nr2.pdf"), "--project", "Nr", "--title", "Exact")
            tsv3 = os.path.join(t, "near.tsv")
            with open(tsv3, "w") as f:
                f.write(f"001-0001\t{n1}\tnearest\n001-0002\t{n2}\n")
            rc, o = run("backfill-sources", "--from", tsv3)
            reg = load()
            ok("backfill --from's nearest column records source_nearest on the kept revision; an exact pick does not",
               rc == 0 and "001-0001-A\tkept\t" in o and "001-0002-A\tkept\t" in o
               and reg["documents"]["001-0001"]["revisions"][-1].get("source_nearest") is True
               and "source_nearest" not in reg["documents"]["001-0002"]["revisions"][-1])
            # a re-keep never swaps the source kept at filing for the working tree's edit of it: an old tarball
            # (no manifest) whose .tex was edited after filing stays as it is; one whose .tex is unchanged is re-kept
            ROOT = os.path.join(t, "r-bf4")
            os.environ.pop("DOCS_SOURCE_CHECK")
            e1 = texdir("edited", "\\documentclass{article}\\begin{document}old\\end{document}\n")
            e2 = texdir("same", "\\documentclass{article}\\begin{document}same\\end{document}\n")
            run("file", mkpdf(src, "ed1", "Edited later"), "--project", "Ed", "--kind", "work", "--title", "Edited",
                "--source", e1)
            run("file", mkpdf(src, "ed2", "Unchanged"), "--project", "Ed", "--title", "Same", "--source", e2)
            reg = load()
            tars = {}
            for num, tex in (("001-0001", e1), ("001-0002", e2)):
                r = reg["documents"][num]["revisions"][-1]
                pack([(tex, "main.tex")], os.path.join(ROOT, r["sources"]))     # as a filing before manifests kept it
                for k in ("source_main", "source_engine", "source_checked"):
                    r.pop(k, None)
                tars[num] = open(os.path.join(ROOT, r["sources"]), "rb").read()
            save(reg)
            with open(e1, "w") as fh:
                fh.write("\\documentclass{article}\\begin{document}new\\end{document}\n")
            os.environ["DOCS_SOURCE_CHECK"] = f"{sys.executable} {fake} {flog}"
            rc, o = run("backfill-sources")
            reg = load()
            r1, r2 = (reg["documents"][n]["revisions"][-1] for n in ("001-0001", "001-0002"))
            ok("backfill keeps an old tarball whose .tex was edited after filing, and re-keeps an unchanged one",
               rc == 0 and "001-0001-A\tnot kept\tsource changed since filing: main.tex" in o
               and open(os.path.join(ROOT, r1["sources"]), "rb").read() == tars["001-0001"]
               and "source_main" not in r1 and "sources_backfilled" not in r1
               and "001-0002-A\tkept\t" in o and has_manifest(os.path.join(ROOT, r2["sources"]))
               and r2.get("source_main") == "main.tex" and "source_nearest" not in r2)
        finally:
            globals()["_cwds"] = old_cwds
            if old_env is None:
                os.environ.pop("CC_SLACK_DIR", None)
            else:
                os.environ["CC_SLACK_DIR"] = old_env
    # SUPPORTING FILES: each case files into a register of its own
    with tempfile.TemporaryDirectory(prefix="cc-docs-att-") as t:
        src = os.path.join(t, "src")
        os.makedirs(src)
        MEMBERS = os.path.join(t, "members")
        wid = "fedcba9876543210"
        os.makedirs(os.path.join(MEMBERS, "kid2"))
        with open(os.path.join(MEMBERS, "kid2", "workspace-id"), "w") as f:
            f.write(wid + "\n")

        def blob(name, body):
            p = os.path.join(t, "out", name)
            os.makedirs(os.path.dirname(p), exist_ok=True)
            with open(p, "wb") as f:
                f.write(body)
            return p

        pa, pb, pc = (mkpdf(src, nm, body) for nm, body in (("pa", "Board one"), ("pb", "Board two"), ("pc", "Board three")))
        g1, d1 = blob("board-F_Cu.gbr", b"G04 top*\n"), blob("board.drl", b"M48\n")
        ROOT = os.path.join(t, "a1")
        rc, o = run("file", pa, "--project", "Boards", "--kind", "work", "--title", "Board", "--attach", g1, "--attach", d1)
        reg = load()
        r = reg["documents"]["001-0001"]["revisions"][0]
        att = {x["name"]: x for x in r.get("attachments", [])}
        ok("file --attach keeps each file once by content, read-only, with its size, sha256 and crc32",
           rc == 0 and sorted(att) == ["board-F_Cu.gbr", "board.drl"]
           and att["board.drl"]["blob"] == "attachments/" + att["board.drl"]["sha256"][:2] + "/" + att["board.drl"]["sha256"]
           and open(os.path.join(ROOT, att["board.drl"]["blob"]), "rb").read() == b"M48\n"
           and not os.stat(os.path.join(ROOT, att["board.drl"]["blob"])).st_mode & 0o222
           and att["board.drl"]["crc32"] == zlib.crc32(b"M48\n") and att["board.drl"]["bytes"] == 4
           and not [f for f in os.listdir(os.path.join(ROOT, "attachments")) if f.startswith(".part")])
        # pdf: a text revision filed with no PDF gets its rendered one; one that has a PDF is never rewritten
        ROOT = os.path.join(t, "p1")
        run("file", pa, "--project", "Boards", "--kind", "work", "--title", "Board")
        reg = load()
        dd = reg["documents"]["001-0001"]
        dd["visibility"] = ["owner", wid]
        dd["revisions"] += [{"rev": "B", "date": "2026-10-01", "file": None, "source_files": ["plan.md"]},
                            {"rev": "C", "date": "2026-10-02", "file": None, "source_files": ["plan.md"]}]
        save(reg)
        write_views(reg, {wid})
        rcl, ol = run("library", "--viewer", "owner")
        rc, o = run("pdf", "001-0001-B", pb)
        rc2, o2 = run("pdf", "001-0001-B", pc)
        rc3, o3 = run("pdf", "001-0001-Z", pb)
        rc4, o4 = run("pdf", "001-0001-C", mkpdf(src, "pn", "001-0001-C rendered with its own number"))
        rb, rcc = load()["documents"]["001-0001"]["revisions"][1:]
        bf = os.path.join(ROOT, rb.get("file") or "none")
        with open(os.path.join(ROOT, "ws", wid, "register.json")) as fh:
            vb = json.load(fh)["documents"]["001-0001"]["revisions"][1]
        ok("pdf files a text revision's PDF onto it, stamped and read-only, linked into a workspace's view; a second "
           "PDF, an unknown revision and a PDF carrying its own number (kept as it is) each do what file does",
           rcl == 0 and '"file": null' in ol and rc == 0 and o.startswith("001-0001-B\t")
           and rb["file"] == "files/001/001-0001-B_board.pdf" and rb["stamped"] == "overlay" and rb["pages"] == 1
           and "001-0001-B" in pdftext(bf) and not os.stat(bf).st_mode & 0o222
           and os.path.exists(os.path.join(ROOT, "ws", wid, rb["file"])) and vb["file"] == rb["file"]
           and rc2 == 2 and "has its PDF already" in o2 and rc3 == 2
           and rc4 == 0 and rcc["stamped"] == "carried")
        # brief: "filing a .md with no PDF gives a revision that the box renders to done"
        import contextlib
        ROOT = os.path.join(t, "p-md")
        md = os.path.join(src, "plan.md")
        with open(md, "w") as fh:
            fh.write("# Plan\n\nOne.\n")
        rc, o = run("file", md, "--project", "Notes", "--kind", "work", "--title", "Plan", "--note", "first")
        rm = load()["documents"]["001-0001"]["revisions"][0]
        kept = os.path.join(ROOT, rm.get("sources") or "none")
        with tarfile.open(kept) if os.path.isfile(kept) else contextlib.nullcontext() as tf:
            names = tf.getnames() if tf else []
            body = tf.extractfile("plan.md").read() if "plan.md" in names else b""
        rcl, ol = run("library", "--viewer", "owner")
        lv = json.loads(ol)["documents"][0]["revisions"][0] if rcl == 0 else {}
        rcu, ou = run("file", md, "--project", "Notes", "--title", "Plan")
        ok("file given a .md and no PDF files a text revision: no PDF, the .md kept as its Markdown source, the "
           "path its PDF will have printed; the same bytes again file nothing",
           rc == 0 and o.startswith("001-0001-A\t" + os.path.join(ROOT, "files", "001", "001-0001-A_plan.pdf")
                                    + "\tfiled, rendering")
           and rm["file"] is None and rm["source_main"] == "plan.md" and rm.get("note") == "first"
           and rm["source_sha256"] == hashlib.sha256(b"# Plan\n\nOne.\n").hexdigest()
           and names == ["plan.md"] and body == b"# Plan\n\nOne.\n" and lv.get("file", 0) is None
           and rcu == 0 and "001-0001-A\t-\tunchanged" in ou and len(load()["documents"]["001-0001"]["revisions"]) == 1)
        rcp, op = run("pdf", "001-0001-A", mkpdf(src, "plan-print", "Plan printed"))
        rm = load()["documents"]["001-0001"]["revisions"][0]
        rcu, ou = run("file", md, "--project", "Notes", "--title", "Plan")
        with open(md, "a") as fh:
            fh.write("Two.\n")
        rcb, ob = run("file", md, "--project", "Notes", "--title", "Plan")
        rcc_, oc = run("file", mkpdf(src, "plan-pdf", "Plan as a PDF"), "--project", "Notes", "--title", "Plan")
        revs = load()["documents"]["001-0001"]["revisions"]
        ok("the box's print goes on with pdf and the revision is done; unchanged Markdown still files nothing, "
           "changed Markdown files the next letter with no PDF, and a PDF after it files as usual",
           rcp == 0 and rm["file"] == "files/001/001-0001-A_plan.pdf" and rm["stamped"] == "overlay"
           and rcu == 0 and "001-0001-A\t" + os.path.join(ROOT, rm["file"]) + "\tunchanged" in ou
           and rcb == 0 and ob.startswith("001-0001-B\t") and revs[1]["file"] is None
           and rcc_ == 0 and oc.startswith("001-0001-C\t") and revs[2]["file"])
        rcx, ox = run("file", md, "--project", "Notes", "--title", "Plan", "--attach", md)
        ok("a Markdown filing refuses --attach, nothing filed", rcx == 2 and "--attach" in ox
           and len(load()["documents"]["001-0001"]["revisions"]) == 3)
        # brief: "a saved revision produces a branch and PR in the source repo and an undeclared project is unchanged"
        ROOT = os.path.join(t, "p-decl")
        bare, site, ghlog = os.path.join(t, "origin.git"), os.path.join(t, "site"), os.path.join(t, "gh.log")

        def g(*x, cwd=site):
            return subprocess.run(["git", *x], cwd=cwd, capture_output=True, text=True)
        subprocess.run(["git", "init", "-q", "--bare", "-b", "main", bare], capture_output=True)
        subprocess.run(["git", "clone", "-q", bare, site], capture_output=True)
        g("config", "user.email", "sc@example.invalid")
        g("config", "user.name", "selfcheck")
        os.makedirs(os.path.join(site, "content"))
        for rel, txt in (("content/text.md", "# Site\n\nOld words.\n"), ("content/broken.md", "# Broken\n"),
                         ("library.json", json.dumps({"documents": [
                             {"project": "Site", "title": "Site text", "content": "content/text.md",
                              "rebuild": ["sh", "-c", "tr a-z A-Z < content/text.md > built.txt"]},
                             {"project": "Site", "title": "Broken", "content": "content/broken.md",
                              "rebuild": ["sh", "-c", "echo bad field >&2; exit 3"]},
                             {"project": "Site", "title": "Bad", "content": "content/text.md", "rebuild": "make"},
                             {"project": "Site", "title": "Linked", "content": "content/link.md", "rebuild": ["true"]},
                             {"project": "Site", "title": "Via dir", "content": "lnk/x.md", "rebuild": ["true"]}]}))):
            with open(os.path.join(site, rel), "w") as fh:
                fh.write(txt)
        outdir, victim = os.path.join(t, "outdir"), os.path.join(t, "victim.md")
        os.makedirs(outdir)
        for f in (os.path.join(outdir, "x.md"), victim):
            with open(f, "w") as fh:
                fh.write("victim\n")
        os.symlink(victim, os.path.join(site, "content", "link.md"))     # a file outside the repo, by a link
        os.symlink(outdir, os.path.join(site, "lnk"))                     # a folder outside it, by a link
        g("add", "-A")
        g("commit", "-q", "-m", "start")
        g("push", "-q", "origin", "main")
        g("remote", "set-head", "origin", "main")
        fakegh = os.path.join(t, "fake-gh")
        with open(fakegh, "w") as fh:
            # a stub gh: `pr create` logs its argv, records the head it opened a PR for, and prints the PR's url
            # (with gh-slow present it hangs instead); `pr list --head H` prints the urls recorded for H, or fails
            # while gh-listfail is present
            fh.write(f"""#!/bin/sh
h=; prev=
for x in "$@"; do [ "$prev" = --head ] && h=$x; prev=$x; done
if [ "$1 $2" = "pr list" ]; then
  [ -e {t}/gh-listfail ] && {{ echo list broke >&2; exit 1; }}
  [ -e {t}/gh-prs ] && awk -v h="$h" '$2 == h {{print $1}}' {t}/gh-prs
  exit 0
fi
printf '%s\\n' "$@" > {ghlog}
[ -e {t}/gh-slow ] && exec sleep 3
echo "https://github.com/o/site/pull/7 $h" >> {t}/gh-prs
echo https://github.com/o/site/pull/7
""")
        os.chmod(fakegh, 0o755)
        os.environ["CC_DOCS_GH"] = fakegh
        sitepdf = mkpdf(src, "site-pdf", "Site text as a PDF")
        edit = os.path.join(t, "edit.md")
        with open(edit, "w") as fh:
            fh.write("# Site\n\nNew words.\n")
        here = os.getcwd()
        os.chdir(site)
        try:
            rc1, o1 = run("file", sitepdf, "--project", "Site", "--kind", "work", "--title", "Site text",
                          "--latex", os.path.join(src, "site-pdf.tex"))
            r1 = load()["documents"]["001-0001"]["revisions"][0]
            gh1 = os.path.exists(ghlog)
            rc2, o2 = run("file", edit, "--project", "Site", "--title", "Site text", "--note", "new words")
            with open(ghlog) if os.path.exists(ghlog) else contextlib.nullcontext() as fh:
                ghargs = fh.read().split("\n") if fh else []
            os.unlink(ghlog) if os.path.exists(ghlog) else None
            rc3, o3 = run("file", edit, "--project", "Site", "--title", "Site text")
            gh3 = os.path.exists(ghlog)
            rc4, o4 = run("file", sitepdf, "--project", "Site", "--title", "Other")
            gh4 = os.path.exists(ghlog)
            rc5, o5 = run("file", edit, "--project", "Site", "--title", "Broken")
            gh5 = os.path.exists(ghlog)
            rc6, o6 = run("file", edit, "--project", "Site", "--title", "Bad")
        finally:
            os.chdir(here)
            os.environ.pop("CC_DOCS_GH", None)
        docs = load()["documents"]
        on = lambda ref: g("show", ref, cwd=bare).stdout     # noqa: E731
        heads = g("for-each-ref", "--format=%(refname)", "refs/heads", cwd=bare).stdout.split()
        ok("a document its repo declares in library.json is filed as its Markdown, whatever file the maker gave, and "
           "nothing is carried back while the repo's file already says it",
           rc1 == 0 and o1.startswith("001-0001-A\t") and "is declared in" in o1 and r1["file"] is None
           and r1["source_main"] == "text.md" and "already says this" in o1 and not gh1)
        ok("a changed revision of it lands on a branch library/<rev> in the repo, rebuilt there, with a PR opened "
           "from it; origin's default branch and the local branches are untouched",
           rc2 == 0 and o2.startswith("001-0001-B\t") and "carried back into site as https://github.com/o/site/pull/7"
           in o2 and on("library/001-0001-B:content/text.md") == "# Site\n\nNew words.\n"
           and on("library/001-0001-B:built.txt") == "# SITE\n\nNEW WORDS.\n"
           and on("main:content/text.md") == "# Site\n\nOld words.\n"
           and ghargs[:7] == ["pr", "create", "--base", "main", "--head", "library/001-0001-B", "--title"]
           and "What changed: new words" in "\n".join(ghargs)
           and not g("branch", "--list", "library/*").stdout.strip()
           and len(g("worktree", "list").stdout.strip().splitlines()) == 1)
        ok("the same Markdown again files nothing and pushes nothing, since its branch is on origin already",
           rc3 == 0 and "001-0001-B\t-\tunchanged" in o3 and "already carried back" in o3 and not gh3)
        ok("a document the repo does not declare files its PDF as before and carries nothing back",
           rc4 == 0 and docs["001-0002"]["revisions"][0]["file"] and "declared" not in o4 and "carried" not in o4
           and not gh4 and heads == ["refs/heads/library/001-0001-B", "refs/heads/main"])
        ok("a rebuild that fails leaves the revision filed and pushes no branch and opens no PR; an entry whose "
           "rebuild is not a list refuses the filing",
           rc5 == 0 and docs["001-0003"]["title"] == "Broken" and "failed, so no PR" in o5 and "bad field" in o5
           and not gh5 and "refs/heads/library/001-0003-A" not in heads
           and rc6 == 2 and 'needs "rebuild"' in o6 and not any(d["title"] == "Bad" for d in docs.values()))
        # the review's cases of a declared document: an explicit --source .md wins over the content file; a
        # library/ branch that was there already is left alone; a symlinked content path is refused, in the checkout
        # and on the default branch; a pushed branch with no PR gets one without a second push; a step that runs out
        # of time says so; and the base is the HEAD origin advertises, not a stale refs/remotes/origin/HEAD
        def mdf(name, words):
            f = os.path.join(t, name)
            with open(f, "w") as fh:
                fh.write(f"# Site\n\n{words}\n")
            return f
        draft, fourth, fifth, sixth = (mdf(n + ".md", w) for n, w in (("draft", "Draft words."), (
            "fourth", "Fourth words."), ("fifth", "Fifth words."), ("sixth", "Sixth words.")))
        flag = lambda n, on=True: open(os.path.join(t, n), "w").close() if on else os.unlink(os.path.join(t, n))  # noqa: E731
        gone = lambda f: os.unlink(f) if os.path.exists(f) else None     # noqa: E731
        os.environ["CC_DOCS_GH"] = fakegh
        os.chdir(site)
        wait = GH_WAIT
        try:
            gone(ghlog)
            rc7, o7 = run("file", sitepdf, "--source", draft, "--project", "Site", "--title", "Site text")
            gh7 = open(ghlog).read() if os.path.exists(ghlog) else ""
            rc8, o8 = run("file", sitepdf, "--project", "Site", "--title", "Site text", "--attach", draft)
            gone(ghlog)
            flag("gh-slow")
            globals()["GH_WAIT"] = 1
            rc9, o9 = run("file", fourth, "--project", "Site", "--title", "Site text")
            globals()["GH_WAIT"] = wait
            flag("gh-slow", False)
            sha_d = g("rev-parse", "library/001-0001-D", cwd=bare).stdout
            gone(ghlog)
            flag("gh-listfail")
            rc10, o10 = run("file", fourth, "--project", "Site", "--title", "Site text")
            gh10 = os.path.exists(ghlog)
            flag("gh-listfail", False)
            rc11, o11 = run("file", fourth, "--project", "Site", "--title", "Site text")
            gh11 = open(ghlog).read().split("\n") if os.path.exists(ghlog) else []
            sha_d2 = g("rev-parse", "library/001-0001-D", cwd=bare).stdout
            g("branch", "library/001-0001-E", "main")      # the owner's branch, by the name revision E would take
            sha_e = g("rev-parse", "library/001-0001-E").stdout
            rc12, o12 = run("file", fifth, "--project", "Site", "--title", "Site text")
            rc13, o13 = run("file", edit, "--project", "Site", "--title", "Linked")
            rc14, o14 = run("file", edit, "--project", "Site", "--title", "Via dir")
            # origin's default becomes trunk, whose content/text.md is a link out of the repo; this clone's
            # refs/remotes/origin/HEAD still says main, where the file is plain
            other = os.path.join(t, "other")
            subprocess.run(["git", "clone", "-q", bare, other], capture_output=True)
            g("checkout", "-q", "-b", "trunk", cwd=other)
            os.unlink(os.path.join(other, "content", "text.md"))
            os.symlink(victim, os.path.join(other, "content", "text.md"))
            g("add", "-A", cwd=other)
            g("-c", "user.email=sc@example.invalid", "-c", "user.name=sc", "commit", "-q", "-m", "link", cwd=other)
            g("push", "-q", "origin", "trunk", cwd=other)
            g("symbolic-ref", "HEAD", "refs/heads/trunk", cwd=bare)
            rc15, o15 = run("file", sixth, "--project", "Site", "--title", "Site text")
        finally:
            globals()["GH_WAIT"] = wait
            os.chdir(here)
            os.environ.pop("CC_DOCS_GH", None)
        revs = load()["documents"]["001-0001"]["revisions"]
        heads = g("for-each-ref", "--format=%(refname)", "refs/heads", cwd=bare).stdout.split()
        ok("a declared document given a PDF and --source <a .md> files that .md's words, not the repo's content "
           "file, and carries them back; --attach on it is refused",
           rc7 == 0 and o7.startswith("001-0001-C\t") and f"filing the Markdown {draft}" in o7
           and revs[2]["source_sha256"] == hashlib.sha256(b"# Site\n\nDraft words.\n").hexdigest()
           and on("library/001-0001-C:content/text.md") == "# Site\n\nDraft words.\n" and "library/001-0001-C" in gh7
           and rc8 == 2 and "--attach" in o8 and len(revs) == 6)
        ok("a gh that runs out of time is said, and the revision stays filed with its branch pushed",
           rc9 == 0 and o9.startswith("001-0001-D\t") and "took over 1s" in o9 and revs[3]["rev"] == "D"
           and sha_d.strip())
        ok("filing it again with the branch on origin and no PR found opens one, and pushes nothing; a gh pr list "
           "that fails opens none",
           rc10 == 0 and "unchanged" in o10 and "whether it has a PR is not known" in o10 and "list broke" in o10
           and not gh10 and rc11 == 0 and "carried back into site as https://github.com/o/site/pull/7" in o11
           and "--head" in gh11 and gh11[gh11.index("--head") + 1] == "library/001-0001-D" and sha_d2 == sha_d)
        ok("a local library/ branch that was there already is left where it was, and nothing is carried",
           rc12 == 0 and o12.startswith("001-0001-E\t") and "not carried back: no branch library/001-0001-E" in o12
           and g("rev-parse", "library/001-0001-E").stdout == sha_e and "refs/heads/library/001-0001-E" not in heads)
        ok("a declared content path that is a symlink, or under a symlinked folder, refuses the filing",
           rc13 == 2 and "content/link.md goes through a symlink" in o13
           and rc14 == 2 and "goes through a symlink, lnk" in o14
           and not any(d["title"] in ("Linked", "Via dir") for d in load()["documents"].values()))
        ok("the base is the HEAD origin advertises (trunk), and a content path that is a symlink there is not "
           "written through: nothing pushed, the file it points at untouched, the local branch removed",
           rc15 == 0 and o15.startswith("001-0001-F\t") and "not carried back: on trunk, content/text.md goes "
           "through a symlink" in o15 and open(victim).read() == "victim\n"
           and "refs/heads/library/001-0001-F" not in heads and not g("branch", "--list", "library/001-0001-F").stdout
           and len(g("worktree", "list").stdout.strip().splitlines()) == 1)
        # a --source directory: its own files are kept, so the folder can vanish after filing
        ROOT = os.path.join(t, "p-dir")
        sdir = os.path.join(t, "built-here")
        os.makedirs(os.path.join(sdir, "sub"))
        os.makedirs(os.path.join(sdir, ".git"))
        for rel, txt in (("gen.py", "print(1)\n"), ("sub/data.csv", "a,b\n"), (".hidden", "x"), (".git/HEAD", "y")):
            with open(os.path.join(sdir, rel), "w") as fh:
                fh.write(txt)
        os.symlink(os.path.join(sdir, "gen.py"), os.path.join(sdir, "link.py"))
        os.makedirs(os.path.join(t, "gen-out"))
        gp = shutil.copy(pa, os.path.join(t, "gen-out", "gen.pdf"))    # no .tex beside it: --source decides
        rc, o = run("file", gp, "--project", "Gen", "--kind", "work", "--title", "Generated", "--source", sdir)
        rg = load()["documents"]["001-0001"]["revisions"][0]
        shutil.rmtree(sdir)
        with tarfile.open(os.path.join(ROOT, rg.get("sources") or "none")) if rg.get("sources") \
                else contextlib.nullcontext() as tf:
            names = sorted(tf.getnames()) if tf else []
        ok("a --source directory keeps its own files by their path under it, no hidden names or links, and they "
           "outlast the folder", rc == 0 and names == ["gen.py", "sub/data.csv"] and rg["source_files"] == names)

        def board(root, *attach):
            """A register of its own at root, holding 001-0001-A filed from pa with `attach` on it."""
            global ROOT
            ROOT = os.path.join(t, root)
            run("file", pa, "--project", "Boards", "--kind", "work", "--title", "Board",
                *[x for f in attach for x in ("--attach", f)])

        board("a1b", g1, d1)
        rc, o = run("file", pb, "--project", "Boards", "--title", "Board")
        b = load()["documents"]["001-0001"]["revisions"][1]
        ok("a new revision filed without --attach carries the one before's files, marked, and says so",
           rc == 0 and [x["name"] for x in b.get("attachments", [])] == ["board-F_Cu.gbr", "board.drl"]
           and all(x.get("carried_from") == "A" for x in b["attachments"])
           and "001-0001-B carries 2 supporting file(s) from A" in o)
        g2 = blob("v2/board-F_Cu.gbr", b"G04 top v2*\n")
        board("a1c", g1, d1)
        run("file", pb, "--project", "Boards", "--title", "Board")
        rc, o = run("file", pc, "--project", "Boards", "--title", "Board", "--attach", g2)
        reg = load()
        c = {x["name"]: x for x in reg["documents"]["001-0001"]["revisions"][2]["attachments"]}
        ok("a new revision's own --attach replaces that name; the rest are carried from where they were first attached; "
           "the revision before keeps its own",
           rc == 0 and open(os.path.join(ROOT, c["board-F_Cu.gbr"]["blob"]), "rb").read() == b"G04 top v2*\n"
           and "carried_from" not in c["board-F_Cu.gbr"] and c["board.drl"].get("carried_from") == "A"
           and reg["documents"]["001-0001"]["revisions"][1]["attachments"][0]["sha256"] == att["board-F_Cu.gbr"]["sha256"])
        board("a1d", d1)
        reg = load()
        rc, o = run("file", pa, "--project", "Boards", "--title", "Board", "--attach", d1)
        rc2, o2 = run("file", pa, "--project", "Boards", "--title", "Board", "--attach", g1)
        cur = load()["documents"]["001-0001"]["revisions"]
        ok("an unchanged build's --attach with bytes the revision already has changes nothing; with a new file it "
           "puts it on the current revision and files no revision",
           rc == 0 and "unchanged, nothing filed" in o and load() != reg and len(cur) == 1
           and [x["name"] for x in cur[0]["attachments"]] == ["board.drl", "board-F_Cu.gbr"]
           and rc2 == 0 and "recorded supporting files board-F_Cu.gbr" in o2)
        board("a1e", d1)
        reg = load()
        run("file", pa, "--project", "Boards", "--title", "Board", "--attach", d1)
        ok("…and the same bytes alone leave the register exactly as it was", load() == reg)
        # a different board revision carries nothing
        ROOT = os.path.join(t, "a2")
        run("file", pa, "--project", "Boards", "--kind", "work", "--title", "Board", "--describes", "PCB-0001-A",
            "--attach", g1)
        rc, o = run("file", pb, "--project", "Boards", "--title", "Board", "--describes", "PCB-0001-B")
        rc2, o2 = run("file", pc, "--project", "Boards", "--title", "Board", "--describes", "PCB-0001-B", "--attach", d1)
        rc3, o3 = run("file", mkpdf(src, "pd", "Board four"), "--project", "Boards", "--title", "Board",
                      "--describes", "PCB-0001-B")
        revs = load()["documents"]["001-0001"]["revisions"]
        ok("a revision describing another board revision carries none of the one before's files and says so; the same "
           "board revision carries",
           rc == 0 and "attachments" not in revs[1] and "B's 1 supporting file(s)" not in o
           and "A's 1 supporting file(s) stay on A and are not carried" in o
           and [x["name"] for x in revs[3]["attachments"]] == ["board.drl"] and revs[3]["attachments"][0]["carried_from"] == "C")
        # attach: add, same bytes, other bytes refused, --replace, --remove, a named revision
        ROOT = os.path.join(t, "a3")
        run("file", pa, "--project", "Boards", "--kind", "work", "--title", "Board")
        run("file", pb, "--project", "Boards", "--title", "Board")
        rc, o = run("attach", "001-0001", g1, d1)
        rc2, o2 = run("attach", "001-0001", g1)
        before = load()
        rc3, o3 = run("attach", "001-0001", g2)
        ok("attach puts files on the current revision; the same bytes again are unchanged; other bytes under the same "
           "name are refused and change nothing",
           rc == 0 and "001-0001-B\tboard-F_Cu.gbr\tattached" in o and "001-0001-B\tboard.drl\tattached" in o
           and rc2 == 0 and "001-0001-B\tboard-F_Cu.gbr\tunchanged" in o2
           and rc3 == 2 and "--replace" in o3 and load() == before
           and not [f for f in os.listdir(os.path.join(ROOT, "attachments")) if f.startswith(".part")])
        ROOT = os.path.join(t, "a3b")
        run("file", pa, "--project", "Boards", "--kind", "work", "--title", "Board")
        run("file", pb, "--project", "Boards", "--title", "Board")
        run("attach", "001-0001", g1, d1)
        rc, o = run("attach", "001-0001", g2, "--replace")
        rc2, o2 = run("attach", "001-0001-B", "--remove", "board.drl")
        rc3, o3 = run("attach", "001-0001-A", d1)
        rc4, o4 = run("attach", "001-0001", "--remove", "nothing.txt")
        revs = load()["documents"]["001-0001"]["revisions"]
        ok("--replace swaps the bytes, --remove takes a name off, a named older revision gets its own, a name not there "
           "is refused",
           rc == 0 and "\treplaced" in o and rc2 == 0 and "board.drl\tremoved" in o2
           and [x["name"] for x in revs[1]["attachments"]] == ["board-F_Cu.gbr"]
           and revs[1]["attachments"][0]["bytes"] == len(b"G04 top v2*\n")
           and rc3 == 0 and [x["name"] for x in revs[0]["attachments"]] == ["board.drl"] and rc4 == 2)
        # caps and bad input: refused, saying why, nothing filed and nothing attached
        board("a3c", g1)
        before = load()
        os.makedirs(os.path.join(t, "outdir"), exist_ok=True)
        rcs = [run("attach", "001-0001", os.path.join(t, "outdir"))[1], run("attach", "001-0001", os.path.join(t, "nope"))[1],
               run("attach", "001-0001", blob(".hidden", b"x"))[1]]
        caps = ATTACH_FILE_CAP, ATTACH_TOTAL_CAP, ATTACH_REV_CAP
        try:
            ATTACH_FILE_CAP = 10
            rc, o = run("file", pc, "--project", "Boards", "--title", "Board", "--attach", blob("big.zip", b"0" * 11))
            ATTACH_FILE_CAP = caps[0]
            ATTACH_TOTAL_CAP = 20
            rc2, o2 = run("attach", "001-0001", blob("more.bom", b"1" * 15))
            ATTACH_TOTAL_CAP = caps[1]
            ATTACH_REV_CAP = 1
            rc3, o3 = run("attach", "001-0001", d1)
        finally:
            ATTACH_FILE_CAP, ATTACH_TOTAL_CAP, ATTACH_REV_CAP = caps
        ok("a directory, a missing file and a dot-name are refused; a file over the size cap refuses the whole filing; "
           "the total and per-revision caps refuse; each says which, and the register is as it was",
           "is a directory" in rcs[0] and "no such file" in rcs[1] and "rename it" in rcs[2]
           and rc == 2 and "Cloudflare Pages" in o and rc2 == 2 and "GitHub" in o2 and rc3 == 2 and "over 1 a revision" in o3
           and load() == before and not [f for f in os.listdir(os.path.join(ROOT, "attachments")) if f.startswith(".part")])
        # member views: a member's document's files are linked into its view, and leave it when removed
        ROOT = os.path.join(t, "a4")
        run("file", pa, "--project", "Kid2", "--member", "kid2", "--title", "Kid board", "--attach", g1)
        run("file", pb, "--project", "Own", "--kind", "work", "--title", "Own board", "--attach", d1)
        reg = load()
        kb = reg["documents"]["901-0001"]["revisions"][0]["attachments"][0]["blob"]
        ob = reg["documents"]["001-0001"]["revisions"][0]["attachments"][0]["blob"]
        v = os.path.join(ROOT, "ws", wid)
        linked = os.path.exists(os.path.join(v, kb)) and os.path.samefile(os.path.join(v, kb), os.path.join(ROOT, kb))
        run("attach", "901-0001", "--remove", "board-F_Cu.gbr")
        ok("a member's view links its own document's supporting files and not the owner's, and drops one removed",
           linked and not os.path.exists(os.path.join(v, ob)) and not os.path.exists(os.path.join(v, kb))
           and os.path.exists(os.path.join(ROOT, kb)))
        IN_SANDBOX = True
        try:
            rc, o = run("attach", "901-0001", g1)
            rc2, o2 = run("file", pa, "--title", "Kid board", "--attach", g1)
        finally:
            IN_SANDBOX = False
        ok("inside a workspace attach and file --attach are refused", rc == 2 and "host's" in o and rc2 == 2
           and "attached on the host" in o2)
    # link: a fake library site on 127.0.0.1 mints links, reuses an identical one, and answers what each case sets
    import http.server
    import threading

    class Site(http.server.BaseHTTPRequestHandler):
        seen, links, answer, plain = [], {}, [200], [None]

        def log_message(self, *args):
            pass

        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"null")
            Site.seen.append((self.path, self.headers.get("Cf-Access-Client-Id"),
                              self.headers.get("Cf-Access-Client-Secret"), body))
            code = Site.answer[0]
            if code == 200:
                key = json.dumps(body, sort_keys=True)
                reused = key in Site.links
                lid = Site.links.setdefault(key, f"L{len(Site.links) + 1}")
                out = {"id": lid, "name": body.get("name"), "kind": body["kind"], "state": "live",
                       "url": f"http://site.test/l/{lid}", "target": body["target"], "people": body.get("people", []),
                       "reused": reused}
            else:
                out = {"error": "nope"}
            raw = json.dumps(out).encode()
            if code != 200 and Site.plain[0]:
                raw = Site.plain[0].encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Site)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    site = f"http://127.0.0.1:{srv.server_address[1]}"
    lkeys = ("LIBRARY_URL", "LIBRARY_LINK_CLIENT_ID", "LIBRARY_LINK_CLIENT_SECRET", "LIBRARY_FEEDBACK_CLIENT_ID",
             "LIBRARY_FEEDBACK_CLIENT_SECRET")

    def lenv(**kv):
        for k in lkeys:
            os.environ.pop(k, None)
        os.environ.update({k: v for k, v in kv.items()})
        Site.seen.clear()
        Site.answer[0] = 200

    def last():
        return Site.seen[-1] if Site.seen else (None, None, None, None)

    try:
        with tempfile.TemporaryDirectory(prefix="cc-docs-link-") as t:
            ROOT = os.path.join(t, "r")
            lsrc = os.path.join(t, "src")
            os.makedirs(lsrc)
            built = mkpdf(lsrc, "l1", "Link one")
            run("file", built, "--project", "Links", "--kind", "work", "--title", "Linked")
            run("file", mkpdf(lsrc, "l2", "Link two"), "--project", "Links", "--title", "Linked")
            reg = load()
            revs = reg["documents"]["001-0001"]["revisions"]
            fa = os.path.join(ROOT, revs[0]["file"])
            base = dict(LIBRARY_URL=site + "/", LIBRARY_FEEDBACK_CLIENT_ID="fid", LIBRARY_FEEDBACK_CLIENT_SECRET="fsec")

            lenv(**base)
            rc, o = run("link", "001-0001")
            p, cid, sec, body = last()
            ok("link: signed-in by default, the site's url alone on stdout, a bare number follows the newest",
               rc == 0 and o == "http://site.test/l/L1\n" and p == "/api/links"
               and body == {"target": {"number": "001-0001", "rev": None}, "kind": "signed-in"})
            ok("link: the request carries the feedback service token as Access headers, and no output names it",
               (cid, sec) == ("fid", "fsec") and "fsec" not in o)
            rc, o2 = run("link", "001-0001")
            ok("link: a second identical call prints the url the site reused", rc == 0 and o2 == o and len(Site.seen) == 2)

            rc, o = run("link", "001-0001-A", "--kind", "public", "--name", "for the class")
            p, cid, sec, body = last()
            ok("link: public with a revision is pinned and carries its name",
               rc == 0 and o.startswith("http://site.test/l/") and o.count("\n") == 1
               and body == {"target": {"number": "001-0001", "rev": "A"}, "kind": "public", "name": "for the class"})

            rc, o = run("link", "001-0001", "--kind", "private", "--to", "Ann Lee <ann@example.org>", "--to", "bob@example.org")
            body = last()[3]
            ok("link: private sends the people, `Name <addr>` reduced to its address",
               rc == 0 and o.startswith("http://site.test/l/")
               and body["kind"] == "private" and body["people"] == ["ann@example.org", "bob@example.org"])
            n0 = len(Site.seen)
            rc1, o1 = run("link", "001-0001", "--kind", "private")
            rc2, o2 = run("link", "001-0001", "--to", "ann@example.org")
            rc3, o3 = run("link", "001-0001", "--kind", "private", "--to", "not an address")
            ok("link: private without --to, --to without private and a bad address are refused, nothing sent",
               rc1 == 1 and "needs at least one --to" in o1 and rc2 == 1 and "only for --kind private" in o2
               and rc3 == 1 and len(Site.seen) == n0)

            os.environ["MAIL_WORKSPACE"] = "Own@Example.org=owner,ann@example.org=anna"
            try:
                n0 = len(Site.seen)
                rc, o = run("link", "001-0001", "--kind", "private", "--to", "OWN@example.org")
                body = last()[3]
                ok("link: private to the owner alone becomes a signed-in link with no people, and says so",
                   rc == 0 and len(Site.seen) == n0 + 1 and body["kind"] == "signed-in" and "people" not in body
                   and "signed-in link" in o)
                rc, o = run("link", "001-0001", "--kind", "private", "--to", "own@example.org", "--to", "bob@example.org")
                body = last()[3]
                ok("link: private to the owner and another sends only the other",
                   rc == 0 and body["kind"] == "private" and body["people"] == ["bob@example.org"])
            finally:
                os.environ.pop("MAIL_WORKSPACE", None)
            Site.answer[0], Site.plain[0] = 400, "no people left\nsecond line"
            rc, o = run("link", "001-0001", "--kind", "private", "--to", "bob@example.org")
            Site.plain[0] = None
            ok("link: a plain-text 400 body's first line is in the error",
               rc == 1 and "malformed (no people left)" in o and "second line" not in o)
            lenv(**base, LIBRARY_LINK_CLIENT_ID="lid", LIBRARY_LINK_CLIENT_SECRET="lsec")
            run("link", "001-0001")
            ok("link: LIBRARY_LINK_* win over LIBRARY_FEEDBACK_*", last()[1:3] == ("lid", "lsec"))
            lenv(**base, LIBRARY_LINK_CLIENT_ID="lid")
            run("link", "001-0001")
            ok("link: a half-set LIBRARY_LINK_* pair falls back to the feedback pair", last()[1:3] == ("fid", "fsec"))

            lenv(**base)
            rc, o = run("link", fa)
            body = last()[3]
            ok("link: a filed PDF's path resolves to its document and follows the newest",
               rc == 0 and body["target"] == {"number": "001-0001", "rev": None})
            rc, o = run("link", fa, "--pin")
            ok("link: --pin on a path pins the revision the path is", rc == 0 and last()[3]["target"]["rev"] == "A")
            rc, o = run("link", "001-0001", "--pin")
            ok("link: --pin on a bare number pins its current revision",
               rc == 0 and last()[3]["target"] == {"number": "001-0001", "rev": revs[-1]["rev"]} and revs[-1]["rev"] == "B")
            cp = os.path.join(t, "copy.pdf")
            shutil.copy(fa, cp)
            rc, o = run("link", cp, "--pin")
            ok("link: a copy of a filed PDF elsewhere resolves by its bytes",
               rc == 0 and last()[3]["target"] == {"number": "001-0001", "rev": "A"})
            with open(built, "rb") as f1, open(fa, "rb") as f2:
                stamped = f1.read() != f2.read()
            rc, o = run("link", built, "--pin")
            ok("link: the PDF a session built and filed with a stamp resolves by its fingerprint from its build path",
               stamped and rc == 0 and last()[3]["target"] == {"number": "001-0001", "rev": "A"})
            n0 = len(Site.seen)
            # a revision filed with the old text-only print: a different drawing with the same words is not it
            twin = mkpdf(lsrc, "twin", "Link one\\par\\rule{6cm}{3cm}")
            reg = load()
            kept_fp = reg["documents"]["001-0001"]["revisions"][0]["fingerprint"]
            reg["documents"]["001-0001"]["revisions"][0]["fingerprint"] = textprint(pdftext(built))
            save(reg)
            rc, o = run("link", twin)
            reg = load()
            reg["documents"]["001-0001"]["revisions"][0]["fingerprint"] = kept_fp
            save(reg)
            ok("link: a different PDF with the same text as a text-only-print revision is not that document — "
               "refused, nothing sent",
               textprint(pdftext(twin)) == textprint(pdftext(built))
               and fingerprint(twin, pdftext(twin)) != fingerprint(built, pdftext(built))
               and rc == 1 and "is not filed" in o and len(Site.seen) == n0)
            loose = mkpdf(lsrc, "loose", "Never filed")
            rc, o = run("link", loose)
            ok("link: an unfiled PDF is refused, exit 1, nothing sent",
               rc == 1 and f"cc-docs: {loose} is not filed; file it first with `cc-docs file`" in o and len(Site.seen) == n0)
            rc1, o1 = run("link", "001-0009")
            rc2, o2 = run("link", "001-0001-C")
            ok("link: an unknown number or revision exits 1, nothing sent",
               rc1 == 1 and "no document 001-0009" in o1 and rc2 == 1 and "no revision C" in o2 and len(Site.seen) == n0)

            lenv(**base)
            Site.answer[0] = 404
            rc, o = run("link", "001-0001")
            ok("link: signed-in falls back to the document's page on a 404, with the reason, exit 0",
               rc == 0 and o.startswith(site + "/d/001-0001\n") and "does not know that document" in o)
            rc1, o1 = run("link", "001-0001", "--kind", "public")
            rc2, o2 = run("link", "001-0001", "--kind", "private", "--to", "ann@example.org")
            ok("link: public and private exit 1 on a 404, with no url",
               rc1 == 1 and rc2 == 1 and "/d/" not in o1 + o2 and "does not know that document" in o1)
            Site.answer[0] = 403
            rc, o = run("link", "001-0001-A", "--kind", "public")
            ok("link: a refused token exits 1 for public", rc == 1 and "refused the service token" in o)

            lenv(LIBRARY_URL=site)
            rc1, o1 = run("link", "001-0001")
            rc2, o2 = run("link", "001-0001", "--kind", "public")
            ok("link: with no service token signed-in gives the page, public exits 1, nothing sent",
               rc1 == 0 and o1.startswith(site + "/d/001-0001\n") and "no service token" in o1
               and rc2 == 1 and "no service token" in o2 and not Site.seen)
            lenv(LIBRARY_URL="http://127.0.0.1:1", LIBRARY_FEEDBACK_CLIENT_ID="fid", LIBRARY_FEEDBACK_CLIENT_SECRET="fsec")
            rc, o = run("link", "001-0001")
            ok("link: an unreachable site falls back for signed-in and never prints the secret",
               rc == 0 and o.startswith("http://127.0.0.1:1/d/001-0001\n") and "could not be reached" in o
               and "fsec" not in o)
            lenv(LIBRARY_FEEDBACK_CLIENT_ID="fid", LIBRARY_FEEDBACK_CLIENT_SECRET="fsec")
            rc1, o1 = run("link", "001-0001")
            rc2, o2 = run("link", "001-0001", "--kind", "public")
            ok("link: LIBRARY_URL unset exits 1 for every kind and says how to set it",
               rc1 == 1 and rc2 == 1 and "cc-config set LIBRARY_URL" in o1 and not Site.seen)
    finally:
        srv.shutdown()
        for k in lkeys:
            os.environ.pop(k, None)
    print(f"cc-docs selfcheck: {n[0]} passed, {n[1]} failed")
    return 1 if n[1] else 0
