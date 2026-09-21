package ali

import (
	"encoding/json"
	"net/http/httptest"
	"testing"

	"github.com/gin-gonic/gin"
	"github.com/stretchr/testify/require"
)

func TestModelPortAliPreservesEveryImage(t *testing.T) {
	var output AliOutput
	require.NoError(t, json.Unmarshal([]byte(`{"choices":[
		{"message":{"content":[{"image":"https://fixture.invalid/one"},{"image":"https://fixture.invalid/two"},{"text":"prompt"}]}},
		{"message":{"content":[{"image":"RklYVFVSRQ=="}]}},
		{"message":{"content":[{"text":"no image"}]}}
	]}`), &output))
	c, _ := gin.CreateTestContext(httptest.NewRecorder())
	images := output.ChoicesToOpenAIImageDate(c, "url")
	require.Len(t, images, 3)
	require.Equal(t, "https://fixture.invalid/one", images[0].Url)
	require.Equal(t, "https://fixture.invalid/two", images[1].Url)
	require.Equal(t, "prompt", images[0].RevisedPrompt)
	require.Equal(t, "prompt", images[1].RevisedPrompt)
	require.Equal(t, "RklYVFVSRQ==", images[2].B64Json)
}
