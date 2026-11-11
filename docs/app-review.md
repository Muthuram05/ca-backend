# Meta App Review submission

Draft text for the three permissions Reel DM Automation needs, plus the screencast
reviewers watch and the steps they follow. Paste each section into the matching box in
App Review; keep the wording specific, because vague answers are the usual rejection.

App: StillTyping (`1681235963510378`) · Dashboard: https://automation.stilltyping.in

## Permissions requested

### instagram_basic

> After a creator connects their Instagram professional account, the app reads the
> account's username, name and profile picture so the dashboard can show which account is
> signed in, and lists that account's reels and posts so the creator can choose which one
> an automation applies to. Without this permission the creator cannot confirm which
> account they connected, and cannot pick a post for an automation.

Endpoints: `GET /{ig-user-id}?fields=id,username,name,profile_picture_url`,
`GET /{ig-user-id}/media`.

### instagram_manage_comments

> The app subscribes to the `comments` webhook field for the connected account. When
> someone comments on one of that account's reels or posts, the app matches the comment
> text against the keywords the creator configured. If the creator turned on the optional
> public reply, the app posts one reply under that comment. Without this permission the
> app cannot see the comment that triggers the automation, and cannot post the public
> acknowledgement creators ask for.

Endpoints: webhook field `comments`, `POST /{comment-id}/replies`.

### instagram_manage_messages

> This is the app's core function. When a comment matches a keyword, the app sends one
> private reply to the person who commented, containing the message the creator wrote —
> usually a link they promised in the reel. Creators otherwise answer the same "link pls"
> comment by hand dozens of times a day. Each comment is answered exactly once, enforced
> by a unique key in the database. Without this permission the app cannot send anything.

Endpoint: `POST /{ig-user-id}/messages` with `recipient.comment_id`.

## Steps for the reviewer

1. Open https://automation.stilltyping.in and select **Log in with Instagram**.
2. Connect an Instagram professional (Business or Creator) account.
3. Under **New automation**, leave *All reels & posts* selected, enter the keyword
   `link`, write any DM message, and select **Create automation**.
4. From a second Instagram account, comment `link pls` on any reel of the connected
   account.
5. Within a few seconds the second account receives the DM. It appears under **Requests**
   if that account does not follow the connected one.
6. The dashboard's **Recent activity** shows the comment and a **Sent** status.

**Test a comment** on the dashboard runs step 4 as a dry run, matching the comment and
showing the DM that would be sent without sending anything.

## Screencast shot list

One continuous recording is better than cuts; reviewers look for the permission being
exercised, not production value.

1. The logged-out page, then **Log in with Instagram** and the asset selection dialog.
2. The dashboard after login: the username, profile picture and the grid of reels.
   *(instagram_basic)*
3. Creating an automation with the keyword and message.
4. A phone screen: the second account posting `link pls` on a reel.
5. The dashboard's Recent activity showing **Sent**. *(instagram_manage_comments —
   the comment was received)*
6. The second account's inbox, opening the DM that arrived. *(instagram_manage_messages)*
7. If the public reply is enabled, the reply visible under the comment on the reel.
   *(instagram_manage_comments — the reply was posted)*

## Where the submission stands (2026-11-11)

Business verification: **approved**. Tech Provider: **confirmed** (one-way door; the app
stayed Published through it). The submission itself is started but not sent — Meta no
longer lets you edit or cancel a submission once it is in review, so it goes in complete.

Done in the dashboard:

- The request was trimmed to the four permissions the app actually uses:
  `instagram_basic`, `instagram_manage_comments`, `instagram_manage_messages`,
  `public_profile`. `ads_management`, `ads_read` and `instagram_content_publish` were
  removed — Meta now reviews the whole app, and asking for permissions with no
  demonstrated use invites rejection. They are still on the app, just not under review.
- A **Website** platform was added (`https://automation.stilltyping.in/`); reviewer
  instructions cannot be written until a platform exists.
- The platform's testing instructions carry the steps from this file.

The per-permission descriptions in *Permissions requested* above are entered and saved
under **Allowed usage** for `instagram_basic`, `instagram_manage_comments` and
`instagram_manage_messages`.

Still open, in the submission's own checklist:

- **Each permission's compliance checkbox** ("I agree that any data I receive through X
  will be used in accordance with the allowed usage"). These are commitments the account
  holder makes, not something to delegate.
- **Screencast**, uploaded per permission — the same recording can serve all three.
- **API test calls**: Meta shows `0 of 1` for `instagram_basic` and
  `instagram_manage_comments` even though the live app has made these calls. Its own note
  says testing data can take up to 24 hours to appear, so check again tomorrow before
  using the Testing tool to force it.
- `instagram_manage_messages` carries extra requirements depending on whether data is
  processed for other businesses or only your own — read "View requirements" on that
  permission before submitting.

- **Allowed usage** and **Data handling** — certifications about how the app uses
  permissions and handles data. Worth answering from the facts: tokens are encrypted at
  rest with Fernet, the activity log is deleted after 90 days, and the only data leaving
  Meta's APIs is what the README's models describe.
- **Reviewer instructions** — still flagged; this is where the screencast attaches.

## Before submitting
- A reviewer logs in with **their own** Instagram account, not `stilltyping.ai`. Confirm
  that the account discovery in `app/instagram.py` finds an account other than the one in
  `IG_USER_ID` — see *Finding the account* in the README. A reviewer who cannot log in is
  an automatic rejection.

---

# Record of everything entered in the Meta dashboard

Written 2026-11-11. Submission id `1684047033229271`. Nothing has been submitted.

## App settings → Basic

| Field | Value |
| --- | --- |
| Category | Messaging |
| Privacy Policy URL | `https://automation.stilltyping.in/privacy` |
| Terms of Service URL | `https://automation.stilltyping.in/terms` |
| App icon | the three-dot StillTyping mark, 1024x1024 PNG |
| Platform | **Website**, Site URL `https://automation.stilltyping.in/` |

## App settings → Basic → Website → testing instructions

| Field | Value |
| --- | --- |
| Where can we find the app? | `https://automation.stilltyping.in/` |
| Instructions for accessing the app | the six numbered steps from *Steps for the reviewer* above, plus the note that the app is free and the "Test a comment" dry run |
| Is Facebook Login integrated on this platform? | **Yes** |
| Access codes / test credentials | "No payment or membership is required. Every feature is available for free once an Instagram professional account is connected through Facebook Login for Business, so no access codes or test credentials are needed." |
| Geographic restrictions | "There are no geographic restrictions… no geo-blocking or geo-fencing." |

## App Review → permissions requested

Kept: `instagram_basic`, `instagram_manage_comments`, `instagram_manage_messages`,
`public_profile`. Removed from the submission (still on the app):
`ads_management`, `ads_read`, `instagram_content_publish`.

## App Review → Allowed usage

The description box for each of `instagram_basic`, `instagram_manage_comments` and
`instagram_manage_messages` holds the wording from *Permissions requested* at the top of
this file. `public_profile` has no description box.

## App Review → Data handling

| Question | Answer |
| --- | --- |
| processor-0 — do you have data processors? | **Yes** |
| processor-2 — Supabase | category *IT solutions and services, including cloud storage and processing*; countries **India, United States of America** |
| processor-2 — Render | same category; country **United States of America** |
| processor-2 — Netlify | same category; country **United States of America** |
| responsible-1 — entity responsible for Platform Data | **Zeen Labs** |
| responsible-2 — country of that entity | **India** |
| requests-3 — data given to public authorities under national security requests in 12 months | **No** |
| requests-4 — policies for public-authority requests | **None of the above** |

Why those countries: the Supabase project is in **Mumbai (ap-south-1)**, with the United
States added because Supabase Inc. can reach the infrastructure remotely; the Render
service runs in **Oregon (US West)**; Netlify is US-based and proxies `/api`, `/auth`,
`/webhook` and `/healthz` through to Render, so Platform Data passes through it.

**Check requests-4 before submitting.** "None of the above" is the honest answer for a
business with no legal function, but it is a statement about Zeen Labs, not about the
code.

## Still to do, and only you can do it

1. The four **"I agree … in accordance with the allowed usage"** checkboxes, one per
   permission under Allowed usage.
2. The **screencast**, uploaded against `instagram_basic`,
   `instagram_manage_comments` and `instagram_manage_messages`.
3. The **API test-call counters**, which read `0 of 1` for `instagram_basic` and
   `instagram_manage_comments` despite the live app having made those calls. Meta says
   testing data can take 24 hours to appear.
