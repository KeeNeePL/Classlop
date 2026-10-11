// PROTOTYPE (throwaway): the floating bar that cycles the variants through ?variant=.
import { Component, HostListener, inject, input } from '@angular/core';
import { Router } from '@angular/router';

@Component({
  selector: 'cl-prototype-switcher',
  template: `
    <button type="button" aria-label="Poprzedni wariant" (click)="go(-1)">&larr;</button>
    <span>{{ current() }} ({{ names()[current()] }})</span>
    <button type="button" aria-label="Następny wariant" (click)="go(1)">&rarr;</button>
  `,
  styles: `
    :host {
      position: fixed;
      left: 50%;
      bottom: 16px;
      z-index: 50;
      transform: translateX(-50%);
      display: flex;
      align-items: center;
      gap: 12px;
      padding: 6px 12px;
      border-radius: 999px;
      background: #111;
      color: #fff;
      box-shadow: 0 4px 16px rgba(0, 0, 0, 0.35);
      font-size: 14px;
    }
    button {
      font: inherit;
      color: #fff;
      background: none;
      border: 0;
      cursor: pointer;
      padding: 2px 8px;
    }
  `,
})
export class Switcher {
  private readonly router = inject(Router);
  readonly current = input.required<string>();
  readonly names = input.required<Record<string, string>>();

  protected go(step: number): void {
    const keys = Object.keys(this.names());
    const next = keys[(keys.indexOf(this.current()) + step + keys.length) % keys.length];
    void this.router.navigate([], { queryParams: { variant: next }, replaceUrl: true });
  }

  @HostListener('document:keydown', ['$event'])
  protected key(event: KeyboardEvent): void {
    const target = event.target as HTMLElement;
    if (/^(INPUT|TEXTAREA|SELECT)$/.test(target.tagName) || target.isContentEditable) return;
    if (event.key === 'ArrowLeft') this.go(-1);
    if (event.key === 'ArrowRight') this.go(1);
  }
}
