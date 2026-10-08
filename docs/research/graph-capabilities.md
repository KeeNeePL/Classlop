# What Microsoft Graph exposes for Classes, Assignments, Submissions and Lessons

Research for issue #3. Sources read on 2026-10-08; all are Microsoft Learn or other Microsoft first-party pages unless marked. Terms follow `GLOSSARY.md`.

## Answer

- **Create today:** an **Office 365 A1 Education trial** tenant, signed up by the Teams area owner at microsoft.com/education/products/office with a school email address. Of the options below, only this one is an Education tenant you can get by tomorrow. The trial can be used straight away, before Microsoft has verified the school ([1]). Give it a timebox: if it has not produced a tenant where you are Global Admin within about an hour, fall back.
- **What an Education tenant gives you:** the whole Assignment lifecycle through Graph. You can create an Assignment for a whole Class or for selected Students, publish it, read each Submission and its attached files, write points and feedback, and return it. Classes and their Students can be read through Graph. Each of these permissions needs admin consent once.
- **Lessons and Attendance do not need an Education tenant.** Creating Teams meetings and reading their attendance reports works on any tenant with Teams. Signed in as the Teacher (delegated), it needs no admin consent and no extra Teams admin policy.
- **Not by tomorrow:** the official EDU developer tenant and the demo EDU tenant both need a Microsoft Partner Network ID, and the developer one has no stated turnaround ([7], [8]). The Microsoft 365 Developer Program sandbox is instant only for eligible members (Visual Studio Professional/Enterprise subscribers, certain partners, Premier/Unified customers). It is an E5 tenant, not an Education tenant ([5]).
- **Fallback:** a Microsoft 365 for business 30-day trial (25 licences, ready in minutes; [6]). On it, Lessons and Attendance work unchanged. Classes become ordinary Teams/groups. Assignments must be faked: post a channel message, Students upload files to a folder in the team's Files, Classlop reads those files. Without the Education API there is no per-Student Submission status, no due dates, and no grades that Students see in Teams.

## 1. Which tenant to create

| Option | Education tenant? | Ready by 2026-10-09? | Gate |
| --- | --- | --- | --- |
| Office 365 A1 Education trial | Yes | Likely, if sign-up accepts the email | You need a school email. The trial can be used before verification ([1]). |
| EDU developer tenant (Partner Sign Up) | Yes | No | Needs an MPN ID; you only get "an email notification" with no SLA ([7]) |
| Demo EDU tenant (CDX) | Yes | Instant for "Quick tenant" | Needs an MPN ID; "You must not use a demo EDU tenant for development purposes" ([8]) |
| M365 Developer Program E5 sandbox | No | Instant, if eligible | Eligibility paths only; needs an active MCA billing account with an Azure subscription ([5]) |
| Microsoft 365 for business trial | No | Yes, minutes | 30 days, 25 licences, 300 GB ([6]) |

How the A1 trial works:

- To get the trial: "visit https://www.microsoft.com/education/products/office, enter your school email address, and select Get started." The trial shows up as "Office 365 A1 for faculty Trial" and "Office 365 A1 for students Trial" ([1]).
- On verification timing: "In most cases, you receive immediate approval or denial of your school's eligibility. In some cases, we require more information to complete a manual eligibility review ... This review can take up to 10 business days" ([1]). The marketing page gives a looser outer bound: "may take up to a month" ([2]).
- **On whether you can start before verification:** "You can close the academic verification wizard before you enter a domain and start using the trial subscription right away. However, you aren't eligible for academic prices until you complete the verification process. You must complete the process before the end of your free trial to convert to a paid subscription" ([1]). The trial lasts 30 days ([2]) and can be extended once ([1]). That covers a hackathon.
- A1 includes Teams for Education ([3]). Microsoft Teams is "part of the free Microsoft 365 A1 for Students SKU" ([4]).
- Risk (not verified for this team): "A domain can't be used across more than one tenant" ([9]). If the school email's domain already belongs to a school's Microsoft 365 tenant, the sign-up is likely to route you into that tenant as an ordinary user. You would then have no admin rights to consent to permissions. Use an address whose domain has no tenant, or fall back.

The Developer Program sandbox is not a shortcut. It is an E5 tenant ([5]), and Microsoft's own path for building education solutions is an EDU tenant: "To implement and test your education solutions, you need to set up a demo developer tenant" ([10]).

## 2. Classes and Students (roster)

- Read a Class: `GET /education/me/taughtClasses` lists the Teacher's Classes. `GET /education/classes/{id}/members` lists its members. Both use delegated `EduRoster.ReadBasic` or application `EduRoster.Read.All`. With a delegated token, "users can only see information about their own classes" ([11], [12]).
- `educationUser.primaryRole` is `student`, `teacher`, `none` or `unknownFutureValue`. With delegated scopes, Graph returns only a limited property set (id, primaryRole, names, UPN and a few others) ([13]).
- Create a Class: `POST /education/classes` is **application-only** (`EduRoster.ReadWrite.All`). It "only creates the universal group and doesn't create a team" ([14]). For the demo, it is simpler to create the class team in the Teams client. The Graph team template `educationClass` pins the Assignments app and forces HiddenMembership ([15]).
- Assignments exist only inside class teams: "Assignments is only available in class teams" ([16]).

## 3. Assignments and Submissions

All endpoints below are v1.0, global cloud only ([17]).

| Step | Endpoint | Delegated | Application |
| --- | --- | --- | --- |
| Create (draft) | `POST /education/classes/{id}/assignments` | EduAssignments.ReadWriteBasic | EduAssignments.ReadWriteBasic.All |
| Attach Item files | `POST .../assignments/{id}/resources` | EduAssignments.ReadWriteBasic | EduAssignments.ReadWriteBasic.All |
| Upload folder for Item files | `POST .../assignments/{id}/setUpResourcesFolder` gives a SharePoint folder | EduAssignments.ReadWrite | EduAssignments.ReadWrite.All |
| Publish | `POST .../assignments/{id}/publish` | EduAssignments.ReadWriteBasic | EduAssignments.ReadWriteBasic.All |
| List Submissions | `GET .../assignments/{id}/submissions?$expand=outcomes,submittedResources` | EduAssignments.ReadBasic | EduAssignments.ReadBasic.All |
| Read attachments | `GET .../submissions/{id}/resources` | EduAssignments.ReadBasic | EduAssignments.ReadBasic.All |
| Grade and feedback | `PATCH .../submissions/{id}/outcomes/{id}` | EduAssignments.ReadWrite | EduAssignments.ReadWrite.All |
| Return | `POST .../submissions/{id}/return` | EduAssignments.ReadWrite | EduAssignments.ReadWrite.All |
| Reassign | `POST .../submissions/{id}/reassign` | EduAssignments.ReadWrite | EduAssignments.ReadWrite.All |
| Poll changes | `GET /education/classes/{id}/getRecentlyModifiedSubmissions`, assignment `delta` | EduAssignments.Read | EduAssignments.Read.All |

Sources: [18], [19], [20], [21], [22], [23], [24], [25], [37], [38].

Facts the design depends on:

- **Whole Class or selected Students.** `assignTo` takes `educationAssignmentClassRecipient` (the whole Class) or `educationAssignmentIndividualRecipient` with a `recipients` list of user IDs ("selected students in the class will receive a submission object when the assignment is published") ([17], [26]). This matches the glossary's Assignment.
- **Draft vs published.** A new Assignment is a draft that Students can't see. Publishing creates one `educationSubmission` per Student, and "The status of the assignment goes back to `draft` if there is any backend failure during publish" ([17], [19]). Status can't be changed with PATCH ([17]).
- **Only teachers can call these in delegated mode.** Create and publish are teacher-only ("Only teachers in a class can create an assignment"; "Only a teacher in the class can make this call"). Return, reassign and outcome updates are also teacher-only ([18], [19], [23], [24], [21]). Classlop must therefore sign in as the Teacher, or use application permissions.
- **Attachments.** A Submission's `resources` are the working copy and `submittedResources` are what was handed in. File resources carry a `fileUrl` that points at a Graph `drives/{id}/items/{id}` item ([20]). Downloading the bytes is a normal drive item read. Inference, not verified: that read probably also needs a Files permission.
- **Points.** Grading uses `educationAssignmentPointsGradeType` with `maxPoints`. Outcomes include `educationPointsOutcome` and `educationFeedbackOutcome`, each with a draft value and a published value that the Student sees after return ([18], [21]).
- **Storage.** Student files live in the class team's SharePoint "Student Work" library. Grades, feedback and assignment details live outside SharePoint ([27]).

## 4. Lessons and Attendance

| Step | Endpoint | Delegated | Application |
| --- | --- | --- | --- |
| Create a Lesson meeting | `POST /me/onlineMeetings` | OnlineMeetings.ReadWrite | not supported on `/me` |
| ... as app for a user | `POST /users/{id}/onlineMeetings` | OnlineMeetings.ReadWrite | OnlineMeetings.ReadWrite.All + access policy |
| Find a meeting by join link | `GET /me/onlineMeetings?$filter=JoinWebUrl eq '...'` | OnlineMeetings.Read | OnlineMeetings.Read.All (on `/users/{id}`) |
| List attendance reports | `GET /me/onlineMeetings/{id}/attendanceReports` | OnlineMeetingArtifact.Read.All | OnlineMeetingArtifact.Read.All + access policy |

Sources: [28], [29], [30].

- `POST /onlineMeetings` creates a standalone meeting that "aren't shown on the user's calendar". A calendar-backed Lesson needs the Create event API (`isOnlineMeeting`) instead ([28]).
- "Each time an online meeting ... ends, an attendance report is generated for that session". The list returns "only up to 50 of the most recent reports". **attendanceRecords is empty in the list response**, so you must GET each report to get its records ([30]).
- Each `attendanceRecord` has `emailAddress`, `identity`, `role` (`Attendee`/`Presenter`/`Organizer`), `totalAttendanceInSeconds` and `attendanceIntervals` (join/leave periods) ([31]). That is enough to derive Attendance per Student.
- Online meetings expire 60 days after start or end unless they are updated ([32]).
- **App-only needs a Teams admin step.** An admin must create and grant an application access policy with `New-CsApplicationAccessPolicy` and `Grant-CsApplicationAccessPolicy`. Changes "can take up to 30 minutes" to apply, and without it the call fails with "No application access policy found for this app" ([33]). Signing in as the Teacher (delegated) avoids this.
- Online meetings are standard Teams. Nothing in these pages is education-specific, so this section works on any tenant with Teams licences.

## 5. Admin consent

Taken from the Graph permissions reference ([34]). Application permissions always need admin consent.

| Permission | Delegated: admin consent? |
| --- | --- |
| EduRoster.ReadBasic | Yes |
| EduAssignments.ReadWriteBasic | Yes |
| EduAssignments.ReadWrite | Yes |
| OnlineMeetings.ReadWrite | No |
| OnlineMeetingArtifact.Read.All | No |
| Calendars.ReadWrite | No |
| Files.Read.All | No |
| GroupMember.Read.All | Yes |

- For the demo tenant this is a one-time click by the team's Global Admin. The Education docs give the admin-consent URL `GET https://login.microsoftonline.com/{tenant}/adminconsent?client_id=...` ([35]).
- Implication for the product, not acted on here: in a real school, school IT would have to consent to the Edu permissions.

**Recommended mode for the hackathon: delegated, signed in as the Teacher.** It meets the teacher-only rules, needs no application access policy, and keeps meeting permissions consent-free.

## 6. Fallback on a non-Education tenant

What still works unchanged: Lessons, Attendance, calendar events and files.

What changes:

- **Class** becomes an ordinary team or Microsoft 365 group. **Students** come from `GET /groups/{id}/members` (`GroupMember.ReadBasic.All`, delegated or application) ([36]).
- **Assignment** has no Graph object. Post it as a channel message with the Items attached or linked from the team's Files.
- **Submission** means each Student uploads a file to a per-Assignment folder in the team's Files. Classlop lists and downloads those files and maps uploader to Student.
- What is lost: Submission objects and their states (working/submitted/returned), due dates and late rules, Teams notifications, and grades and feedback shown to Students inside Teams. Feedback would have to go back by chat or channel message.
- Keep Assignment I/O behind one interface. Then the Education API and the files fallback can be swapped without touching the grading pipeline.

Not verified: whether `/education/*` calls return data or errors on a non-Education tenant. Microsoft documents no supported path for that, and Assignments needs a class team ([10], [16]). Assume it is unavailable.

## 7. Smoke test to run today on the A1 tenant (about 30 minutes)

1. Create a Teacher account and two invented Student accounts, for example `teacher.demo@` and `student.a@`. Assign A1 licences with Teams enabled ([4]).
2. As the Teacher, create a Class team in the Teams client ("Class" type) and add both Students.
3. In Graph Explorer as the Teacher, consent `EduRoster.ReadBasic` and `EduAssignments.ReadWrite`. Then call `GET /education/me/taughtClasses` and note the class id.
4. Run `POST /education/classes/{id}/assignments` with a points grade, then `POST .../publish`. As a Student, hand in a file in Teams. Then `GET .../submissions?$expand=submittedResources,outcomes`.
5. Run `POST /me/onlineMeetings`, join as a Student, leave, then `GET .../attendanceReports/{reportId}`.

If step 3 or 4 fails, switch to the fallback the same day.

## Sources

1. Verify eligibility for Microsoft 365 Education subscriptions: https://learn.microsoft.com/en-us/microsoft-365/commerce/subscriptions/verify-academic-eligibility
2. Office 365 Education (product page): https://www.microsoft.com/en-us/education/products/office
3. Office 365 Education service description: https://learn.microsoft.com/en-us/office365/servicedescriptions/office-365-platform-service-description/office-365-education
4. Assign Microsoft Teams licenses for education: https://learn.microsoft.com/en-us/microsoftteams/teams-edu-licensing
5. Microsoft 365 Developer Program FAQ (updated 2026-09-08): https://learn.microsoft.com/en-us/office/developer-program/microsoft-365-developer-program-faq
6. Try or buy a Microsoft 365 for business subscription: https://learn.microsoft.com/en-us/microsoft-365/commerce/try-or-buy-microsoft-365
7. Set up a demo tenant to develop education solutions: https://learn.microsoft.com/en-us/graph/msgraph-onboarding-devtenant
8. Set up a demo education tenant: https://learn.microsoft.com/en-us/graph/msgraph-onboarding-edutenant
9. Tenant setup for Microsoft 365 for education baseline: https://learn.microsoft.com/en-us/microsoft-365/education/guide/0-start-baseline/start-setup
10. Set up an EDU development environment: https://learn.microsoft.com/en-us/graph/msgraph-onboarding-overview
11. List educationUser taughtClasses: https://learn.microsoft.com/en-us/graph/api/educationuser-list-taughtclasses
12. List members of an educationClass: https://learn.microsoft.com/en-us/graph/api/educationclass-list-members
13. educationUser resource: https://learn.microsoft.com/en-us/graph/api/resources/educationuser
14. Create educationClass: https://learn.microsoft.com/en-us/graph/api/educationclass-post
15. Team templates with Microsoft Graph: https://learn.microsoft.com/en-us/microsoftteams/get-started-with-teams-templates
16. Create an assignment in Microsoft Teams (support): https://support.microsoft.com/en-us/education/create-an-assignment-in-microsoft-teams
17. educationAssignment resource: https://learn.microsoft.com/en-us/graph/api/resources/educationassignment
18. Create educationAssignment: https://learn.microsoft.com/en-us/graph/api/educationclass-post-assignments
19. educationAssignment: publish: https://learn.microsoft.com/en-us/graph/api/educationassignment-publish
20. List submission resources: https://learn.microsoft.com/en-us/graph/api/educationsubmission-list-resources
21. Update educationOutcome: https://learn.microsoft.com/en-us/graph/api/educationoutcome-update
22. List submissions: https://learn.microsoft.com/en-us/graph/api/educationassignment-list-submissions
23. educationSubmission: return: https://learn.microsoft.com/en-us/graph/api/educationsubmission-return
24. educationSubmission: reassign: https://learn.microsoft.com/en-us/graph/api/educationsubmission-reassign
25. educationClass: getRecentlyModifiedSubmissions: https://learn.microsoft.com/en-us/graph/api/educationclass-getrecentlymodifiedsubmissions
26. educationAssignmentIndividualRecipient: https://learn.microsoft.com/en-us/graph/api/resources/educationassignmentindividualrecipient
27. Assignments for Teams (admin): https://learn.microsoft.com/en-us/microsoftteams/expand-teams-across-your-org/assignments-in-teams
28. Create onlineMeeting: https://learn.microsoft.com/en-us/graph/api/application-post-onlinemeetings
29. Get onlineMeeting: https://learn.microsoft.com/en-us/graph/api/onlinemeeting-get
30. List meetingAttendanceReports: https://learn.microsoft.com/en-us/graph/api/meetingattendancereport-list
31. attendanceRecord resource: https://learn.microsoft.com/en-us/graph/api/resources/attendancerecord
32. onlineMeeting resource: https://learn.microsoft.com/en-us/graph/api/resources/onlinemeeting
33. Configure an application access policy: https://learn.microsoft.com/en-us/graph/cloud-communication-online-meeting-application-access-policy
34. Microsoft Graph permissions reference: https://learn.microsoft.com/en-us/graph/permissions-reference
35. Working with education APIs: https://learn.microsoft.com/en-us/graph/api/resources/education-overview
36. List group members: https://learn.microsoft.com/en-us/graph/api/group-list-members
37. Create educationAssignmentResource: https://learn.microsoft.com/en-us/graph/api/educationassignment-post-resources
38. educationAssignment: setUpResourcesFolder: https://learn.microsoft.com/en-us/graph/api/educationassignment-setupresourcesfolder
