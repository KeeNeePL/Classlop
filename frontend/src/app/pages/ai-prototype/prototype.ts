// PROTOTYPE (throwaway): three variants of the Classlop AI screen on /ai, chosen by ?variant=A|B|C.
// Read-only: a fake AI with invented data, no backend calls.
import { Component, inject } from '@angular/core';
import { toSignal } from '@angular/core/rxjs-interop';
import { ActivatedRoute } from '@angular/router';
import { map } from 'rxjs';
import { Switcher } from './switcher';
import { VariantA } from './variant-a';
import { VariantB } from './variant-b';
import { VariantC } from './variant-c';

export const VARIANTS: Record<string, string> = {
  A: 'Warsztat: czat i panel wyników',
  B: 'Skupiony czat z zakładkami',
  C: 'Tryby zamiast wolnego tekstu',
};

@Component({
  selector: 'cl-ai-prototype',
  imports: [Switcher, VariantA, VariantB, VariantC],
  template: `
    @switch (variant()) {
      @case ('A') {
        <cl-variant-a />
      }
      @case ('B') {
        <cl-variant-b />
      }
      @case ('C') {
        <cl-variant-c />
      }
    }
    <cl-prototype-switcher [current]="variant()" [names]="names" />
  `,
})
export class AiPrototype {
  protected readonly names = VARIANTS;
  protected readonly variant = toSignal(
    inject(ActivatedRoute).queryParamMap.pipe(map((q) => q.get('variant') ?? 'A')),
    { requireSync: true },
  );
}

export const isVariant = (value: string | null): boolean => !!value && value in VARIANTS;
