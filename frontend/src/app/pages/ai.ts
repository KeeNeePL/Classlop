import {
  Component,
  ElementRef,
  HostListener,
  computed,
  effect,
  inject,
  signal,
  viewChild,
} from '@angular/core';
import { toSignal } from '@angular/core/rxjs-interop';
import {
  ActivatedRoute,
  NavigationEnd,
  Router,
  RouterLink,
  RouterLinkActive,
  RouterOutlet,
} from '@angular/router';
import { filter, map } from 'rxjs';
import { ChatEntry } from '../api/models';
import { Badge } from '../ui/badge';
import { AiStore } from './ai-store';

/** The Classlop AI tab: the open Chat, with the Teacher's Chats in a menu above it. */
@Component({
  imports: [Badge, RouterLink, RouterLinkActive, RouterOutlet],
  templateUrl: './ai.html',
  styleUrl: './ai.css',
})
export class Ai {
  private readonly store = inject(AiStore);
  private readonly router = inject(Router);
  private readonly route = inject(ActivatedRoute);

  protected readonly open = signal(false);
  protected readonly query = signal('');
  /** The Chat whose name is being typed over. */
  protected readonly renaming = signal<string | null>(null);
  /** The Chat the Teacher is asked to confirm deleting. */
  protected readonly deleting = signal<string | null>(null);

  protected readonly shown = computed(() => {
    const q = this.query().trim().toLowerCase();
    return (this.store.chats() ?? []).filter((c) => c.name.toLowerCase().includes(q));
  });

  private readonly chatId = toSignal(
    this.router.events.pipe(
      filter((e) => e instanceof NavigationEnd),
      map(() => this.openId()),
    ),
    { initialValue: this.openId() },
  );
  /** The open Chat, or undefined on the start of a new one and while the list loads. */
  protected readonly current = computed(() =>
    (this.store.chats() ?? []).find((c) => c.id === this.chatId()),
  );
  protected readonly label = computed(() => this.current()?.name || 'Nowy czat');

  private readonly field = viewChild<ElementRef<HTMLInputElement>>('field');
  private readonly toggle = viewChild.required<ElementRef<HTMLButtonElement>>('toggle');
  private readonly picker = viewChild.required<ElementRef<HTMLElement>>('picker');

  constructor() {
    effect(() => this.field()?.nativeElement.focus());
  }

  @HostListener('document:keydown.escape')
  protected escape(): void {
    if (!this.open()) return;
    this.close();
    this.toggle().nativeElement.focus();
  }

  @HostListener('document:click', ['$event'])
  protected outside(event: MouseEvent): void {
    if (this.open() && !this.picker().nativeElement.contains(event.target as Node)) this.close();
  }

  protected close(): void {
    this.open.set(false);
    this.renaming.set(null);
    this.deleting.set(null);
  }

  protected cancelRename(event: Event): void {
    event.stopPropagation();
    this.renaming.set(null);
  }

  protected async rename(chat: ChatEntry, name: string): Promise<void> {
    if (this.renaming() !== chat.id) return;
    this.renaming.set(null);
    if (name.trim() && name.trim() !== chat.name) await this.store.rename(chat.id, name.trim());
  }

  protected async remove(chat: ChatEntry): Promise<void> {
    this.deleting.set(null);
    await this.store.remove(chat.id);
    if (this.chatId() === chat.id) await this.router.navigate(['/ai']);
  }

  private openId(): string | null {
    return this.route.firstChild?.snapshot?.paramMap.get('czat') ?? null;
  }
}
