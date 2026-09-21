package gemini

import (
	"github.com/QuantumNous/new-api/common"
	"github.com/QuantumNous/new-api/logger"
	relaycommon "github.com/QuantumNous/new-api/relay/common"
	"github.com/QuantumNous/new-api/relay/helper"
	"github.com/QuantumNous/new-api/relaykit/types"
	"github.com/gin-gonic/gin"
)

func writeModelPortGeminiStreamError(c *gin.Context, info *relaycommon.RelayInfo) {
	if isGeminiDownstreamStop(c, info) {
		return
	}
	logger.LogWarn(c, "upstream Gemini stream interrupted; settling reported partial usage")
	message := "Upstream stream interrupted; the response is incomplete"
	payload := gin.H{"error": gin.H{
		"message": message, "type": "upstream_error", "code": "stream_interrupted",
	}}
	switch info.RelayFormat {
	case types.RelayFormatClaude:
		c.Render(-1, common.CustomEvent{Data: "event: error\n"})
		payload = gin.H{"type": "error", "error": gin.H{"type": "api_error", "message": message}}
	case types.RelayFormatGemini:
		payload = gin.H{"error": gin.H{"code": 502, "status": "UNAVAILABLE", "message": message}}
	}
	data, err := common.Marshal(payload)
	if err == nil {
		err = helper.StringData(c, string(data))
	}
	if err != nil {
		logger.LogError(c, "failed to write Gemini stream error: "+err.Error())
	}
}
