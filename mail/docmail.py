"""`cc-mail doc` — one library document mailed to a verified address, laid out by a template the owner can swap.

THE TEMPLATE IS A FILE, NOT CODE (owner, 2026-09-29: the look comes from a template he makes later).
`library-document.html` and `library-document.txt` are read from MAIL_DOC_TEMPLATES (default ~/.cc/mail/templates)
when they are there, each on its own, and otherwise from core/templates/mail/ beside this tree, the plain default.
Dropping a file into that directory is the whole swap. A template may use {{title}}, {{number}}, {{project}},
{{date}}, {{link}} and {{note}}; any other {{name}} refuses the mail by name, so a typo is never sent. In the HTML
every value is escaped.

THE DOCUMENT GOES AS ITS LIBRARY LINK, never as a file, the way a PDF handed to `cc-mail send` does (#772):
`cc-docs link <number>` with outbound.link_kind's flags, private to every recipient who is not the owner. A
revision (PPP-NNNN-R) links that revision; a bare PPP-NNNN links the document.

NOTHING HERE SENDS. `compose` runs send_to's recipient gate (outbound.cold_gate, the verified list among it), a
look at the caps and both templates BEFORE a link is asked for, so no link names an address that is not on the owner's
list or is minted for a mail a bad template would refuse, and returns the subject, text and HTML for cc-mail to hand
to outbound.send_to, whose list, caps and log are the same as every other mail's."""
import html as H
import json
import os
import re

import outbound

HERE = os.path.dirname(os.path.realpath(__file__))
DEFAULTS = os.path.join(os.path.dirname(HERE), "templates", "mail")
NAME = "library-document"
FIELDS = ("title", "number", "project", "date", "link", "note")
SLOT = re.compile(r"\{\{\s*([A-Za-z_]+)\s*\}\}")
NUM = re.compile(r"^(\d{3}-\d{4})(?:-([A-HJ-NP-Z]{1,3}))?$")


def template_dir(cfg):
    return os.path.expanduser((cfg.get("MAIL_DOC_TEMPLATES") or "").strip() or os.path.join(outbound.H, ".cc", "mail", "templates"))


def template(cfg, ext):
    """(text, None) of the .html or .txt template, the owner's when his directory has one, else the default; or
    (None, why) when neither is there, it cannot be read as UTF-8 or it names a field that does not exist."""
    for d in (template_dir(cfg), DEFAULTS):
        p = os.path.join(d, NAME + "." + ext)
        if os.path.isfile(p):
            try:
                with open(p, encoding="utf-8") as f:
                    text = f.read()
            except (OSError, ValueError) as e:
                return None, "cannot read the template %s (%s)" % (p, outbound.clip(str(e)))
            why = unknown(text)
            return (None, why) if why else (text, None)
    return None, "no template %s.%s in %s or %s" % (NAME, ext, template_dir(cfg), DEFAULTS)


def unknown(text):
    """None, or a str naming the first {{name}} in the template that is not one of FIELDS."""
    odd = sorted({m.group(1) for m in SLOT.finditer(text)} - set(FIELDS))
    if odd:
        return "the template uses {{%s}}, which is not one of {{%s}}" % (odd[0], "}}, {{".join(FIELDS))
    return None


def render(text, fields, escape):
    """The template with each {{name}} filled, or a str saying which name it does not know."""
    why = unknown(text)
    if why:
        return None, why

    def fill(m):
        v = fields.get(m.group(1), "")
        return H.escape(v).replace("\n", "<br>\n") if escape else v
    return SLOT.sub(fill, text), None


def document(number, root=None):
    """(fields, None) for PPP-NNNN or PPP-NNNN-R out of the register, or (None, why)."""
    m = NUM.match(number or "")
    if not m:
        return None, "%r is not a document number like PPP-NNNN or PPP-NNNN-R" % number
    root = root or os.environ.get("CC_DOCS_ROOT") or os.path.join(outbound.H, ".cc", "documents")
    try:
        with open(os.path.join(root, "register.json"), encoding="utf-8") as f:
            reg = json.load(f)
    except (OSError, ValueError) as e:
        return None, "cannot read the library's register (%s)" % e
    d = reg.get("documents", {}).get(m.group(1))
    revs = (d or {}).get("revisions") or []
    rev = next((r for r in revs if r.get("rev") == m.group(2)), None) if m.group(2) else (revs[-1] if revs else None)
    if not rev:
        return None, "no document %s in the library" % number
    date = rev.get("date") or ""
    try:
        y, mo, dd = (int(x) for x in date.split("-"))
        if not 1 <= mo <= 12:
            raise ValueError(mo)
        date = "%d %s %d" % (dd, "Jan Feb Mar Apr May Jun Jul Aug Sep Oct Nov Dec".split()[mo - 1], y)
    except ValueError:                       # not a Y-M-D date: the register's own text stands
        pass
    proj = reg.get("projects", {}).get(d.get("project"), {})
    return {"title": d.get("title") or number, "number": "%s-%s" % (m.group(1), rev.get("rev")),
            "project": proj.get("name") or d.get("project") or "", "date": date}, None


def compose(cfg, number, to, subject="", note="", run=None, channel=""):
    """(subject, text, html) for mailing `number` to `to`, or a str saying why it may not go. Before anything else
    the mail passes send_to's own recipient gate (outbound.cold_gate: an address off the verified list, no sending
    configured, no From), a look at the caps that charges nothing, as pdf_links does, the document and both templates,
    so no link is minted for a mail that will not go: a private link grants the document whether or not the mail goes."""
    rcpts, _blind, _from, why = outbound.cold_gate(cfg, to, None, channel)
    why = why or outbound.caps(cfg, outbound.COLD_KEY, rcpts, charge=False)
    if why:
        return why
    fields, why = document(number)
    if why:
        return why
    (h, why), (t, why2) = template(cfg, "html"), template(cfg, "txt")
    if why or why2:
        return why or why2
    exe = outbound.docs_bin()
    run = run or __import__("subprocess").run
    try:
        r = run([exe, "link", number] + outbound.link_kind(cfg, rcpts), capture_output=True, text=True,
                timeout=60)
    except Exception as e:
        return "the library did not answer for %s's link (%s)" % (number, outbound.clip(str(e)))
    out = (r.stdout or "").strip().splitlines()
    if r.returncode != 0 or len(out) != 1 or not re.fullmatch(r"https?://\S+", out[0].strip()):
        return ((r.stderr or "").strip().splitlines() or ["cc-docs link exit %d" % r.returncode])[-1]
    fields.update(link=out[0].strip(), note=(note or "").strip())
    html, why = render(h, fields, True)
    if why:
        return why
    text, why = render(t, fields, False)
    if why:
        return why
    return (subject or "").strip() or fields["title"], text.strip() + "\n", html
