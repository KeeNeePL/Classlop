import { provideHttpClient, withInterceptors } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';
import { provideRouter } from '@angular/router';
import { App } from './app';
import { SIGN_IN, signInOn401 } from './sign-in';

describe('App', () => {
  let http: HttpTestingController;
  let signIn: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    signIn = vi.fn();
    TestBed.configureTestingModule({
      imports: [App],
      providers: [
        provideRouter([]),
        provideHttpClient(withInterceptors([signInOn401])),
        provideHttpClientTesting(),
        { provide: SIGN_IN, useValue: signIn },
      ],
    });
    http = TestBed.inject(HttpTestingController);
  });

  it("shows the Teacher's name and Wyloguj", async () => {
    const fixture = TestBed.createComponent(App);
    http.expectOne('/api/me').flush({ name: 'Anna Nowak', sign_in_lapsed: false });
    await fixture.whenStable();

    const sidebar = (fixture.nativeElement as HTMLElement).querySelector('nav')!;
    expect(sidebar.textContent).toContain('Anna Nowak');
    expect(sidebar.querySelector('a[href="/auth/logout"]')).not.toBeNull();
    expect(signIn).not.toHaveBeenCalled();
    expect((fixture.nativeElement as HTMLElement).querySelector('[role="alert"]')).toBeNull();
  });

  it('sends the Teacher to sign in without a session', async () => {
    const fixture = TestBed.createComponent(App);
    http.expectOne('/api/me').flush(null, { status: 401, statusText: 'Unauthorized' });
    await fixture.whenStable();

    expect(signIn).toHaveBeenCalledOnce();
    expect((fixture.nativeElement as HTMLElement).textContent).not.toContain('Wyloguj');
  });

  it('shows a Zaloguj się ponownie bar once the sign-in has lapsed', async () => {
    const fixture = TestBed.createComponent(App);
    http.expectOne('/api/me').flush({ name: 'Anna Nowak', sign_in_lapsed: true });
    await fixture.whenStable();

    const bar = (fixture.nativeElement as HTMLElement).querySelector('[role="alert"]')!;
    expect(bar.querySelector('a')?.textContent).toContain('Zaloguj się ponownie');
    expect(bar.querySelector('a')?.getAttribute('href')).toBe('/auth/login');
  });
});
