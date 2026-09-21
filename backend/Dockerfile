FROM golang:1.26.1-alpine@sha256:2389ebfa5b7f43eeafbd6be0c3700cc46690ef842ad962f6c5bd6be49ed82039 AS build
ENV CGO_ENABLED=0 GOWORK=off GOEXPERIMENT=greenteagc GOMAXPROCS=4 GOFLAGS=-p=4
WORKDIR /src
COPY go.mod go.sum ./
COPY relaykit/go.mod ./relaykit/go.mod
RUN go mod download
COPY . .
RUN test -z "$(gofmt -l middleware/session_lifecycle_rate_limit*.go middleware/account_security_policy.go middleware/modelport_*.go controller/account_security_policy_test.go controller/modelport_*.go model/modelport_*.go relay/channel/*/modelport_*.go relay/modelport_*.go relaykit/relayconvert/internal/oai_responses/modelport_*.go)" \
    && go test ./middleware -run 'TestModelPort|TestSessionLifecycleRateLimit|TestRedisIPRateLimiter|TestRedisFixedWindow|TestTrustedProxies' -count=1 \
    && go test ./relay/channel/gemini ./relay/channel/openai ./relay/channel/ali ./relay -run 'TestModelPort' -count=1 \
    && go test github.com/QuantumNous/new-api/relaykit/relayconvert/internal/oai_responses -run 'TestModelPort' -count=1 \
    && go test ./model -run 'TestModelPort' -count=1 \
    && go test ./controller -run 'TestModelPort|TestSecurityLogin|TestSecurityAccountPassword|TestSecurityAccountLongUnicode|TestSecurityAccountFirstPassword|TestSecurityEnrollmentOAuthVerification|TestAuthLogout|TestPasskeyDomains' -count=1 \
    && go build -trimpath -ldflags "-s -w -X github.com/QuantumNous/new-api/common.Version=$(cat VERSION)" -o /new-api

FROM calciumion/new-api@sha256:846a5b12f6b3a78acbf59201ffc1d4f0b31c701d252eff8238cefa6ab3643029
COPY --from=build /new-api /new-api
COPY --from=build /src/modelport-backend /licenses/modelport-backend
LABEL io.modelport.patch="upstream-bugfixes-v1" \
      io.modelport.upstream="385d2dfd10d821b25c8a6766bd16eea248cb1652"
