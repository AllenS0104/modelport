package middleware

import (
	"net/http"
	"testing"
	"time"

	"github.com/QuantumNous/new-api/common"
	"github.com/gin-gonic/gin"
	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
)

func TestSessionLifecycleRateLimitIsolation(t *testing.T) {
	gin.SetMode(gin.TestMode)
	for _, useRedis := range []bool{false, true} {
		name := "memory"
		if useRedis {
			name = "redis"
		}
		t.Run(name, func(t *testing.T) {
			previousEnabled, previousRedis := common.CriticalRateLimitEnable, common.RedisEnabled
			previousNum, previousDuration := common.CriticalRateLimitNum, common.CriticalRateLimitDuration
			common.CriticalRateLimitEnable = true
			common.CriticalRateLimitNum = 20
			common.CriticalRateLimitDuration = 1200
			common.RedisEnabled = false
			t.Cleanup(func() {
				common.CriticalRateLimitEnable, common.RedisEnabled = previousEnabled, previousRedis
				common.CriticalRateLimitNum, common.CriticalRateLimitDuration = previousNum, previousDuration
			})
			if useRedis {
				useRateLimitMiniRedis(t)
			}
			router := gin.New()
			require.NoError(t, router.SetTrustedProxies(nil))
			ok := func(c *gin.Context) { c.Status(http.StatusNoContent) }
			router.GET("/refresh", SessionLifecycleRateLimit("refresh"), ok)
			router.GET("/logout", SessionLifecycleRateLimit("logout"), ok)
			router.GET("/login", CriticalRateLimit(), ok)
			address := "192.0.2.150:1234"
			for range 120 {
				require.Equal(t, http.StatusNoContent, performRateLimitRequest(router, "/refresh", address).Code)
			}
			response := performRateLimitRequest(router, "/refresh", address)
			assert.Equal(t, http.StatusTooManyRequests, response.Code)
			assert.Equal(t, "60", response.Header().Get("Retry-After"))
			require.Equal(t, http.StatusNoContent, performRateLimitRequest(router, "/logout", address).Code)
			for range 20 {
				require.Equal(t, http.StatusNoContent, performRateLimitRequest(router, "/login", address).Code)
			}
			response = performRateLimitRequest(router, "/login", address)
			assert.Equal(t, http.StatusTooManyRequests, response.Code)
			assert.Equal(t, "1200", response.Header().Get("Retry-After"))
			assert.Equal(t, http.StatusNoContent, performRateLimitRequest(router, "/logout", address).Code)
			assert.Equal(t, http.StatusNoContent, performRateLimitRequest(router, "/refresh", "192.0.2.151:1234").Code)
		})
	}
}

func TestSessionLifecycleRateLimitRecoversIndependently(t *testing.T) {
	server, _ := useRateLimitMiniRedis(t)
	router := gin.New()
	require.NoError(t, router.SetTrustedProxies(nil))
	router.GET("/refresh", SessionLifecycleRateLimit("refresh"), func(c *gin.Context) {
		c.Status(http.StatusNoContent)
	})
	for range 120 {
		require.Equal(t, http.StatusNoContent, performRateLimitRequest(router, "/refresh", "192.0.2.152:1234").Code)
	}
	require.Equal(t, http.StatusTooManyRequests, performRateLimitRequest(router, "/refresh", "192.0.2.152:1234").Code)
	server.FastForward(time.Minute)
	assert.Equal(t, http.StatusNoContent, performRateLimitRequest(router, "/refresh", "192.0.2.152:1234").Code)
}
