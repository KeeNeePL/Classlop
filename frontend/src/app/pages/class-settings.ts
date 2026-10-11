import { HttpErrorResponse } from '@angular/common/http';
import { Component, computed, inject, linkedSignal, resource, signal } from '@angular/core';
import { toSignal } from '@angular/core/rxjs-interop';
import { FormsModule } from '@angular/forms';
import { ActivatedRoute, Router } from '@angular/router';
import { map } from 'rxjs';
import { Api } from '../api/api';
import {
  addStudentApiClassesClassIdStudentsPost,
  classSettingsApiClassesClassIdSettingsGet,
  deleteClassApiClassesClassIdDelete,
  removeStudentApiClassesClassIdStudentsStudentIdDelete,
  renameClassApiClassesClassIdPatch,
  restoreTeamApiClassesClassIdRestoreTeamPost,
} from '../api/functions';
import { Candidate, ClassSettings, Member } from '../api/models';
import { HomeStore } from '../shell/home-store';
import { Badge } from '../ui/badge';
import { Panel } from '../ui/panel';
import { ClassTimetable } from './class-timetable';
import { StudentPicker } from './student-picker';

/** The Class page's Ustawienia klasy tab: its name, its Students, its Timetable, and deleting it. */
@Component({
  imports: [Badge, ClassTimetable, FormsModule, Panel, StudentPicker],
  templateUrl: './class-settings.html',
  styleUrl: './class-settings.css',
})
export class ClassSettingsTab {
  private readonly api = inject(Api);
  private readonly home = inject(HomeStore);
  private readonly router = inject(Router);
  // The tab sits under `klasy/:klasa`, whose parameter its own route does not inherit.
  private readonly id = toSignal(
    inject(ActivatedRoute).parent!.paramMap.pipe(map((p) => p.get('klasa') ?? '')),
    { requireSync: true },
  );

  protected readonly settings = resource({
    params: () => this.id(),
    loader: ({ params }) =>
      this.api.invoke(classSettingsApiClassesClassIdSettingsGet, { class_id: params }),
  });
  protected readonly name = linkedSignal(() => this.settings.value()?.name ?? '');
  protected readonly typed = signal('');
  protected readonly busy = signal(false);
  protected readonly error = signal<string | null>(null);

  protected readonly readOnly = computed(() => this.settings.value()?.state !== 'active');
  /** Users who are Students now; a Former student can join again. */
  protected readonly current = computed(
    () =>
      this.settings
        .value()
        ?.students.filter((m) => !m.former)
        .map((m) => m.user_id) ?? [],
  );

  protected rename(s: ClassSettings): Promise<boolean> {
    return this.change(() =>
      this.api.invoke(renameClassApiClassesClassIdPatch, {
        class_id: s.id,
        body: { name: this.name().trim() },
      }),
    );
  }

  protected addStudent(c: Candidate): Promise<boolean> {
    return this.change(() =>
      this.api.invoke(addStudentApiClassesClassIdStudentsPost, {
        class_id: this.id(),
        body: { user_id: c.user_id },
      }),
    );
  }

  protected removeStudent(m: Member): Promise<boolean> {
    return this.change(() =>
      this.api.invoke(removeStudentApiClassesClassIdStudentsStudentIdDelete, {
        class_id: this.id(),
        student_id: m.id,
      }),
    );
  }

  protected restore(): Promise<boolean> {
    return this.change(() =>
      this.api.invoke(restoreTeamApiClassesClassIdRestoreTeamPost, { class_id: this.id() }),
    );
  }

  protected async remove(s: ClassSettings): Promise<void> {
    const deleted = await this.change(
      () =>
        this.api.invoke(deleteClassApiClassesClassIdDelete, {
          class_id: s.id,
          name: this.typed().trim(),
        }),
      false,
    );
    if (deleted) await this.router.navigate(['/']);
  }

  /** One change through `teams`; afterwards the tab and the sidebar show the Class as it now is. */
  private async change(change: () => Promise<unknown>, reload = true): Promise<boolean> {
    this.busy.set(true);
    this.error.set(null);
    try {
      await change();
      await this.home.refresh();
      if (reload) this.settings.reload();
      return true;
    } catch (e) {
      this.error.set(
        e instanceof HttpErrorResponse && e.status === 409
          ? 'Teams nie pozwala na tę zmianę. Odśwież stronę i sprawdź stan klasy.'
          : 'Nie udało się zapisać zmiany. Spróbuj jeszcze raz.',
      );
      return false;
    } finally {
      this.busy.set(false);
    }
  }
}
