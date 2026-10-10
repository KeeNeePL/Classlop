import { provideHttpClient, withInterceptors } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';
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
        provideHttpClient(withInterceptors([signInOn401])),
        provideHttpClientTesting(),
        { provide: SIGN_IN, useValue: signIn },
      ],
    });
    http = TestBed.inject(HttpTestingController);
  });

  it("shows the Teacher's name and Wyloguj", async () => {
    const fixture = TestBed.createComponent(App);
    http.expectOne('/api/me').flush({ name: 'Anna Nowak' });
    await fixture.whenStable();

    const header = (fixture.nativeElement as HTMLElement).querySelector('header')!;
    expect(header.textContent).toContain('Anna Nowak');
    expect(header.querySelector('a')?.getAttribute('href')).toBe('/auth/logout');
    expect(signIn).not.toHaveBeenCalled();
  });

  it('sends the Teacher to sign in without a session', async () => {
    const fixture = TestBed.createComponent(App);
    http.expectOne('/api/me').flush(null, { status: 401, statusText: 'Unauthorized' });
    await fixture.whenStable();

    expect(signIn).toHaveBeenCalledOnce();
    expect((fixture.nativeElement as HTMLElement).textContent).not.toContain('Wyloguj');
  });
});
