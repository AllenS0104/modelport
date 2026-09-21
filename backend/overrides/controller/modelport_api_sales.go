package controller

import (
	"net/http"
	"net/mail"
	"strings"

	"github.com/QuantumNous/new-api/common"
	"github.com/QuantumNous/new-api/model"
	"github.com/QuantumNous/new-api/relaykit/dto"
	"github.com/QuantumNous/new-api/service"
	"github.com/gin-gonic/gin"
)

func ModelPortWebChatDisabled(c *gin.Context) {
	c.AbortWithStatusJSON(http.StatusForbidden, gin.H{
		"success": false, "code": "WEB_CHAT_DISABLED",
		"message": "本站暂不提供网页聊天，请使用客户 API Key 接入自己的应用。",
	})
}

func modelPortEmail(user *model.User) (string, bool) {
	address := strings.TrimSpace(user.GetSetting().NotificationEmail)
	if address == "" {
		address = strings.TrimSpace(user.Email)
	}
	parsed, err := mail.ParseAddress(address)
	return address, err == nil && parsed.Address == address && !strings.ContainsAny(address, "\r\n;")
}

func modelPortSMTPReady() bool {
	return strings.TrimSpace(common.SMTPServer) != "" &&
		(strings.TrimSpace(common.SMTPFrom) != "" || strings.TrimSpace(common.SMTPAccount) != "")
}

func ModelPortEmailReadiness(c *gin.Context) {
	user, err := model.GetUserById(c.GetInt("id"), true)
	if err != nil {
		common.ApiError(c, err)
		return
	}
	_, recipientOK := modelPortEmail(user)
	common.ApiSuccess(c, gin.H{"configured": modelPortSMTPReady(), "recipient_configured": recipientOK})
}

func ModelPortTestEmail(c *gin.Context) {
	user, err := model.GetUserById(c.GetInt("id"), true)
	if err != nil {
		common.ApiError(c, err)
		return
	}
	address, valid := modelPortEmail(user)
	if !valid {
		c.JSON(http.StatusBadRequest, gin.H{"success": false, "code": "NOTIFICATION_EMAIL_REQUIRED",
			"message": "请先保存有效的通知邮箱，或绑定账户邮箱。"})
		return
	}
	if !modelPortSMTPReady() {
		c.JSON(http.StatusServiceUnavailable, gin.H{"success": false, "code": "SMTP_NOT_CONFIGURED",
			"message": "邮件服务尚未配置，请联系管理员。"})
		return
	}
	settings := user.GetSetting()
	settings.NotifyType = dto.NotifyTypeEmail
	settings.NotificationEmail = address
	err = service.NotifyUser(user.Id, user.Email, settings, dto.NewNotify(
		"modelport-email-test", "模港 ModelPort 邮件通知测试",
		"这是一封由你在账户设置中主动请求的通知测试邮件。请勿回复或在邮件中发送 API Key。", nil))
	if err != nil {
		common.SysError("ModelPort notification test failed; verify SMTP settings, delivery limits and network access")
		c.JSON(http.StatusBadGateway, gin.H{"success": false, "code": "NOTIFICATION_EMAIL_FAILED",
			"message": "测试邮件未成功发送，请联系管理员检查邮件配置及发送限制。"})
		return
	}
	common.ApiSuccess(c, gin.H{"accepted": true})
}

func ModelPortDeleteChannelModel(c *gin.Context) {
	var request struct {
		ModelName string `json:"model_name"`
	}
	if err := c.ShouldBindJSON(&request); err != nil {
		common.ApiErrorMsg(c, "请选择要从渠道移除的模型。")
		return
	}
	result, err := model.ModelPortDeleteChannelModel(request.ModelName)
	if err != nil {
		common.ApiError(c, err)
		return
	}
	recordManageAudit(c, "model.delete_channel_only", map[string]any{
		"model_name": request.ModelName, "updated_channels": result.UpdatedChannels,
	})
	common.ApiSuccess(c, result)
}
