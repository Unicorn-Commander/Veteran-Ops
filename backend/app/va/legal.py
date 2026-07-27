"""Terms of use + privacy policy served at GET /api/legal.

These are a VA Lighthouse PRODUCTION-ACCESS prerequisite (VA reviews an app's
terms and privacy policy before granting prod credentials), and they must stay
consistent with the legal lane in docs/BUILD-SPEC.md: self-help educational
software, the veteran always drives, no sale of veteran data, ever.

Plain language on purpose — veterans should be able to read these without a
lawyer. Keep the app name in sync with settings.app_name usage elsewhere.
"""

from __future__ import annotations

TERMS_MD = """\
# Terms of Use — Veteran-Ops

_Last updated: July 5, 2026_

## What Veteran-Ops is (and isn't)

Veteran-Ops is **self-help educational software**. It helps you organize your
own VA disability compensation claim: your conditions, your evidence, your
deadlines, and what the rating criteria actually say.

Veteran-Ops is **not**:

- legal advice, or a substitute for it;
- a VA-accredited representative, agent, or attorney (38 CFR §14.629);
- affiliated with, or endorsed by, the U.S. Department of Veterans Affairs.

**You always drive.** Veteran-Ops never files a claim, submits a form, or
changes anything in a VA system on its own. The few features that can send
something to VA (like recording an Intent to File) run only on your own
VA.gov-consented sign-in, only when you explicitly confirm the specific action,
and do exactly what you could do yourself on VA.gov.

**Free help exists.** VA-accredited Veterans Service Officers (VSOs) — VFW,
DAV, The American Legion, and your state or county veterans office — will help
you prepare and file for free. We link to them throughout the app and encourage
you to use them.

## No guarantees about outcomes

Rating criteria, presumptive lists, and VA processes change. We work to keep
our reference material current and every AI answer cites its source, but you
should verify anything that matters at eCFR or VA.gov. Nothing in this app is a
promise about what rating you will receive.

## Your account and your responsibilities

- You must provide accurate information — the app organizes what you give it.
- Keep your login credentials to yourself; you are responsible for activity on
  your account.
- Don't use the app to violate the law or someone else's rights, or attempt to
  access another person's data.

## Connecting your VA account

If you choose to connect VA services, you sign in **at VA.gov** (via Login.gov
or ID.me) and consent there. We never see your VA.gov password. You can revoke
the connection at any time — in this app (Settings → Disconnect) or from your
VA.gov connected-apps page — and revoking stops our access immediately.

## Termination and changes

You can stop using Rating Raider and delete your account and data at any time.
We may update these terms; material changes will be shown in the app before
they take effect.

## Liability

The app is provided "as is." To the maximum extent permitted by law, we are not
liable for indirect or consequential damages arising from use of the app. This
does not limit anything that cannot be limited by law.
"""

PRIVACY_MD = """\
# Privacy Policy — Veteran-Ops

_Last updated: July 5, 2026_

## The short version

- Your data is stored **on your behalf**, to run the features you use. It is
  yours, not ours.
- **We never sell veteran data. Ever.** Not to advertisers, not to lead
  generators, not to "partners," not in aggregate, not anonymized. There is no
  version of this product where your claim data is the product.
- You can download a portable archive of your account data and retained uploaded
  originals, or delete your account data, whenever you want.

## What we store

- **Account basics:** your email, name, and password hash.
- **What you enter:** your service history, exposures, conditions, evidence
  checklist, saved rating scenarios, and notes.
- **Documents you upload:** files, the text we extract from them, and the
  summaries generated for you.
- **VA-connection data (only if you connect):** the access tokens VA issues for
  your consented sign-in, and the service-history, rating, and claim-status
  records you pull. Tokens are stored isolated to your account and are never
  written to logs.
- **An audit trail:** a record of actions taken in your account (like "Intent
  to File recorded"), so you can always see what the software did on your
  instruction.

## How your data is protected

Every record is keyed to your account and enforced with database row-level
security — one account cannot read another's rows, even if application code has
a bug. AI features run on locally hosted models by default; your documents and
personal data are not sent to third-party AI providers unless you deliberately
opt in.

## The VA connection is yours

Connecting VA services happens **at VA.gov** with your Login.gov or ID.me
sign-in. We never receive your VA.gov password. VA shows you exactly which
scopes you are granting. Nothing we hold is written back to VA without your
explicit, per-action confirmation, and you can revoke access at any time in
this app or at VA.gov — revocation cuts off our access immediately.

## What we share

Nothing, except:

- **Service providers we run on** (our own hosting infrastructure) — your data
  passes through them only to operate the app.
- **If you ask us to** — e.g., a feature you invoke that sends a request to VA
  on your consented token.
- **If the law compels us** — and then only the minimum required.

No advertising networks. No data brokers. No analytics companies receiving your
claim data.

## Your rights

- **Access & export:** you can view and download your data.
- **Deletion:** you can delete individual records or your entire account. On
  account deletion we remove your data from live systems promptly and from
  backups on their normal rotation.
- **Revocation:** disconnecting VA revokes our tokens with VA (best effort) and
  deletes them locally either way.

## Questions

Contact the operator at the address shown on the app's About page. If we change
this policy in any meaningful way, you'll see it in the app first.
"""
