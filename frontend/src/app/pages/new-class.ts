import { HttpErrorResponse } from '@angular/common/http';
import { Component, computed, inject, resource, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { Router } from '@angular/router';
import { Api } from '../api/api';
import {
  createClassApiClassesPost,
  linkTeamApiClassesLinkPost,
  ownedTeamsApiTeamsGet,
} from '../api/functions';
import { Candidate, Team } from '../api/models';
import { HomeStore } from '../shell/home-store';
import { Panel } from '../ui/panel';
import { StudentPicker } from './student-picker';

/** Makes a Class: a new Private team with the Students picked, or a team the Teacher owns. */
@Component({
  imports: [FormsModule, Panel, StudentPicker],
  templateUrl: './new-class.html',
  styleUrl: './new-class.css',
})
export class NewClass {
  private readonly api = inject(Api);
  private readonly home = inject(HomeStore);
  private readonly router = inject(Router);

  protected readonly teams = resource({ loader: () => this.api.invoke(ownedTeamsApiTeamsGet) });
  protected readonly name = signal('');
  protected readonly students = signal<Candidate[]>([]);
  protected readonly userIds = computed(() => this.students().map((s) => s.user_id));
  protected readonly busy = signal(false);
  protected readonly error = signal<string | null>(null);

  protected pick(c: Candidate): void {
    this.students.update((all) => [...all, c]);
  }

  protected drop(c: Candidate): void {
    this.students.update((all) => all.filter((s) => s.user_id !== c.user_id));
  }

  protected create(): Promise<void> {
    return this.open(() =>
      this.api.invoke(createClassApiClassesPost, {
        body: { name: this.name().trim(), student_user_ids: this.userIds() },
      }),
    );
  }

  protected link(team: Team): Promise<void> {
    return this.open(() =>
      this.api.invoke(linkTeamApiClassesLinkPost, { body: { team_id: team.id } }),
    );
  }

  /** Makes the Class, then shows it in the sidebar and opens it. */
  private async open(make: () => Promise<{ id: string }>): Promise<void> {
    this.busy.set(true);
    this.error.set(null);
    try {
      const made = await make();
      await this.home.refresh();
      await this.router.navigate(['/klasy', made.id]);
    } catch (e) {
      this.error.set(
        e instanceof HttpErrorResponse && e.status === 409
          ? 'Ten zespół jest już klasą.'
          : 'Nie udało się utworzyć klasy. Spróbuj jeszcze raz.',
      );
    } finally {
      this.busy.set(false);
    }
  }
}
