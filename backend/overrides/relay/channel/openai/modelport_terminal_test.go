package openai

import (
	"testing"

	relaycommon "github.com/QuantumNous/new-api/relay/common"
	"github.com/QuantumNous/new-api/relaykit/dto"
	"github.com/stretchr/testify/require"
)

func TestModelPortTerminalChoicesAreNotUsageOnly(t *testing.T) {
	for _, tc := range []struct {
		name, choices string
		send          bool
	}{
		{"stop", `[{"index":0,"delta":{},"finish_reason":"stop"}]`, true},
		{"length", `[{"index":0,"delta":{},"finish_reason":"length"}]`, true},
		{"tool", `[{"index":0,"delta":{"tool_calls":[{"index":0,"id":"call-fixture","type":"function","function":{"name":"tool","arguments":"{}"}}]},"finish_reason":"tool_calls"}]`, true},
		{"role", `[{"index":0,"delta":{"role":"assistant"}}]`, true},
		{"text", `[{"index":0,"delta":{"content":"answer"}}]`, true},
		{"usage-only", `[]`, false},
	} {
		t.Run(tc.name, func(t *testing.T) {
			for _, include := range []bool{false, true} {
				var id, fingerprint, model string
				var created int64
				usage := &dto.Usage{}
				contains, send := false, true
				frame := `{"id":"fixture","model":"fixture","choices":` + tc.choices +
					`,"usage":{"prompt_tokens":100,"completion_tokens":20,"total_tokens":120}}`
				err := handleLastResponse(frame, &id, &created, &fingerprint, &model, &usage,
					&contains, &relaycommon.RelayInfo{ShouldIncludeUsage: include}, &send)
				require.NoError(t, err)
				require.Equal(t, include || tc.send, send)
				require.True(t, contains)
				require.Equal(t, 100, usage.PromptTokens)
				require.Equal(t, 20, usage.CompletionTokens)
			}
		})
	}
}
