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
  {
    path: 'bank',
    loadComponent: () => import('./pages/bank').then((m) => m.Bank),
    children: [
      { path: '', loadComponent: () => import('./pages/bank').then((m) => m.BankEmpty) },
      {
        path: ':zadanie',
        loadComponent: () => import('./pages/bank-item').then((m) => m.BankItem),
      },
    ],
  },
  empty('klasy/nowa', 'Nowa klasa'),
  {
    path: 'klasy/:klasa',
    component: ClassPage,
    children: [
      {
        path: '',
        loadComponent: () => import('./pages/class-overview').then((m) => m.ClassOverview),
      },
      empty('lekcje', 'Lekcje', true),
      empty('lekcje/:lekcja', 'Lekcja', true),
      empty('ustawienia', 'Ustawienia klasy', true),
    ],
  },
  empty('klasy/:klasa/uczniowie/:uczen', 'Uczeń'),
  empty('klasy/:klasa/nowa-praca', 'Nowa praca'),
  {
    path: 'klasy/:klasa/prace/:praca',
    loadComponent: () => import('./pages/assignment-page').then((m) => m.AssignmentPage),
  },
  empty('klasy/:klasa/prace/:praca/:uczen', 'Praca ucznia'),
  empty('ustawienia', 'Ustawienia'),
  { path: '**', component: NotFound },
];
