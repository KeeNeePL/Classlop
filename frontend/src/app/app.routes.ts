import { Route, Routes } from '@angular/router';
import { ClassPage } from './pages/class-page';
import { DoZrobienia } from './pages/do-zrobienia';
import { EmptyPage } from './pages/empty-page';
import { NotFound } from './pages/not-found';

const empty = (path: string, title: string, sub = false): Route => ({
  path,
  component: EmptyPage,
  data: { title, sub },
});

export const routes: Routes = [
  { path: '', pathMatch: 'full', component: DoZrobienia },
  empty('ai', 'Classlop AI'),
  empty('ai/:czat', 'Classlop AI'),
  empty('bank', 'Bank zadań'),
  empty('bank/:zadanie', 'Bank zadań'),
  empty('klasy/nowa', 'Nowa klasa'),
  {
    path: 'klasy/:klasa',
    component: ClassPage,
    children: [
      empty('', 'Przegląd', true),
      empty('lekcje', 'Lekcje', true),
      empty('lekcje/:lekcja', 'Lekcja', true),
      empty('ustawienia', 'Ustawienia klasy', true),
    ],
  },
  empty('klasy/:klasa/uczniowie/:uczen', 'Uczeń'),
  empty('klasy/:klasa/nowa-praca', 'Nowa praca'),
  empty('klasy/:klasa/prace/:praca', 'Praca'),
  empty('klasy/:klasa/prace/:praca/:uczen', 'Praca ucznia'),
  empty('ustawienia', 'Ustawienia'),
  { path: '**', component: NotFound },
];
