package middleware

import (
	"net/http"
	"strings"

	"github.com/gin-gonic/gin"
)

func ModelPortRejectGeminiCountTokens() gin.HandlerFunc {
	return func(c *gin.Context) {
		path := c.Request.URL.Path
		if c.Request.Method == http.MethodPost &&
			(strings.HasPrefix(path, "/v1/models/") || strings.HasPrefix(path, "/v1beta/models/")) &&
			strings.HasSuffix(path, ":countTokens") {
			c.AbortWithStatusJSON(http.StatusNotFound, gin.H{"error": gin.H{
				"code": http.StatusNotFound, "status": "UNIMPLEMENTED",
				"message": "Gemini countTokens is not supported; no generation or billing was performed",
			}})
			return
		}
		c.Next()
	}
}
