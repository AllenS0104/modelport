package middleware

import (
	"net/http"
	"net/http/httptest"
	"testing"

	"github.com/gin-gonic/gin"
	"github.com/stretchr/testify/require"
)

func TestModelPortCountTokensNeverReachesGeneration(t *testing.T) {
	for _, path := range []string{
		"/v1beta/models/gemini-fixture:countTokens",
		"/v1/models/gemini-fixture:countTokens",
		"/v1beta/models/gemini-fixture%3AcountTokens?alt=sse",
		"/v1beta/models/gemini-fixture:generateContent",
		"/v1beta/models/gemini-fixture:streamGenerateContent",
		"/v1/chat/completions",
	} {
		t.Run(path, func(t *testing.T) {
			called := false
			router := gin.New()
			router.Use(ModelPortRejectGeminiCountTokens())
			router.POST("/*path", func(c *gin.Context) {
				called = true
				c.Status(http.StatusOK)
			})
			recorder := httptest.NewRecorder()
			router.ServeHTTP(recorder, httptest.NewRequest(http.MethodPost, path, nil))
			if path == "/v1beta/models/gemini-fixture:generateContent" ||
				path == "/v1beta/models/gemini-fixture:streamGenerateContent" ||
				path == "/v1/chat/completions" {
				require.True(t, called)
				require.Equal(t, http.StatusOK, recorder.Code)
			} else {
				require.False(t, called)
				require.Equal(t, http.StatusNotFound, recorder.Code)
				require.Contains(t, recorder.Body.String(), "no generation or billing")
			}
		})
	}
}
