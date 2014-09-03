SUBROUTINE calc_fits(images, model, parvals, n_vals, n_wlens, x, y, n_pars, results, fitvals)

IMPLICIT NONE
INTEGER, INTENT(IN) :: n_vals, n_wlens, x, y, n_pars
REAL, DIMENSION(n_vals, n_pars), INTENT(IN) :: parvals
REAL, DIMENSION(n_vals, n_wlens), INTENT(IN) :: model
REAL, DIMENSION(n_wlens, x, y), INTENT(IN) :: images
REAL, DIMENSION(x, y), INTENT(OUT) :: fitvals
REAL, DIMENSION(x, y, n_pars), INTENT(OUT) :: results
INTEGER :: i, j, t, w
REAL :: error, total_error, this_fit, best_fit

DO j = 1, y
  DO i = 1, x
    best_fit = 1000000.0
    DO t = 1, n_vals
      total_error = 0.0
      DO w = 1, n_wlens
        error = ABS(images(w,i,j) - model(t, w))
        total_error = total_error + error
      END DO
      this_fit = total_error / REAL(n_wlens)
      IF (this_fit < best_fit) THEN
        best_fit = this_fit
        fitvals(i, j) = this_fit
        results(i, j, :) = parvals(t, :)
      END IF
    END DO
  END DO
END DO

END SUBROUTINE calc_fits