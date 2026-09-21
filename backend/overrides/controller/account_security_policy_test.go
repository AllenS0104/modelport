package controller

import (
	"net/http"
	"net/http/httptest"
	"strconv"
	"strings"
	"testing"
	"time"

	"github.com/QuantumNous/new-api/common"
	"github.com/QuantumNous/new-api/middleware"
	"github.com/QuantumNous/new-api/model"
	"github.com/QuantumNous/new-api/service"
	"github.com/gin-gonic/gin"
	"github.com/stretchr/testify/require"
)

// Real UserAuth resolves the role from the server record, not request headers/body.
func TestModelPortPolicyUsesAuthenticatedRole(t *testing.T) {
	for _, role := range []int{common.RoleCommonUser, common.RoleAdminUser, common.RoleRootUser} {
		t.Run(strconv.Itoa(role), func(t *testing.T) {
			user, _ := setupSecurityEnrollmentTest(t)
			require.NoError(t, model.DB.Model(user).Update("role", role).Error)
			require.NoError(t, model.PublishUserAuthCache(user.Id))
			bundle, err := service.CreateLoginSession(user.Id, "password", "127.0.0.1", "policy-test")
			require.NoError(t, err)
			router := gin.New()
			router.POST("/restricted", middleware.UserAuth(), middleware.AccountSecurityAdminOnly(), func(c *gin.Context) { c.Status(http.StatusNoContent) })
			pat := common.GetRandomString(32)
			require.NoError(t, model.UpdateUserAccessToken(user.Id, pat))
			router.DELETE("/api/user/self", middleware.UserAuth(), middleware.DenySelfAccountDeletion(), DeleteSelf)
			for _, token := range []string{bundle.AccessToken, pat} {
				r := httptest.NewRequest("POST", "/restricted?role=100", strings.NewReader(`{"role":100,"id":1,"admin":true}`))
				r.Header.Set("Authorization", "Bearer "+token)
				r.Header.Set("New-Api-User", "1")
				r.Header.Set("X-Role", "100")
				w := httptest.NewRecorder()
				router.ServeHTTP(w, r)
				expected := http.StatusNoContent
				if role == common.RoleCommonUser {
					expected = http.StatusForbidden
				}
				require.Equal(t, expected, w.Code)
				if role == common.RoleCommonUser {
					require.Contains(t, w.Body.String(), "ACCOUNT_SECURITY_MANAGED_BY_ADMIN")
				}
				r = httptest.NewRequest("DELETE", "/api/user/self", nil)
				r.Header.Set("Authorization", "Bearer "+token)
				w = httptest.NewRecorder()
				router.ServeHTTP(w, r)
				require.Equal(t, http.StatusForbidden, w.Code)
				require.Contains(t, w.Body.String(), "SELF_ACCOUNT_DELETION_DISABLED")
			}

		})
	}
}

func TestModelPortPrivacyPreservesOmittedFields(t *testing.T) {
	for _, value := range []string{"true", "false", "null", "omit", "case"} {
		t.Run(value, func(t *testing.T) {
			user, identity := setupSecurityEnrollmentTest(t)
			settings := user.GetSetting()
			settings.RecordIpLog = true
			require.NoError(t, model.UpdateUserSetting(user.Id, settings))
			body := `{"notify_type":"email","quota_warning_threshold":500}`
			switch value {
			case "omit":
			case "case":
				body = strings.TrimSuffix(body, "}") + `,"RECORD_IP_LOG":false}`
			default:
				body = strings.TrimSuffix(body, "}") + `,"record_ip_log":` + value + `}`
			}
			response := securityEnrollmentRequest("PUT", "/api/user/setting", body, "", identity, UpdateUserSetting)
			expected := http.StatusOK
			if value == "false" || value == "case" {
				expected = http.StatusForbidden
			}
			require.Equal(t, expected, response.Code)
			stored, err := model.GetUserById(user.Id, false)
			require.NoError(t, err)
			require.True(t, stored.GetSetting().RecordIpLog)
		})
	}
}

func TestModelPortOAuthPendingBindCannotBypassPolicy(t *testing.T) {
	user, identity := setupSecurityEnrollmentTest(t)
	state, _, err := model.CreateAuthFlow(model.AuthFlowCreate{
		Purpose: model.AuthFlowPurposeOAuth, Provider: "github", Intent: model.AuthFlowIntentBind,
		UserId: user.Id, SessionId: identity.SessionID, Payload: "{}", ExpiresAt: time.Now().Add(time.Minute),
	})
	require.NoError(t, err)
	w := httptest.NewRecorder()
	c, _ := gin.CreateTestContext(w)
	c.Request = httptest.NewRequest("GET", "/api/oauth/github?state="+state, nil)
	c.Params = gin.Params{{Key: "provider", Value: "github"}}
	c.Set("id", user.Id)
	c.Set("role", common.RoleCommonUser)
	c.Set("session_id", identity.SessionID)
	c.Set("auth_version", identity.UserAuthVersion)
	c.Set("session_version", identity.SessionVersion)
	HandleOAuth(c)
	require.Equal(t, http.StatusForbidden, w.Code)
	require.Contains(t, w.Body.String(), "ACCOUNT_SECURITY_MANAGED_BY_ADMIN")
	_, err = model.GetAuthFlow(state, model.AuthFlowMatch{Purpose: model.AuthFlowPurposeOAuth, Provider: "github"})
	require.NoError(t, err) // no provider call, no mutation/consumption
}

func TestModelPortAdminPrivacyStillWorks(t *testing.T) {
	user, identity := setupSecurityEnrollmentTest(t)
	w := httptest.NewRecorder()
	c, _ := gin.CreateTestContext(w)
	c.Request = httptest.NewRequest("PUT", "/api/user/setting", strings.NewReader(`{"notify_type":"email","quota_warning_threshold":500,"record_ip_log":true}`))
	c.Request.Header.Set("Content-Type", "application/json")
	c.Set("id", identity.UserID)
	c.Set("role", common.RoleAdminUser)
	UpdateUserSetting(c)
	require.Equal(t, http.StatusOK, w.Code)
	stored, err := model.GetUserById(user.Id, false)
	require.NoError(t, err)
	require.True(t, stored.GetSetting().RecordIpLog)
}
