# Smoke test: fallback Teams path on the demo tenant

Issue #44. Run 2026-10-09 against the Business Basic demo tenant with the invented Teacher and a Student, signed in through the device-code flow (delegated tokens, app «Classlop dev»). Folder and file names below are throwaway.

## Setup findings

- User consent is disabled in the tenant: every delegated scope needed an admin grant, including user-consentable ones. The app registration needs `Files.ReadWrite.All` on top of what `scripts/setup-demo-tenant.sh` grants (`Files.Read.All`), or `invite`, uploads and permission changes fail.
- `GET /me/drive/sharedWithMe` returns 401 for the Student. Address the shared folder by `driveId` and item id instead.

## 2. Hand-ins seen by delta: holds

A Student upload into a folder shared with `invite` (role `write`, `sendInvitation: false`) appeared in `GET /me/drive/root/delta` on the Teacher's drive, using a `token=latest` baseline taken before the invite.

- `createdBy.user` carries the Student's `email`, `id` and `displayName`. `createdBy.application` is «Microsoft Graph»: the upload went through the API, so a Student using the OneDrive app or Teams may show a different application.
- `createdDateTime` is set by the server and matched the Student's upload time to the second.
- The invite appeared in delta as the folder item; the upload appeared a few seconds later.

No fallback to polling the folder's children is needed.

## Revoking uploads: holds

`PATCH /me/drive/items/{id}/permissions/{permissionId}` with `{"roles": ["read"]}` returned 200. A Student upload attempted about ten seconds later returned 403 `accessDenied`.

## 1. Attendance per occurrence: not yet run

Blocked. Neither the Teacher nor the Student has a working mailbox: `GET /me/calendar` returns an empty 401 and Outlook on the web fails with `CannotResolveExternalDirectoryOrganizationIdException`, although `EXCHANGE_S_STANDARD` shows `Success` in the licence details. `POST /me/events` needs a mailbox, so the recurring-event check cannot start.

To run once mailboxes work: create a short recurring event with `isOnlineMeeting` and `teamsForBusiness`, compare `joinUrl` across `instances`, look the meeting up with `/me/onlineMeetings?$filter=JoinWebUrl eq '...'`, then have people join two occurrences and read `attendanceReports`.

## 3. Uploading from Teams: not yet run

Needs a person with the Teams desktop and mobile apps: open the folder link as the Student from a 1:1 chat and upload a photo and a PDF.
