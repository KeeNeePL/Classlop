import { Component, ElementRef, computed, input, output, signal, viewChild } from '@angular/core';
import { CurriculumSection } from '../api/models';
import { MathText } from '../ui/math';

/** The Curriculum in a pop-up over the screen, where the Teacher ticks any number of topics. The
 * pop-up stays open while they do; it fits the screen and scrolls down. */
@Component({
  selector: 'cl-topic-picker',
  imports: [MathText],
  templateUrl: './topic-picker.html',
  styleUrl: './topic-picker.css',
})
export class TopicPicker {
  readonly sections = input.required<CurriculumSection[]>();
  /** The ids of the picked topics. */
  readonly picked = input.required<string[]>();
  readonly clearLabel = input('Wyczyść wybór');
  readonly pickedChange = output<string[]>();

  private readonly dialog = viewChild.required<ElementRef<HTMLDialogElement>>('dialog');
  protected readonly query = signal('');

  /** The sections with the topics that fit the words typed; a section that fits keeps all. */
  protected readonly shown = computed(() => {
    const words = this.query().trim().toLowerCase();
    if (!words) return this.sections();
    return this.sections()
      .map((s) =>
        s.name.toLowerCase().includes(words)
          ? s
          : { ...s, topics: s.topics.filter((t) => t.name.toLowerCase().includes(words)) },
      )
      .filter((s) => s.topics.length);
  });

  open(): void {
    this.query.set('');
    this.dialog().nativeElement.showModal();
  }

  protected close(): void {
    this.dialog().nativeElement.close();
  }

  protected has(id: string): boolean {
    return this.picked().includes(id);
  }

  /** How many of a section's shown topics are picked: all, some or none. */
  protected share(topics: { id: string }[]): 'all' | 'some' | 'none' {
    const n = topics.filter((t) => this.has(t.id)).length;
    return n === 0 ? 'none' : n === topics.length ? 'all' : 'some';
  }

  protected pick(topics: { id: string }[], on: boolean): void {
    const ids = topics.map((t) => t.id);
    const rest = this.picked().filter((id) => !ids.includes(id));
    this.pickedChange.emit(on ? [...rest, ...ids] : rest);
  }

  protected clear(): void {
    this.pickedChange.emit([]);
  }
}
