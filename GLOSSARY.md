# Classlop

A teacher's dashboard for orchestrating day-to-day teaching in a Polish school: classes, lessons, assignments, grading and progress, in one place instead of many. Students never use it directly; they work through Microsoft Teams.

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

**Attendance**:
The record of which students were present at a lesson, taken from Teams.
_Avoid_: Presence, register

**Note**:
A private remark the teacher keeps about a student.
_Avoid_: Comment, observation

### Curriculum

**Curriculum topic**:
One requirement of the mathematics podstawa programowa; the unit that items are tagged with and progress is measured in.
_Avoid_: Topic (unqualified), chapter, skill, standard

**Knowledge base**:
The books and curriculum documents the AI draws on when generating items and grading.
_Avoid_: RAG, library, sources

### Work

**Item**:
A single question or exercise, tagged with curriculum topics and worth a number of points.
_Avoid_: Task, question, exercise

**Assignment**:
A set of items given to a whole class or to selected students. Has a type: homework, quiz or exam.
_Avoid_: Task, test, worksheet

**Exam**:
An assignment of the exam type; not a separate concept.
_Avoid_: Test, sprawdzian (as a distinct entity)

**Submission**:
One student's completed work on one assignment, handed in through Teams or scanned from paper.
_Avoid_: Answer, hand-in, attempt

**Item bank**:
The teacher's searchable collection of reusable items.
_Avoid_: Question bank, task library

**Spot-check**:
The teacher reviewing a sample of AI-graded submissions rather than every one.
_Avoid_: Review, moderation
