/**
 * inbound-worker.js — the Cloudflare Email Worker that hands inbound mail to the box.
 *
 * STAGED, NOT DEPLOYED. Nothing on the box deploys this; the owner pastes it into the dashboard or runs
 * `wrangler deploy` himself. See docs/2026-09-08-email.md in the box's own (private) repo.
 *
 * What it does: takes the mail Email Routing gives it, POSTs the raw bytes to the receiver behind a
 * Cloudflare tunnel (`POST <BOX_URL>` with a bearer secret), reads the receiver's JSON answer, and — only if
 * that answer carries a `reply` string — mails that text back to the sender inside the same event.
 *
 * What it does NOT do: judge the sender. Email Routing has already rejected mail that fails both SPF and
 * DKIM and has already enforced the sender's DMARC policy before this worker is invoked
 * (developers.cloudflare.com/email-routing/postmaster/). This worker adds no verdict of its own. The verdict
 * travels in the mail's own Authentication-Results headers, which are part of the raw bytes, and the receiver
 * re-reads them there.
 *
 * THE OTHER DIRECTION, milestone 4: `fetch()` below is the box's way OUT. The box builds the whole RFC822
 * message itself (core/mail/outbound.py) and POSTs it here with the recipients listed explicitly; this worker
 * checks the secret, checks the From is on its own domain, and hands one EmailMessage per recipient to the
 * `send_email` binding. It never reads a recipient out of the message it was given, so nothing in a mail's
 * body or headers can add one. Cloudflare will only deliver to a destination address VERIFIED in the account
 * (developers.cloudflare.com/email-routing/email-workers/send-email/), and a refusal comes back to the box as
 * a named failure rather than a silent drop.
 *
 * Config (Workers → Settings):
 *   BOX_URL      var    — the tunnel hostname plus the path, e.g. https://<hostname>/inbound
 *   MAIL_SECRET  SECRET — must be a Wrangler *secret* (`wrangler secret put MAIL_SECRET`), never a var in
 *                         wrangler.toml: a var is plain text in the dashboard and in the repo, and this value
 *                         is the only thing that proves a caller is this worker.
 *   SEND_SECRET  SECRET — the other direction's lock: what proves a caller of `fetch()` is the box. A
 *                         DIFFERENT value from MAIL_SECRET on purpose — one secret doing both jobs means a
 *                         leak in either direction costs both.
 *   SEND_DOMAIN  var    — the box's mail domain. A From that is not on it is refused, so this worker can only
 *                         ever send AS the box and never as anybody else.
 *   SEND         send_email binding — `[[send_email]] name = "SEND"` in wrangler.toml. Without it `fetch()`
 *                         answers 503 and the box shows that in the thread.
 *   ACCESS_CLIENT_ID, ACCESS_CLIENT_SECRET
 *                SECRETs — optional, and recommended: a Cloudflare Access service token on the tunnel
 *                         hostname. With them set, Access turns away everything that is not this worker at
 *                         Cloudflare's edge, so the receiver's own checks are the second line and not the
 *                         first. Set both or neither. See docs/2026-09-08-email.md step 5.
 */
import { EmailMessage } from "cloudflare:email";

// The statuses that ARE the receiver answering — see "THE WIRE" at the top of core/mail/receiver.py. Anything
// else, and any answer that will not parse as the receiver's JSON, makes this Worker throw.
//
// WHAT A THROW BUYS, and it is the one thing this file leans on: an event that ends in an uncaught error has
// not accepted the mail, so the sending server has it still and retries — a mail delayed while somebody fixes
// BOX_URL or the tunnel, not a mail gone. Cloudflare's Email Workers docs do not spell the failure mode out
// (developers.cloudflare.com/email-routing/email-workers/ documents only `message.setReject()`, which is a
// PERMANENT SMTP error and is deliberately not used here). So the throw is the safe side of an unknown either
// way: at worst the sender gets a bounce and knows, where returning quietly loses the mail with no trace.
const FINAL = new Set([200, 400, 413, 429]);

export default {
  async email(message, env, ctx) {
    // The raw message, byte for byte. message.raw is a ReadableStream and message.rawSize is its length;
    // nothing here rewrites it, because the receiver re-reads the headers Cloudflare authenticated.
    const raw = new Uint8Array(await new Response(message.raw).arrayBuffer());

    let res;
    try {
      res = await fetch(env.BOX_URL, {
        method: "POST",
        headers: {
          "Authorization": `Bearer ${env.MAIL_SECRET}`,
          "Content-Type": "message/rfc822",
          "X-Mail-From": headerSafe(message.from),
          "X-Mail-To": headerSafe(message.to),
          // An Access service token, when the hostname has an Access policy on it. A Worker can send these
          // headers, which is what makes Access usable in front of a machine-to-machine call: there is no
          // browser sign-in anywhere in this path.
          ...(env.ACCESS_CLIENT_ID && env.ACCESS_CLIENT_SECRET ? {
            "CF-Access-Client-Id": env.ACCESS_CLIENT_ID,
            "CF-Access-Client-Secret": env.ACCESS_CLIENT_SECRET,
          } : {}),
        },
        body: raw,
      });
    } catch (err) {
      // The box is down, or the tunnel is. THROW: Cloudflare turns that into a temporary failure and the
      // sending server retries later, which is what you want with a real person's mail. Returning here would
      // accept the mail and drop it on the floor.
      throw new Error(`mail receiver unreachable: ${err}`);
    }

    // 503 is the receiver saying MAIL_SECRET is unset on the box, or that it is momentarily full; 5xx is it
    // being broken. All of them are ours to fix or to wait out, and all should retry rather than lose the
    // mail. 401 is the same case with a different cause: the two secrets disagree. Fix it and the retry lands.
    if (res.status === 401 || res.status >= 500) {
      throw new Error(`mail receiver refused the call: HTTP ${res.status}`);
    }
    // 403 is the receiver dropping the mail: an unknown sender, one nothing authenticated, or a verdict that
    // says fail. The mail is accepted and discarded and the sender learns NOTHING — no reply, no bounce, no
    // timing difference worth reading.
    // A 403 from in FRONT of the receiver is a different animal: Access turning away a wrong or expired
    // service token answers with HTML, not the receiver's JSON. Throwing on that retries the mail while the
    // token is fixed instead of discarding a real person's mail as if it came from a stranger.
    if (res.status === 403) {
      if (!(res.headers.get("content-type") || "").includes("application/json")) {
        throw new Error("403 from in front of the mail receiver (an Access token?), not from the receiver");
      }
      return;
    }

    // Everything left has to be the receiver's own answer, and FINAL is the whole set of them: 200 stored,
    // and the three refusals (400 malformed, 413 too big, 429 too many) it has already decided on. Any other
    // status came from something in FRONT of the receiver and settles nothing — a 404 is BOX_URL missing the
    // `/inbound` path, and a tunnel that is up with nothing behind it answers 502/530 with a page of its own.
    // Treating those as "stored" is how mail disappears: accepted from the sender, never written anywhere.
    if (!FINAL.has(res.status)) {
      throw new Error(`unexpected answer in front of the mail receiver: HTTP ${res.status}`);
    }

    let answer;
    try {
      answer = await res.json();
    } catch (err) {
      // A body that will not parse as JSON did not come from the receiver — an Access login page, an error
      // page — so nothing was stored and a retry cannot store it twice.
      throw new Error(`mail receiver answered HTTP ${res.status} with no usable JSON: ${err}`);
    }
    // Same reasoning one layer in: a 200 is only the receiver's if it says so.
    if (res.status === 200 && answer.status !== "stored") {
      throw new Error(`HTTP 200 that is not the mail receiver's: status=${JSON.stringify(answer.status)}`);
    }

    // 400/413/429 have already been answered by the receiver: the reason is in `reply` and goes back below.
    // `reply` null or absent means send nothing at all.
    const text = typeof answer.reply === "string" ? answer.reply.trim() : "";
    if (!text) return;

    // reply() rules, all four of them: it goes only to the sender of this message, it must come From an
    // address on the receiving domain, it may be called only once per event, and it needs a valid DMARC
    // result on the incoming mail. Any of those can make it throw at runtime — a mail forwarded through a
    // list, say — and a throw here would fail an event whose mail is already safely stored. So: catch, log,
    // return.
    try {
      await message.reply(buildReply(message, text));
    } catch (err) {
      console.log(`reply not sent (${answer.status}): ${err}`);
    }
  },

  /**
   * THE BOX'S WAY OUT (milestone 4). POST <worker>/send, Bearer SEND_SECRET, JSON:
   *   {"from": "<an address on SEND_DOMAIN>", "to": ["<recipient>", …], "raw": "<base64 RFC822>"}
   * Answers 200 {"ok":true,"sent":[…],"failed":[{"to":…,"error":…}]} or 4xx/503 {"ok":false,"error":…}.
   *
   * THE RECIPIENTS ARE THE ONES THE BOX NAMED, AND `raw` IS NEVER READ FOR ONE. The box has already narrowed
   * them to the addresses the original mail carried, so parsing To:/Cc: here would only be a second, weaker
   * chance to get it wrong — and a mail body that writes its own headers would then have a way out.
   *
   * A FAILURE PER RECIPIENT, NOT FOR THE CALL. `send_email` refuses an address the account has not verified,
   * and a mail to four people where one is unverified should still reach the other three; the refusal comes
   * back named, the box logs it and shows it in the thread, and nothing is dropped quietly.
   */
  async fetch(request, env) {
    const bad = (status, error) => new Response(JSON.stringify({ ok: false, error }), {
      status, headers: { "Content-Type": "application/json" },
    });
    if (new URL(request.url).pathname !== "/send") return bad(404, "not found");
    if (request.method !== "POST") return bad(405, "POST only");
    // The secret is the whole authentication. Compared without an early exit, so the answer's timing says
    // nothing about how much of a guess was right.
    const offered = (request.headers.get("authorization") || "").replace(/^Bearer\s+/i, "");
    if (!env.SEND_SECRET || !sameSecret(offered, env.SEND_SECRET)) return bad(401, "unauthorized");
    if (!env.SEND) return bad(503, "this worker has no send_email binding");

    let body;
    try {
      body = await request.json();
    } catch (err) {
      return bad(400, "the body is not JSON");
    }
    const from = typeof body?.from === "string" ? body.from.trim() : "";
    const domain = (env.SEND_DOMAIN || "").trim().toLowerCase();
    if (!domain) return bad(503, "SEND_DOMAIN is not set on this worker");
    // ONLY AS ITSELF, AND ONLY ONE ADDRESS. Cloudflare requires the From to be on a domain of this account;
    // checking it here as well turns a runtime throw into one refusal the box can show, and states the rule
    // where it is read. The SHAPE is checked exactly as a recipient's is, because `endsWith` alone takes
    // "attacker@evil.test, x@box.example" — a second address smuggled in front of ours ends on our domain
    // just as well: one local part, one @, and the domain that follows it is this one and nothing else.
    const fromOk = /^[^\s@<>,;:"]+@[^\s@<>,;:"]+$/.test(from)
      && from.slice(from.indexOf("@") + 1).toLowerCase() === domain;
    if (!fromOk) return bad(403, `From is not one address on ${domain}`);

    const to = Array.isArray(body?.to)
      ? body.to.map((a) => String(a || "").trim()).filter((a) => /^[^\s@<>,]+@[^\s@<>,]+$/.test(a))
      : [];
    if (!to.length) return bad(400, "no recipient");
    if (to.length > 20) return bad(400, "too many recipients");

    let raw;
    try {
      raw = atob(String(body?.raw || ""));
    } catch (err) {
      return bad(400, "raw is not base64");
    }
    if (!raw) return bad(400, "raw is empty");

    const sent = [], failed = [];
    for (const rcpt of to) {
      try {
        await env.SEND.send(new EmailMessage(from, rcpt, raw));
        sent.push(rcpt);
      } catch (err) {
        // The commonest one by far: a destination address nobody has verified in this account. It is the
        // owner's runbook step, not a bug, and it has to reach a person as words rather than as a lost mail.
        failed.push({ to: rcpt, error: String(err && err.message ? err.message : err).slice(0, 300) });
      }
    }
    return new Response(JSON.stringify({ ok: true, sent, failed }), {
      status: 200, headers: { "Content-Type": "application/json" },
    });
  },
};

// Equal-length, no early exit. Two strings of different lengths are not equal and that much the timing may say.
function sameSecret(a, b) {
  if (a.length !== b.length) return false;
  let diff = 0;
  for (let i = 0; i < a.length; i++) diff |= a.charCodeAt(i) ^ b.charCodeAt(i);
  return diff === 0;
}

// Anything that came off the incoming mail is attacker-controlled. A CR or an LF in it would end the header
// and start one of the sender's choosing, so they never survive into a header line.
function headerSafe(value) {
  return String(value ?? "").replace(/[\r\n]+/g, " ").trim();
}

// The reply MIME, built by hand — a Worker has no mail library and needs none for nine headers.
function buildReply(message, text) {
  const from = headerSafe(message.to);     // the address the mail was sent TO: the receiving domain's
  const to = headerSafe(message.from);     // the sender, and only the sender
  const domain = from.split("@").pop();
  const subject = headerSafe(message.headers.get("subject"));
  const messageId = headerSafe(message.headers.get("message-id"));
  const references = headerSafe(message.headers.get("references"));

  const headers = [
    `From: ${from}`,
    `To: ${to}`,
    // Re: once, not Re: Re: — a thread that has been round twice already carries the prefix.
    `Subject: ${/^re:/i.test(subject) ? subject : `Re: ${subject}`}`,
    `Date: ${new Date().toUTCString()}`,
    `Message-ID: <${crypto.randomUUID()}@${domain}>`,
  ];
  // Without these two the reply opens a new thread in the sender's client instead of landing under theirs.
  if (messageId) {
    headers.push(`In-Reply-To: ${messageId}`);
    headers.push(`References: ${references ? `${references} ${messageId}` : messageId}`);
  }
  headers.push("MIME-Version: 1.0");
  headers.push("Content-Type: text/plain; charset=utf-8");

  const body = text.replace(/\r?\n/g, "\r\n");
  return new EmailMessage(from, to, `${headers.join("\r\n")}\r\n\r\n${body}\r\n`);
}
