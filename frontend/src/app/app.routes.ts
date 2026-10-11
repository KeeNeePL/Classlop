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
  {
    path: 'klasy/nowa',
    loadComponent: () => import('./pages/new-class').then((m) => m.NewClass),
  },
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
      {
        path: 'ustawienia',
        loadComponent: () => import('./pages/class-settings').then((m) => m.ClassSettingsTab),
      },
    ],
  },
  {
    path: 'klasy/:klasa/uczniowie/:uczen',
    loadComponent: () => import('./pages/student-report').then((m) => m.StudentReport),
  },
  {
    path: 'klasy/:klasa/nowa-praca',
    loadComponent: () => import('./pages/new-work').then((m) => m.NewWork),
  },
  {
    path: 'klasy/:klasa/prace/:praca',
    loadComponent: () => import('./pages/assignment-page').then((m) => m.AssignmentPage),
  },
  {
    path: 'klasy/:klasa/prace/:praca/:uczen',
    loadComponent: () => import('./pages/submission-page').then((m) => m.SubmissionPage),
  },
  {
    path: 'ustawienia',
    loadComponent: () => import('./pages/settings').then((m) => m.Settings),
  },
  { path: '**', component: NotFound },
];
