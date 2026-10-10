import { HttpErrorResponse, HttpInterceptorFn } from '@angular/common/http';
import { InjectionToken, inject } from '@angular/core';
import { NEVER, catchError, throwError } from 'rxjs';

export const SIGN_IN = new InjectionToken<() => void>('sign in', {
  factory: () => () => location.assign('/auth/login'),
});

/** Any API call refused for want of a session sends the Teacher to sign in. The call never
 * settles, since the page is leaving, so callers need not handle it. */
export const signInOn401: HttpInterceptorFn = (request, next) => {
  const signIn = inject(SIGN_IN);
  return next(request).pipe(
    catchError((error: unknown) => {
      if (!(error instanceof HttpErrorResponse && error.status === 401)) return throwError(() => error);
      signIn();
      return NEVER;
    }),
  );
};
