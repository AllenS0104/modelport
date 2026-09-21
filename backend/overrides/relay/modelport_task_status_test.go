package relay

import (
	"net/http"
	"net/http/httptest"
	"strconv"
	"testing"

	"github.com/QuantumNous/new-api/common"
	"github.com/QuantumNous/new-api/constant"
	"github.com/QuantumNous/new-api/service"
	"github.com/QuantumNous/new-api/setting/operation_setting"
	"github.com/QuantumNous/new-api/setting/ratio_setting"
	"github.com/stretchr/testify/require"
)

func TestModelPortTaskSubmitAcceptsCreatedAndAccepted(t *testing.T) {
	savedPrices := ratio_setting.ModelPrice2JSONString()
	savedFree := operation_setting.GetQuotaSetting().EnableFreeModelPreConsume
	t.Cleanup(func() {
		require.NoError(t, ratio_setting.UpdateModelPriceByJSONString(savedPrices))
		operation_setting.GetQuotaSetting().EnableFreeModelPreConsume = savedFree
	})
	require.NoError(t, ratio_setting.UpdateModelPriceByJSONString(`{"declared-model":0}`))
	operation_setting.GetQuotaSetting().EnableFreeModelPreConsume = false
	service.InitHttpClient()
	for _, status := range []int{200, 201, 202, 204, 400, 500} {
		t.Run(strconv.Itoa(status), func(t *testing.T) {
			calls := 0
			server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
				calls++
				w.Header().Set("Content-Type", "application/json")
				w.WriteHeader(status)
				if status != http.StatusNoContent {
					_, _ = w.Write([]byte(`{"taskId":"1"}`))
				}
			}))
			defer server.Close()
			c, info := newTaskSubmitContext(t, "declared-model", "")
			common.SetContextKey(c, constant.ContextKeyChannelBaseUrl, server.URL)
			pinMappingOrderPlugin(t, c, mappingOrderSubmitPlugin)
			info.OriginModelName = "declared-model"
			result, taskErr := RelayTaskSubmit(c, info)
			require.Equal(t, 1, calls)
			if status == 200 || status == 201 || status == 202 {
				require.Nil(t, taskErr)
				require.NotNil(t, result)
				require.Equal(t, "1", result.UpstreamTaskID)
			} else {
				require.NotNil(t, taskErr)
				require.Nil(t, result)
			}
		})
	}
}
