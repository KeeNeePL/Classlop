# Smoke test: fallback Teams path on the demo tenant

Issue #44. Run 2026-10-09 and 2026-10-10 against the Business Basic demo tenant with the invented Teacher and one Student. Every finding below is a response observed on the tenant unless it says otherwise; Graph error messages are quoted where they are the source.

## Summary

| Question | Result |
|---|---|
| 1. Attendance per occurrence | Recurring calendar events untested (no mailboxes). Attendance works through call records instead, which needs app-only access. |
| 2. Submissions seen by delta | Holds. |
| Revoking uploads with `PATCH` to `read` | Holds. |
| 3. Uploading from Teams | Does not hold: the link leaves Teams. The fallback applies: Students upload in the browser. |

## 1. Attendance per occurrence

### Recurring calendar events: not run

Neither the Teacher nor the Student has a working mailbox: `GET /me/calendar` returns an empty 401, and Outlook on the web fails with `CannotResolveExternalDirectoryOrganizationIdException`, although `EXCHANGE_S_STANDARD` shows `Success` in the licence details and the admin center says the mailbox is being prepared. `POST /me/events` needs a mailbox, so the shared-`joinUrl` and per-occurrence report questions remain open.

### Standalone meetings

`POST /me/onlineMeetings` works without a mailbox and returns a `joinWebUrl`. `GET /me/onlineMeetings?$filter=JoinWebUrl eq '...'` finds the meeting; filtering on `subject` fails with «Only 'JoinWebUrl' and 'joinMeetingId' (nested under 'joinMeetingIdSettings') are supported».

`GET /me/onlineMeetings/{id}/attendanceReports` returns 404 `SDS_ErrorInvalidUser` on both `/me` and `/users/{id}`, for meetings that ended minutes and hours earlier. The cause is not established; the missing mailbox is the leading suspect.

### Call records: hold

`GET /communications/callRecords` with the application permission `CallRecords.Read.All` (client-credentials token, so the app needs a secret) works without a mailbox.

- Filter the list with `startDateTime ge ...` and match a Lesson by the record's `joinWebUrl`.
- `participants_v2` names each signed-in participant (`identity.user` with `id`, `displayName`, `userPrincipalName`); `sessions` give each participant's join and leave times. The Student's `id` matches `createdBy.user.id` from their Submission in the delta below.
- A Student who leaves and rejoins while others stay has several `sessions` in one record; merge them per Student.
- A meeting that empties and later fills again produces a second record with the same `joinWebUrl` (seen once, when the Teacher rejoined seven minutes after everyone had left). Attendance for a Lesson is therefore all records with its `joinWebUrl`, merged.
- A record appeared 27 minutes after the meeting ended (measured once, polling every 30 s), so Attendance is not available straight after a Lesson.
- A Student who joined from the raw link in a browser with no Teams session was asked for a name and shows up as `identity.guest` («Guest user», no UPN): an Unmatched attendee. The same Student joining from the link posted in the Class channel, signed in to Teams on the web, shows up as `identity.user`. Students must join from inside Teams, signed in.

App-only access departs from the design so far, where Classlop signs in as the Teacher with delegated permissions only; it needs its own decision.

### Posting the Lesson link to the Class

A meeting made with `POST /me/onlineMeetings` is not tied to the Class's team. With delegated `ChannelMessage.Send` and `Channel.ReadBasic.All`, `GET /teams/{id}/primaryChannel` and `POST /teams/{id}/channels/{id}/messages` posted the join link to the Class channel. A channel meeting proper was not tried; it is made as a group calendar event, which presumably meets the same mailbox problem.

## 2. Submissions seen by delta: holds

A Student upload into a folder shared with `invite` (role `write`, `sendInvitation: false`) appears in `GET /me/drive/root/delta` on the Teacher's drive, read from a `token=latest` baseline taken before the invite.

- `createdBy.user` carries the Student's `email`, `id` and `displayName`.
- `createdDateTime` is set by the server and matched the upload time to the second.
- `createdBy.application` is «Microsoft Graph» for an API upload and «SharePoint Online Client Extensibility» for a browser upload.

No fallback to polling each folder's children is needed.

## Revoking uploads: holds

`PATCH /me/drive/items/{id}/permissions/{permissionId}` with `{"roles": ["read"]}` returned 200, and a Student upload about ten seconds later returned 403 `accessDenied`.

## 3. Uploading from Teams: does not hold, fallback applies

The Teacher sent the folder's `webUrl` in a 1:1 Teams chat. In the Teams mobile app the link opened in an external browser, where the Student uploaded a photo and a PDF. On the desktop the Student opened the link in a browser and uploaded an image; opening it from the Teams desktop app was not tried. All three files reached the Teacher's delta as in section 2.

The folder never opens inside Teams, so the chat message that gives an Assignment should tell Students the link opens in their browser or the OneDrive app.

## Tenant setup

- User consent is disabled: every delegated permission needed an admin grant, including user-consentable ones.
- The app registration needs `Files.ReadWrite.All` beyond the `Files.Read.All` that `scripts/setup-demo-tenant.sh` grants, or `invite`, uploads and permission changes fail; plus `ChannelMessage.Send` and `Channel.ReadBasic.All` for channel posts, and the application permission `CallRecords.Read.All` with a client secret for call records.
- `GET /me/drive/sharedWithMe` returns 401 for the Student; address the shared folder by `driveId` and item id.
- Security defaults began rejecting the device-code flow with `AADSTS530035` («Access has been blocked by security defaults»), including refreshes of an earlier device-code token, once MFA was set up. The authorization code flow with PKCE and the registered `http://localhost` redirect works.
