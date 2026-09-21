package oairesponses

import (
	"encoding/json"
	"testing"

	"github.com/QuantumNous/new-api/relaykit/dto"
	"github.com/stretchr/testify/require"
)

func TestModelPortToolOutputCannotSilentlyFlattenMedia(t *testing.T) {
	for _, tc := range []struct {
		name, output, want string
		reject             bool
	}{
		{"string", `"plain text"`, "plain text", false},
		{"text blocks", `[{"type":"input_text","text":"first"},{"type":"input_text","text":"second"}]`, "firstsecond", false},
		{"image", `[{"type":"input_text","text":"look"},{"type":"input_image","image_url":"data:image/png;base64,RklYVFVSRQ=="}]`, "", true},
		{"file", `[{"type":"input_file","file_data":"RklYVFVSRQ=="}]`, "", true},
		{"audio", `[{"type":"input_audio","input_audio":{"data":"RklYVFVSRQ==","format":"wav"}}]`, "", true},
	} {
		t.Run(tc.name, func(t *testing.T) {
			req := &dto.OpenAIResponsesRequest{Model: "fixture", Input: json.RawMessage(
				`[{"type":"function_call_output","call_id":"call-fixture","output":` + tc.output + `}]`)}
			chat, err := ResponsesRequestToChatCompletionsRequest(req)
			if tc.reject {
				require.ErrorContains(t, err, "does not support non-text tool output")
				require.Nil(t, chat)
			} else {
				require.NoError(t, err)
				require.Len(t, chat.Messages, 1)
				require.Equal(t, "tool", chat.Messages[0].Role)
				require.Equal(t, "call-fixture", chat.Messages[0].ToolCallId)
				require.Equal(t, tc.want, chat.Messages[0].Content)
			}
		})
	}
}
