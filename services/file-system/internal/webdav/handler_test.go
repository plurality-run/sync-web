package webdav

import (
	"encoding/json"
	"fmt"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"

	"github.com/plurality-run/sync-web/services/file-system/internal/gateway"
)

func TestStagePutGetCopyMoveDelete(t *testing.T) {
	fake := newFakeGateway(t)
	h := Handler{Gateway: gateway.New(fake.url + "/api/v1"), MaxObjectBytes: 1024 * 1024}

	request(t, h, "PUT", "/webdav/stage/admin/a.txt", "hello", http.StatusCreated)
	body := request(t, h, "GET", "/webdav/stage/admin/a.txt", "", http.StatusOK)
	if body != "hello" {
		t.Fatalf("unexpected GET body: %q", body)
	}

	req := httptest.NewRequest("COPY", "/webdav/stage/admin/a.txt", nil)
	req.Header.Set("Destination", "http://example.test/webdav/stage/admin/b.txt")
	res := httptest.NewRecorder()
	h.ServeHTTP(res, req)
	if res.Code != http.StatusCreated {
		t.Fatalf("COPY status = %d body=%s", res.Code, res.Body.String())
	}
	body = request(t, h, "GET", "/webdav/stage/admin/b.txt", "", http.StatusOK)
	if body != "hello" {
		t.Fatalf("unexpected copied body: %q", body)
	}

	req = httptest.NewRequest("MOVE", "/webdav/stage/admin/b.txt", nil)
	req.Header.Set("Destination", "http://example.test/webdav/stage/admin/c.txt")
	res = httptest.NewRecorder()
	h.ServeHTTP(res, req)
	if res.Code != http.StatusCreated {
		t.Fatalf("MOVE status = %d body=%s", res.Code, res.Body.String())
	}
	request(t, h, "GET", "/webdav/stage/admin/b.txt", "", http.StatusNotFound)
	body = request(t, h, "GET", "/webdav/stage/admin/c.txt", "", http.StatusOK)
	if body != "hello" {
		t.Fatalf("unexpected moved body: %q", body)
	}

	request(t, h, "DELETE", "/webdav/stage/admin/c.txt", "", http.StatusNoContent)
	request(t, h, "GET", "/webdav/stage/admin/c.txt", "", http.StatusNotFound)
}

func TestMkcolAndPropfindHideDirectoryMarker(t *testing.T) {
	fake := newFakeGateway(t)
	h := Handler{Gateway: gateway.New(fake.url + "/api/v1"), MaxObjectBytes: 1024 * 1024}

	request(t, h, "MKCOL", "/webdav/stage/admin/docs/", "", http.StatusCreated)
	marker, ok := fake.values["*state*/admin/docs/*directory*"].(map[string]any)
	if !ok || marker["*type/byte-vector*"] != "" {
		t.Fatalf("directory marker was not stored as an empty byte-vector: %#v", fake.values["*state*/admin/docs/*directory*"])
	}
	body := request(t, h, "PROPFIND", "/webdav/stage/admin/docs/", "", 207)
	if strings.Contains(body, "*directory*") {
		t.Fatalf("marker leaked in PROPFIND: %s", body)
	}
}

func TestDirectoryChildrenDecodePercentEscapedSegments(t *testing.T) {
	children, ok := directoryChildren([]any{"directory", []any{
		[]any{"New%20folder", "directory"},
		[]any{"a%25b.txt", "value"},
	}, true})
	if !ok {
		t.Fatal("directory was not decoded")
	}
	if len(children) != 2 || children[0].Name != "New folder" || !children[0].Directory || children[1].Name != "a%b.txt" || children[1].Directory {
		t.Fatalf("unexpected children: %#v", children)
	}

	children, ok = directoryChildren([]any{"directory", map[string]any{
		"hello%20world%20&%20%C3%BC.bin": "value",
	}, true})
	if !ok || len(children) != 1 || children[0].Name != "hello world & ü.bin" {
		t.Fatalf("unexpected map children: %#v", children)
	}
}

func TestEscapedNamesPropfindAndRecursiveLifecycle(t *testing.T) {
	fake := newFakeGateway(t)
	fake.mapDirectories = true
	h := Handler{Gateway: gateway.New(fake.url + "/api/v1"), MaxObjectBytes: 1024 * 1024}

	request(t, h, "MKCOL", "/webdav/stage/admin/source%20space/", "", http.StatusCreated)
	request(t, h, "PUT", "/webdav/stage/admin/source%20space/hello%20world%20%26%20%C3%BC.bin", "hello", http.StatusCreated)
	body := request(t, h, "PROPFIND", "/webdav/stage/admin/source%20space/", "", 207)
	if !strings.Contains(body, "/webdav/stage/admin/source%20space/") || !strings.Contains(body, "hello%20world%20&amp;%20%C3%BC.bin") {
		t.Fatalf("escaped hrefs missing from PROPFIND: %s", body)
	}

	req := httptest.NewRequest("COPY", "/webdav/stage/admin/source%20space/", nil)
	req.Header.Set("Destination", "http://example.test/webdav/stage/admin/copied%20space/")
	res := httptest.NewRecorder()
	h.ServeHTTP(res, req)
	if res.Code != http.StatusCreated {
		t.Fatalf("COPY status = %d body=%s", res.Code, res.Body.String())
	}
	request(t, h, "GET", "/webdav/stage/admin/copied%20space/hello%20world%20%26%20%C3%BC.bin", "", http.StatusOK)

	req = httptest.NewRequest("MOVE", "/webdav/stage/admin/copied%20space/", nil)
	req.Header.Set("Destination", "http://example.test/webdav/stage/admin/moved%20space/")
	res = httptest.NewRecorder()
	h.ServeHTTP(res, req)
	if res.Code != http.StatusCreated {
		t.Fatalf("MOVE status = %d body=%s", res.Code, res.Body.String())
	}
	request(t, h, "GET", "/webdav/stage/admin/moved%20space/hello%20world%20%26%20%C3%BC.bin", "", http.StatusOK)
	request(t, h, "DELETE", "/webdav/stage/admin/moved%20space/", "", http.StatusNoContent)
	request(t, h, "GET", "/webdav/stage/admin/moved%20space/hello%20world%20%26%20%C3%BC.bin", "", http.StatusNotFound)
}

func TestFederatedLedgerReadsSendCanonicalCommittedPath(t *testing.T) {
	fake := newFakeGateway(t)
	fake.values["-1/journal-1/-1/*state*/alice/data/public/key-0"] = map[string]any{"*type/byte-vector*": "6869"}
	fake.values["1554/journal-1/-2/journal-3/7/*state*/alice/data/public/key-0"] = map[string]any{"*type/byte-vector*": "6869"}
	h := Handler{Gateway: gateway.New(fake.url + "/api/v1"), MaxObjectBytes: 1024 * 1024}

	request(t, h, "GET", "/webdav/ledger/bridge/journal-1/state/alice/data/public/key-0", "", http.StatusOK)
	assertCommittedPath(t, fake.lastBody, []any{-1, "journal-1", -1, "*state*", "alice", "data", "public", "key-0"})
	body := request(t, h, "PROPFIND", "/webdav/ledger/bridge/journal-1/state/alice/data/public/", "", 207)
	if !strings.Contains(body, "key-0") {
		t.Fatalf("federated PROPFIND omitted child: %s", body)
	}
	assertCommittedPath(t, fake.lastBody, []any{-1, "journal-1", -1, "*state*", "alice", "data", "public", "key-0"})

	request(t, h, "GET", "/webdav/ledger/1/5/5/4/bridge/journal-1/minus/2/bridge/journal-3/7/state/alice/data/public/key-0", "", http.StatusOK)
	assertCommittedPath(t, fake.lastBody, []any{1554, "journal-1", -2, "journal-3", 7, "*state*", "alice", "data", "public", "key-0"})
}

func TestExpiredFederatedHistoryIsNotFoundWithoutHidingAuthorizationErrors(t *testing.T) {
	expired := httptest.NewRecorder()
	writeGatewayError(expired, gateway.Error{StatusCode: http.StatusBadRequest, Body: map[string]any{
		"error":   "bridge-index-error",
		"message": "wording is not part of the subtype",
	}})
	if expired.Code != http.StatusNotFound {
		t.Fatalf("expired history status = %d, want 404", expired.Code)
	}

	denied := httptest.NewRecorder()
	writeGatewayError(denied, gateway.Error{StatusCode: http.StatusBadRequest, Body: map[string]any{
		"error":   "authorization-error",
		"message": "Principal is not authorized",
	}})
	if denied.Code != http.StatusBadRequest {
		t.Fatalf("authorization status = %d, want 400", denied.Code)
	}

	legacyMessage := httptest.NewRecorder()
	writeGatewayError(legacyMessage, gateway.Error{StatusCode: http.StatusBadRequest, Body: map[string]any{
		"error":   "bridge-error",
		"message": "Bridge is not committed at the selected local index: journal-1 -1",
	}})
	if legacyMessage.Code != http.StatusBadRequest {
		t.Fatalf("message-only history status = %d, want 400", legacyMessage.Code)
	}
}

func TestPropfindHidesReservedStateSegments(t *testing.T) {
	fake := newFakeGateway(t)
	fake.values["*state*/*time*"] = "reserved"
	fake.values["*state*/*directory*"] = map[string]any{"*type/byte-vector*": ""}
	fake.values["*state*/admin/a.txt"] = map[string]any{"*type/byte-vector*": "68656c6c6f"}
	h := Handler{Gateway: gateway.New(fake.url + "/api/v1"), MaxObjectBytes: 1024 * 1024}

	body := request(t, h, "PROPFIND", "/webdav/stage/", "", 207)
	if strings.Contains(body, "*time*") || strings.Contains(body, "*directory*") {
		t.Fatalf("reserved segment leaked in PROPFIND: %s", body)
	}
	if !strings.Contains(body, "admin") {
		t.Fatalf("non-reserved child missing from PROPFIND: %s", body)
	}
}

func TestNonByteVectorValueFailsClearly(t *testing.T) {
	fake := newFakeGateway(t)
	fake.values["*state*/admin/raw.txt"] = "raw expression"
	h := Handler{Gateway: gateway.New(fake.url + "/api/v1"), MaxObjectBytes: 1024 * 1024}

	request(t, h, "GET", "/webdav/stage/admin/raw.txt", "", http.StatusUnsupportedMediaType)
	request(t, h, "PROPFIND", "/webdav/stage/admin/raw.txt", "", http.StatusUnsupportedMediaType)
}

func TestControlPinIsWriteOnly(t *testing.T) {
	fake := newFakeGateway(t)
	h := Handler{Gateway: gateway.New(fake.url + "/api/v1"), MaxObjectBytes: 1024 * 1024}

	request(t, h, "GET", "/webdav/control/pin", "", http.StatusMethodNotAllowed)
	request(t, h, "PUT", "/webdav/control/pin", "pinned /ledger/state/admin/file.txt\n", http.StatusNoContent)
}

func TestLedgerSyntheticIndexCollections(t *testing.T) {
	fake := newFakeGateway(t)
	h := Handler{Gateway: gateway.New(fake.url + "/api/v1"), MaxObjectBytes: 1024 * 1024}

	body := request(t, h, "PROPFIND", "/webdav/ledger/2/", "", 207)
	if !strings.Contains(body, "/webdav/ledger/2/state/") || !strings.Contains(body, "/webdav/ledger/2/bridge/") || !strings.Contains(body, "/webdav/ledger/2/0/") {
		t.Fatalf("ledger index collection missing children: %s", body)
	}

	request(t, h, "PROPFIND", "/webdav/ledger/2/bridge/", "", 207)
	request(t, h, "PROPFIND", "/webdav/ledger/2/bridge/alice/", "", 207)

	body = request(t, h, "PROPFIND", "/webdav/ledger/2/bridge/alice/minus/2/", "", 207)
	if !strings.Contains(body, "/webdav/ledger/2/bridge/alice/minus/2/state/") {
		t.Fatalf("bridge target collection missing state child: %s", body)
	}
}

func TestBasicAuthPasswordForwardsAsBearer(t *testing.T) {
	fake := newFakeGateway(t)
	h := Handler{Gateway: gateway.New(fake.url + "/api/v1"), MaxObjectBytes: 1024 * 1024}

	req := httptest.NewRequest("PUT", "/webdav/stage/admin/a.txt", strings.NewReader("hello"))
	req.SetBasicAuth("admin", "sync-token")
	res := httptest.NewRecorder()
	h.ServeHTTP(res, req)
	if res.Code != http.StatusCreated {
		t.Fatalf("PUT status = %d body=%s", res.Code, res.Body.String())
	}
	if fake.lastAuthorization != "Bearer sync-token" {
		t.Fatalf("authorization not forwarded as bearer: %q", fake.lastAuthorization)
	}
}

func request(t *testing.T, h Handler, method, path, body string, want int) string {
	t.Helper()
	req := httptest.NewRequest(method, path, strings.NewReader(body))
	res := httptest.NewRecorder()
	h.ServeHTTP(res, req)
	if res.Code != want {
		t.Fatalf("%s %s status = %d, want %d body=%s", method, path, res.Code, want, res.Body.String())
	}
	return res.Body.String()
}

type fakeGateway struct {
	t                 *testing.T
	server            *httptest.Server
	url               string
	values            map[string]any
	lastAuthorization string
	lastBody          map[string]any
	mapDirectories    bool
}

func newFakeGateway(t *testing.T) *fakeGateway {
	fake := &fakeGateway{t: t, values: map[string]any{}}
	fake.server = httptest.NewServer(http.HandlerFunc(fake.handle))
	fake.url = fake.server.URL
	t.Cleanup(fake.server.Close)
	return fake
}

func (f *fakeGateway) handle(w http.ResponseWriter, r *http.Request) {
	f.lastAuthorization = r.Header.Get("Authorization")
	var body map[string]any
	if err := json.NewDecoder(r.Body).Decode(&body); err != nil {
		http.Error(w, err.Error(), http.StatusBadRequest)
		return
	}
	f.lastBody = body
	key := pathKey(body["path"])
	switch r.URL.Path {
	case "/api/v1/general/put":
		value := body["value"]
		if isNothingValue(value) {
			delete(f.values, key)
		} else {
			f.values[key] = value
		}
		writeJSON(w, true)
	case "/api/v1/general/use", "/api/v1/general/retrieve":
		if value, ok := f.values[key]; ok {
			writeJSON(w, value)
			return
		}
		if children := f.children(key); len(children) > 0 {
			if f.mapDirectories {
				mapped := map[string]any{}
				for _, entry := range children {
					pair := entry.([]any)
					mapped[pair[0].(string)] = pair[1]
				}
				writeJSON(w, []any{"directory", mapped, true})
				return
			}
			writeJSON(w, []any{"directory", children, true})
			return
		}
		writeJSON(w, []any{"nothing"})
	case "/api/v1/general/pin", "/api/v1/general/unpin":
		writeJSON(w, true)
	default:
		http.Error(w, "unknown route", http.StatusNotFound)
	}
}

func (f *fakeGateway) children(prefix string) []any {
	base := prefix
	if base != "" {
		base += "/"
	}
	seen := map[string]string{}
	for key := range f.values {
		if !strings.HasPrefix(key, base) {
			continue
		}
		rest := strings.TrimPrefix(key, base)
		if rest == "" {
			continue
		}
		parts := strings.Split(rest, "/")
		kind := "value"
		if len(parts) > 1 {
			kind = "directory"
		}
		if existing, ok := seen[parts[0]]; !ok || existing != "directory" {
			seen[parts[0]] = kind
		}
	}
	children := make([]any, 0, len(seen))
	for name, kind := range seen {
		children = append(children, []any{name, kind})
	}
	return children
}

func pathKey(value any) string {
	items, _ := value.([]any)
	parts := make([]string, 0, len(items))
	for _, item := range items {
		parts = append(parts, fmt.Sprint(item))
	}
	return strings.Join(parts, "/")
}

func assertCommittedPath(t *testing.T, body map[string]any, want []any) {
	t.Helper()
	if _, ok := body["$federation"]; ok {
		t.Fatalf("unexpected outward federation context: %#v", body)
	}
	got, _ := body["path"].([]any)
	if fmt.Sprint(got) != fmt.Sprint(want) {
		t.Fatalf("path = %#v, want %v", got, want)
	}
}

func isNothingValue(value any) bool {
	items, ok := value.([]any)
	return ok && len(items) == 1 && items[0] == "nothing"
}

func writeJSON(w http.ResponseWriter, value any) {
	w.Header().Set("Content-Type", "application/json")
	_ = json.NewEncoder(w).Encode(value)
}

func TestSafeContentTypeUsesMagicBeforeFilename(t *testing.T) {
	png := []byte{0x89, 'P', 'N', 'G', 0x0d, 0x0a, 0x1a, 0x0a}
	if got := safeContentType(png, "misleading.html"); got != "image/png" {
		t.Fatalf("content type = %q, want image/png", got)
	}
	if got := safeContentType([]byte("<script>alert(1)</script>"), "page.html"); got != "text/plain; charset=utf-8" {
		t.Fatalf("content type = %q, want inert text", got)
	}
}

func TestSafeContentTypeFallsBackForUnknownBinary(t *testing.T) {
	if got := safeContentType([]byte{0x00, 0xff, 0x00, 0xfe}, "image.svg"); got != "application/octet-stream" {
		t.Fatalf("content type = %q, want application/octet-stream", got)
	}
}
