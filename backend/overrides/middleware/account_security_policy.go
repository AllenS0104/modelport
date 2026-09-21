// ModelPort policy overlay; upstream authentication and security proofs remain required.
package middleware

import (
	"net/http"

	"github.com/QuantumNous/new-api/common"
	"github.com/gin-gonic/gin"
)

// RequireAccountSecurityAdmin uses only the context populated by UserAuth or
// TryUserAuth (validated session/PAT and server-side user record), never input roles.
// This is an additional restriction, not a grant of any upstream permission.
func RequireAccountSecurityAdmin(c *gin.Context) bool {
	if c.GetInt("id") > 0 && c.GetInt("role") >= common.RoleAdminUser {
		return true
	}
	c.AbortWithStatusJSON(http.StatusForbidden, gin.H{
		"success": false,
		"code":    "ACCOUNT_SECURITY_MANAGED_BY_ADMIN",
		"message": "此安全设置由平台管理员管理；密码修改及现有登录验证不受影响。",
	})
	return false
}

func AccountSecurityAdminOnly() gin.HandlerFunc {
	return func(c *gin.Context) {
		if RequireAccountSecurityAdmin(c) {
			c.Next()
		}
	}
}

// Keep the existing ingress prohibition even for direct backend requests.
func DenySelfAccountDeletion() gin.HandlerFunc {
	return func(c *gin.Context) {
		c.AbortWithStatusJSON(http.StatusForbidden, gin.H{
			"success": false, "code": "SELF_ACCOUNT_DELETION_DISABLED",
			"message": "平台不开放自助删除账户。",
		})
	}
}
