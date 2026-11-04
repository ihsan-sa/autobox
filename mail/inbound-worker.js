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
 *   SEND_CALLERS var    — optional: a comma list of other callers of `fetch()`, such as ALPHA,BETA: letters, digits
 *                         and underscores, because a name with a hyphen is ignored. Each one holds its
 *                         own lock and may send only as itself, to its own list:
 *   SEND_SECRET_<NAME> SECRET — that caller's bearer. Delete it to revoke that caller alone.
 *   SEND_FROM_<NAME>   var    — its one From, on SEND_DOMAIN. Unset, it can send nothing.
 *   SEND_TO_<NAME>     var    — a comma list of the exact recipients it may name. Unset, it can send nothing.
 *   SEND_NAME_<NAME>   var    — optional: the one display name its From may show. Unset, it shows none.
 *   SEND_CAP_<NAME>    var    — how many recipients it may send to per UTC day. Unset, it can send nothing.
 *   SEND_COUNTS  Durable Object binding, class SendCount — where those day counts live. Without it no caller
 *                         can send; the box can. It needs a migration: docs/2026-09-08-email.md step 4.
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

// All a caller's message may carry at its top level. A list of what is allowed rather than of what is not, because
// clients answer to more headers than anyone lists (Mail-Reply-To, Errors-To, Disposition-Notification-To…), and an
// outside address in one of them is a way to draw an answer away from the caller's own address.
const CALLER_HEADERS = new Set(["from", "to", "cc", "reply-to", "subject", "date", "message-id", "in-reply-to",
  "references", "mime-version", "content-type", "content-transfer-encoding"]);
// And the only types its message may be at the top level. A wrapped message or a digest can show a From of its own.
const CALLER_TYPES = new Set(["text/plain", "text/html", "multipart/mixed", "multipart/alternative", "multipart/related"]);

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
   *
   * A CALLER THAT IS NOT THE BOX (SEND_CALLERS) is held to its own From and recipients, and here `raw` IS read:
   * the reader sees the From inside the message, not the envelope's, so a caller could otherwise keep its own
   * envelope and show anyone's name. Recipients still never come out of `raw`. See callerRefusal.
   */
  async fetch(request, env) {
    const bad = (status, error) => new Response(JSON.stringify({ ok: false, error }), {
      status, headers: { "Content-Type": "application/json" },
    });
    if (new URL(request.url).pathname !== "/send") return bad(404, "not found");
    if (request.method !== "POST") return bad(405, "POST only");
    // The secret is the whole authentication. Compared without an early exit, so the answer's timing says
    // nothing about how much of a guess was right, or about whose it was.
    const offered = (request.headers.get("authorization") || "").replace(/^Bearer\s+/i, "");
    const caller = whoIsCalling(offered, env);
    if (!caller) return bad(401, "unauthorized");
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

    // All or nothing: a caller naming one address it may not use sends to none of them.
    if (caller.name) {
      const refusal = callerRefusal(caller.name, from, to, raw, env);
      if (refusal) return bad(403, refusal);
      const over = await capRefusal(caller.name, to.length, env);
      if (over) return bad(over.status, over.error);
    }

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

// Who holds the offered secret: {box: true}, {name} for a SEND_CALLERS entry, or null. Every secret is compared
// whatever an earlier one answered. A listed caller with no secret set matches nothing, which is how it is revoked.
function whoIsCalling(offered, env) {
  let who = null;
  for (const name of commaList(env.SEND_CALLERS).filter((n) => /^\w+$/.test(n))) {
    const secret = env[`SEND_SECRET_${name}`];
    if (secret && sameSecret(offered, secret) && !who) who = { name };
  }
  if (env.SEND_SECRET && sameSecret(offered, env.SEND_SECRET)) who = { box: true };
  return who;
}

function commaList(value) {
  return String(value || "").split(",").map((s) => s.trim()).filter(Boolean);
}

// Why this caller may not send this, or null. Each limit fails closed: a var that is not set allows nothing.
function callerRefusal(name, from, to, raw, env) {
  const own = String(env[`SEND_FROM_${name}`] || "").trim();
  if (!own || from !== own) return `${name} may only send from its own address`;
  const allowed = commaList(env[`SEND_TO_${name}`]);
  const stranger = to.find((a) => !allowed.includes(a));
  if (stranger) return `${name} may not send to ${stranger}`;
  return headerRefusal(raw, own, String(env[`SEND_NAME_${name}`] || "").trim(), allowed);
}

// One count per caller per UTC day, taken before the send and never handed back, so a failed send still counts:
// the point is that one caller cannot spend what the account shares. A KV counter would not hold this, because its
// reads may be stale. SendCount holds each caller's count in one object.
async function capRefusal(name, count, env) {
  const cap = Number(env[`SEND_CAP_${name}`]);
  if (!Number.isInteger(cap) || cap < 1) return { status: 403, error: `${name} has no send cap set` };
  if (!env.SEND_COUNTS) return { status: 503, error: "this worker has no SEND_COUNTS binding" };
  const day = new Date().toISOString().slice(0, 10);
  try {
    const counter = env.SEND_COUNTS.get(env.SEND_COUNTS.idFromName(name));
    const res = await counter.fetch("https://send-count/take", {
      method: "POST", body: JSON.stringify({ day, count, cap }),
    });
    if (res.status === 200) return null;
    if (res.status === 429) return { status: 429, error: `${name} has reached its ${cap} recipients for today` };
  } catch (err) {
    console.log(`send count failed for ${name}: ${err}`);
  }
  return { status: 503, error: `${name}'s send count could not be updated, so nothing was sent` };
}

// A Durable Object takes one event at a time across a storage call (its input gate), so nothing can come between the
// get and the put below. Don't put another kind of await between them, because that opens the gate.
export class SendCount {
  constructor(state) {
    this.storage = state.storage;
  }

  async fetch(request) {
    const { day, count, cap } = await request.json();
    const held = await this.storage.get("count");
    // A call that set out before midnight and arrives after it counts against the newer day and never resets it.
    const current = held && held.day >= day ? held : { day, used: 0 };
    if (current.used + count > cap) return new Response("over", { status: 429 });
    await this.storage.put("count", { day: current.day, used: current.used + count });
    return new Response("ok");
  }
}

// The type alone: comments out (they nest, and may hold a `;`), then what comes before the parameters. Anything left
// that isn't exactly a type, such as a space around the slash, then matches nothing on the list.
function contentType(value) {
  let text = value, before;
  do {
    before = text;
    text = text.replace(/\([^()]*\)/g, "");
  } while (text !== before);
  return text.split(";")[0].trim().toLowerCase();
}

// The message's own headers must show exactly one From, and that From is `own`, under the one display name it
// was given if it shows one. A Reply-To must lead back to `own`. This reads strictly, and refuses
// what mail parsers disagree on, because the parser that matters is the reader's and not this one: a message that
// mixes line endings has two possible header blocks, and only one of them would have been checked here.
function headerRefusal(raw, own, ownName, allowed) {
  const crlf = raw.includes("\r");
  const end = raw.indexOf(crlf ? "\r\n\r\n" : "\n\n");
  if (end < 0) return "the message's headers do not end in a blank line";
  const block = raw.slice(0, end);
  if (crlf && /\r(?!\n)|(?<!\r)\n/.test(block)) return "the message's headers mix line endings";
  // raw is bytes here, so this also catches a NEL or any other multibyte character. An encoded word is plain ASCII.
  if (/[^\t\r\n\x20-\x7e]/.test(block)) return "the message's headers must be plain ASCII";

  const froms = [], replyTos = [];
  for (const line of block.replace(/\r?\n[ \t]+/g, " ").split(/\r?\n/)) {
    const m = line.match(/^([\x21-\x39\x3b-\x7e]+)[ \t]*:(.*)$/);
    if (!m) return "the message has a line in its headers that is not a header";
    const header = m[1].toLowerCase();
    if (!CALLER_HEADERS.has(header)) return `the message may not carry ${m[1]}`;
    if (header === "from") froms.push(m[2].trim());
    if (header === "reply-to") replyTos.push(m[2].trim());
    if (header === "content-type" && !CALLER_TYPES.has(contentType(m[2]))) return "the message's Content-Type is not one a caller may use";
    // A reply-all goes to whoever these show, so they hold the caller and its recipients and nobody else.
    if ((header === "to" || header === "cc") && !m[2].split(",").every((item) => {
      const shown = item.trim().match(/^(?:[^<>@,;:"()]*<)?([^\s<>@,;:"()]+@[^\s<>@,;:"()]+)(>?)$/);
      return shown && (shown[2] === ">") === item.includes("<") && (shown[1] === own || allowed.includes(shown[1]));
    })) return `the message's ${m[1]} may only show ${own} and its allowed recipients`;
  }
  if (froms.length !== 1) return "the message must carry exactly one From";

  // `Name <addr>` or the bare address, and the name can only be the one this caller was given: a free choice of
  // plain words would still let it show a person's name over its own address.
  const named = froms[0].match(/^([^<>]*)<([^<>]*)>$/);
  const addr = named ? named[2] : froms[0];
  const shown = named ? named[1].trim().replace(/^"(.*)"$/, "$1") : "";
  if (addr !== own || (shown && shown !== ownName)) return `the message's From must be ${own} under its own name`;

  // An answer has to come back to this caller: its own address, or its own +tag on it (what a cold mail carries).
  if (replyTos.length > 1) return "the message may carry only one Reply-To";
  if (replyTos.length) {
    const at = own.lastIndexOf("@");
    const value = replyTos[0].replace(/^<(.*)>$/, "$1");
    const tag = value.startsWith(own.slice(0, at) + "+") && value.endsWith(own.slice(at))
      ? value.slice(at + 1, value.length - (own.length - at)) : null;
    if (value !== own && !(tag && /^[A-Za-z0-9._-]+$/.test(tag))) return `the message's Reply-To must lead to ${own}`;
  }
  return null;
}

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
