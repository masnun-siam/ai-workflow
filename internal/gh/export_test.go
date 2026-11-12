package gh

import "time"

// SetAuthClock replaces the cache's clock (tests).
func SetAuthClock(a *AuthCache, now func() time.Time) { a.now = now }
