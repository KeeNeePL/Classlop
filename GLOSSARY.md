# Classlop

A teacher's dashboard for orchestrating day-to-day teaching in a Polish liceum: classes, lessons, assignments, grading and progress, in one place instead of many. Students never use it directly; they work through Microsoft Teams.

## Language

### Teaching

**Teacher**:
The single user of the dashboard; the person who teaches the classes in it.
_Avoid_: User, admin

**Class**:
A group of students the teacher teaches; each gets its own tab in the dashboard.
_Avoid_: Course, group, team

**Student**:
A member of a class. Interacts only through Teams, never with the dashboard.
_Avoid_: Pupil, learner

**Lesson**:
One scheduled online Teams meeting of a class.
_Avoid_: Meeting, session, class (a class is the group, never the meeting)

**Lesson topic**:
The teacher's title for what a lesson covers, as written in the school register (temat lekcji).
_Avoid_: Topic (unqualified), temat, subject

**Timetable**:
The weekly recurring slots in which a class has its lessons.
_Avoid_: Schedule, plan, series

**Attendance**:
Each student's state at one lesson, Present, Late or Absent, derived from Teams and overridable by the teacher.
_Avoid_: Presence, register

**Late**:
The attendance state of a student whose first join came after the lesson's scheduled start plus the lateness threshold.
_Avoid_: Tardy, delayed

**Unmatched attendee**:
Someone in a lesson's Teams attendance who is not yet linked to a student of the class.
_Avoid_: Guest, unknown user

**Note**:
A private remark the teacher keeps about a student.
_Avoid_: Comment, observation

### Curriculum

**Curriculum topic**:
One requirement of the liceum mathematics podstawa programowa at basic level; the unit that items are tagged with and progress is measured in.
_Avoid_: Topic (unqualified), chapter, skill, standard

**Curriculum section**:
One of the numbered sections of the podstawa programowa (I. Liczby rzeczywiste, ...), grouping curriculum topics.
_Avoid_: Chapter, unit, dział (except as the UI label)

**General requirement**:
One of the four general requirements of the podstawa programowa (I computation, II using information, III representations, IV reasoning); the kind of thinking an item demands.
_Avoid_: Skill, competence, ability

**Difficulty**:
How hard an item or exemplar is: easy, medium or hard.
_Avoid_: Level (ambiguous with basic and extended level)

**Exemplar**:
An existing exercise in the knowledge base, tagged like an item, that the AI uses as a model when generating items. Never given to students.
_Avoid_: Example, source task, template

**Knowledge base**:
The material the AI draws on when generating items and grading: exemplars from ZPE e-materials and CKE papers, and the podstawa programowa.
_Avoid_: RAG, library, sources

### Work

**Item**:
A single question or exercise, tagged with curriculum topics and worth a number of points.
_Avoid_: Task, question, exercise

**Item format**:
How an item is answered: closed (choosing from given options) or open (a written answer or solution).
_Avoid_: Item type, question type (type belongs to assignments)

**Model solution**:
The worked solution stored with an item, which grading compares a student's work against. Never shown to students.
_Avoid_: Answer key, reference solution

**Rubric**:
The CKE-style scoring scheme of an item: which stages of a solution earn which points.
_Avoid_: Marking scheme, criteria, klucz

**Generation request**:
The teacher asking the AI for new items, in their own words in a chat or by generating the shortfall in Nowa praca; the AI needs difficulty, item format and count, and may take curriculum topics.
_Avoid_: Prompt, generation prompt, query

**Assignment**:
A set of items given to a whole class or to selected students. Has a type: homework, quiz or exam.
_Avoid_: Task, test, worksheet

**Exam**:
An assignment of the exam type; not a separate concept.
_Avoid_: Test, sprawdzian (as a distinct entity)

**Given**:
Said of an assignment once Teams has accepted its publication, now or at a scheduled time; from then on its items are frozen.
_Avoid_: Sent, assigned, published (Teams' own term)

**Submission**:
One student's completed work on one assignment, handed in through Teams or scanned from paper.
_Avoid_: Answer, hand-in, attempt

**Late submission**:
A submission handed in after the assignment's due time but before it closes.
_Avoid_: Late (that is an attendance state), overdue

**Missing**:
The state of a submission never handed in by the time its assignment closes.
_Avoid_: Absent, not submitted, overdue

**Excused**:
The state of a submission the teacher has released the student from; it never counts in results.
_Avoid_: Exempt, skipped

**Transcription**:
The AI's verbatim reading of a student's work on one item, mistakes included.
_Avoid_: OCR, reading, odczyt (except as the UI label)

**Held**:
Said of a graded submission that is not returned until the teacher approves it, because one of its items is unreadable, unsure or in doubt; a condition, not a submission state.
_Avoid_: Blocked, pending, on hold

**Override**:
The teacher replacing the AI's points on one item of a submission.
_Avoid_: Correction, regrade, manual grade

**Feedback**:
The written comment a student receives on a submission once it is returned: points and a short remark on each item, in Polish.
_Avoid_: Comment, remark, review

**Item bank**:
The teacher's searchable collection of reusable items.
_Avoid_: Question bank, task library

**Chat**:
One named conversation with Classlop AI in which the teacher adds items to the item bank, by generation requests or item uploads; kept in the teacher's chat history.
_Avoid_: Conversation, thread, session, rozmowa

**Item upload**:
The teacher adding their own exercises to the item bank from a file, split into one item per exercise.
_Avoid_: Import

**Extraction**:
The AI's reading of one exercise from an item upload into an item's text; the teacher checks it against the crop of the page when the AI is unsure.
_Avoid_: Transcription (that is a student's work), OCR

**Flagged item**:
An item the AI marks for the teacher's attention, such as one with no exemplar or one that kept failing the tag check; it stays usable until the teacher edits it or dismisses the flag.
_Avoid_: Unreviewed item, draft

**Retired item**:
An item the teacher has withdrawn from the item bank; never offered for new assignments, kept in the assignments that used it, and restorable.
_Avoid_: Deleted item, archived item

**Spot-check**:
The teacher reviewing the AI-graded submissions flagged for it, the held ones and those with geometry, rather than every one.
_Avoid_: Review, moderation

### Reports

**Progress**:
The share of available points a student or class has earned on graded items tagged with one curriculum topic or curriculum section; missing and excused submissions are left out.
_Avoid_: Mastery, score (unqualified), level

**Assignment summary**:
The teacher's view of how a class did on one assignment: results per student, submission states, and how each item went.
_Avoid_: Report (unqualified), statistics

**Suggested grade**:
The school grade (1 to 6) that a submission's percentage maps to under the teacher's thresholds; shown only to the teacher, who enters grades in the e-gradebook by hand.
_Avoid_: Grade (unqualified), ocena, mark

**Class overview**:
The teacher's view of one class: its progress, its assignments and the students needing attention.
_Avoid_: Teacher overview, dashboard

**Student report**:
The teacher's view of one student over a chosen period, also downloadable for parent meetings.
_Avoid_: Report card, świadectwo, student detail
