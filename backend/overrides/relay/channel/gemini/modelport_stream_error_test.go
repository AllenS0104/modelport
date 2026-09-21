package gemini

import (
	"io"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"

	"github.com/QuantumNous/new-api/constant"
	relaycommon "github.com/QuantumNous/new-api/relay/common"
	"github.com/QuantumNous/new-api/relaykit/dto"
	"github.com/QuantumNous/new-api/relaykit/types"
	"github.com/gin-gonic/gin"
	"github.com/stretchr/testify/require"
)

type modelPortTruncatedBody struct{ *strings.Reader }

func (r modelPortTruncatedBody) Read(p []byte) (int, error) {
	if r.Len() == 0 {
		return 0, io.ErrUnexpectedEOF
	}
	return r.Reader.Read(p)
}

func TestModelPortGeminiTruncationIsExplicitAndRetainsUsage(t *testing.T) {
	saved := constant.StreamingTimeout
	constant.StreamingTimeout = 30
	t.Cleanup(func() { constant.StreamingTimeout = saved })
	for _, format := range []types.RelayFormat{types.RelayFormatOpenAI, types.RelayFormatGemini, types.RelayFormatClaude, types.RelayFormatOpenAIResponses} {
		t.Run(string(format), func(t *testing.T) {
			recorder := httptest.NewRecorder()
			c, _ := gin.CreateTestContext(recorder)
			c.Request = httptest.NewRequest(http.MethodPost, "/fixture", nil)
			info := &relaycommon.RelayInfo{
				RelayFormat: format, OriginModelName: "gemini-fixture",
				ChannelMeta: &relaycommon.ChannelMeta{UpstreamModelName: "gemini-fixture"},
			}
			info.SetEstimatePromptTokens(100)
			body := `data: {"candidates":[{"content":{"role":"model","parts":[{"text":"partial"}]}}],"usageMetadata":{"promptTokenCount":100,"candidatesTokenCount":5,"totalTokenCount":105}}` + "\n\n"
			resp := &http.Response{Body: io.NopCloser(modelPortTruncatedBody{strings.NewReader(body)})}
			var usage *dto.Usage
			var apiErr *types.NewAPIError
			switch format {
			case types.RelayFormatGemini:
				usage, apiErr = GeminiTextGenerationStreamHandler(c, info, resp)
			case types.RelayFormatOpenAIResponses:
				usage, apiErr = GeminiResponsesStreamHandler(c, info, resp)
			default:
				usage, apiErr = GeminiChatStreamHandler(c, info, resp)
			}
			require.Nil(t, apiErr, "an emitted stream failure must not trigger retry/full refund")
			require.NotNil(t, usage)
			require.Equal(t, 100, usage.PromptTokens)
			require.Equal(t, 5, usage.CompletionTokens)
			require.Contains(t, recorder.Body.String(), `"error"`)
			require.NotContains(t, recorder.Body.String(), "data: [DONE]")
			require.NotContains(t, recorder.Body.String(), "response.completed")
			require.NotContains(t, recorder.Body.String(), "event: message_stop")
			require.False(t, info.StreamStatus.IsNormalEnd())
		})
	}
}
