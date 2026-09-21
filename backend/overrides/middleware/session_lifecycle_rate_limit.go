package middleware

import "github.com/gin-gonic/gin"

const (
	sessionLifecycleRequests = 120
	sessionLifecycleWindow   = int64(60)
)

// SessionLifecycleRateLimit keeps cookie rotation and logout out of the
// credential-attempt budget. Each operation retains an independent IP limit.
func SessionLifecycleRateLimit(operation string) gin.HandlerFunc {
	return rateLimitFactory(sessionLifecycleRequests, sessionLifecycleWindow, "SESSION:"+operation)
}
