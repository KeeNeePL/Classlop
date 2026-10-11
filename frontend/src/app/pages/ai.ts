import { Component, ElementRef, computed, effect, inject, signal, viewChild } from '@angular/core';
import { Router, RouterLink, RouterLinkActive, RouterOutlet } from '@angular/router';
import { ChatEntry } from '../api/models';
import { Badge } from '../ui/badge';
import { AiStore } from './ai-store';

/** The Classlop AI tab: the Teacher's Chats on the left, the open Chat on the right. */
@Component({
  imports: [Badge, RouterLink, RouterLinkActive, RouterOutlet],
  templateUrl: './ai.html',
  styleUrl: './ai.css',
})
export class Ai {
  private readonly store = inject(AiStore);
  private readonly router = inject(Router);

  protected readonly query = signal('');
  /** The Chat whose name is being typed over. */
  protected readonly renaming = signal<string | null>(null);
  /** The Chat the Teacher is asked to confirm deleting. */
  protected readonly deleting = signal<string | null>(null);

  protected readonly shown = computed(() => {
    const q = this.query().trim().toLowerCase();
    return (this.store.chats() ?? []).filter((c) => c.name.toLowerCase().includes(q));
  });

  private readonly field = viewChild<ElementRef<HTMLInputElement>>('field');

  constructor() {
    effect(() => this.field()?.nativeElement.focus());
  }

  protected async rename(chat: ChatEntry, name: string): Promise<void> {
    if (this.renaming() !== chat.id) return;
    this.renaming.set(null);
    if (name.trim() && name.trim() !== chat.name) await this.store.rename(chat.id, name.trim());
  }

  protected async remove(chat: ChatEntry): Promise<void> {
    this.deleting.set(null);
    await this.store.remove(chat.id);
    if (this.router.url.split('?')[0] === `/ai/${chat.id}`) await this.router.navigate(['/ai']);
  }
}
