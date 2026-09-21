package oairesponses

import (
	"strings"
	"testing"
)

func TestModelPortIssue7498ToolImageMustNotBecomeText(t *testing.T) {
	blocks := []any{
		map[string]any{"type": "input_text", "text": "synthetic tool result"},
		map[string]any{"type": "input_image", "image_url": "data:image/png;base64,RklYVFVSRU9OTFk="},
	}
	content, err := responseToolOutputToChatContent(blocks)
	if err != nil {
		if content != nil || !strings.Contains(err.Error(), "does not support non-text tool output") {
			t.Fatalf("unexpected conversion failure: %v", err)
		}
		return
	}
	text, flattened := content.(string)
	if flattened && strings.Contains(text, "data:image/png;base64,RklYVFVSRU9OTFk=") {
		t.Fatal("issue 7498 reproduced: 2 tool content blocks flattened into text containing synthetic image base64")
	}
}
