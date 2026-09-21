package controller

import (
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"

	"github.com/QuantumNous/new-api/common"
	"github.com/QuantumNous/new-api/model"
	"github.com/gin-gonic/gin"
	"github.com/stretchr/testify/require"
)

func TestModelPortEmailUsesSavedRecipientAndReportsMissingSMTP(t *testing.T) {
	user, _ := setupSecurityEnrollmentTest(t)
	oldServer, oldFrom, oldAccount := common.SMTPServer, common.SMTPFrom, common.SMTPAccount
	common.SMTPServer, common.SMTPFrom, common.SMTPAccount = "", "", ""
	t.Cleanup(func() {
		common.SMTPServer, common.SMTPFrom, common.SMTPAccount = oldServer, oldFrom, oldAccount
	})
	settings := user.GetSetting()
	settings.NotificationEmail = "fixture@example.test"
	require.NoError(t, model.UpdateUserSetting(user.Id, settings))
	w := httptest.NewRecorder()
	c, _ := gin.CreateTestContext(w)
	c.Request = httptest.NewRequest(http.MethodPost, "/email/test", strings.NewReader(`{"email":"attacker@example.test"}`))
	c.Set("id", user.Id)
	ModelPortTestEmail(c)
	require.Equal(t, http.StatusServiceUnavailable, w.Code)
	require.Contains(t, w.Body.String(), "SMTP_NOT_CONFIGURED")
	require.NotContains(t, w.Body.String(), "attacker@example.test")
}

func TestModelPortEmailRejectsMissingAndMultipleRecipients(t *testing.T) {
	user, _ := setupSecurityEnrollmentTest(t)
	user.Email = ""
	for _, address := range []string{"", "first@example.test;second@example.test", "first@example.test\r\nBcc: second@example.test"} {
		settings := user.GetSetting()
		settings.NotificationEmail = address
		user.SetSetting(settings)
		_, valid := modelPortEmail(user)
		require.False(t, valid)
	}
}

func TestModelPortWebChatIsExplicitlyDisabled(t *testing.T) {
	w := httptest.NewRecorder()
	c, _ := gin.CreateTestContext(w)
	ModelPortWebChatDisabled(c)
	require.Equal(t, http.StatusForbidden, w.Code)
	require.Contains(t, w.Body.String(), "WEB_CHAT_DISABLED")
	require.True(t, c.IsAborted())
}
