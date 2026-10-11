"""The one read of a Class that Reports and Do zrobienia make, against the real area over FakeGraph
and against FakeTeams."""

from datetime import timedelta

from tenant import PDF, make_class, spec


async def test_one_read_gives_the_class_with_its_students_work_and_lessons(tenant, gave, clock):
    klass, users = await make_class(tenant, "Jan Kowalski", "Ewa Zielinska", "Adam Lis")
    given = await tenant.give_assignment(klass.id, spec(), PDF)
    start = clock.now + timedelta(hours=1)
    lesson = await tenant.add_lesson(klass.id, start, start + timedelta(minutes=45), "Funkcje")
    tenant.attend(
        lesson.join_url,
        [(users["Jan Kowalski"], "Jan Kowalski", start, start + timedelta(minutes=40))],
    )
    clock.advance(hours=2)
    await tenant.refresh_attendance(klass.id, lesson.id)
    tenant.upload(users["Ewa Zielinska"], "strona-1.jpg", b"page one")
    clock.advance(minutes=4)
    await tenant.poll_handins()
    await tenant.remove_student(klass.id, users["Adam Lis"])

    read = await tenant.read_class(klass.id)

    assert read.klass == klass
    students = {s.display_name: s for s in read.students}
    assert set(students) == {"Jan Kowalski", "Ewa Zielinska", "Adam Lis"}
    assert students["Adam Lis"].former_since is not None
    assert read.assignments == [await tenant.get_assignment(given.id)]
    states = {s.student_id: s.state for s in read.submissions}
    assert states == {
        students["Jan Kowalski"].id: "not_handed_in",
        students["Ewa Zielinska"].id: "handed_in",
        students["Adam Lis"].id: "not_handed_in",
    }
    assert [x.id for x in read.lessons] == [lesson.id]
    attendance = {e.student_id: e.state for e in read.attendance[lesson.id].entries}
    assert attendance[students["Jan Kowalski"].id] == "present"
    assert attendance[students["Ewa Zielinska"].id] == "absent"


async def test_a_lesson_still_to_come_has_no_attendance_in_the_read(tenant, clock):
    klass, _ = await make_class(tenant, "Jan Kowalski")
    start = clock.now + timedelta(days=1)
    lesson = await tenant.add_lesson(klass.id, start, start + timedelta(minutes=45), "Funkcje")

    read = await tenant.read_class(klass.id)

    assert [x.id for x in read.lessons] == [lesson.id]
    assert read.attendance == {}
