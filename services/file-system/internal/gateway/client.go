package gateway

import (
	"bytes"
	"context"
	"encoding/base64"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"strings"
	"time"

	"github.com/plurality-run/sync-web/services/file-system/internal/paths"
)

type Client struct {
	BaseURL    string
	HTTPClient *http.Client
}

func New(baseURL string) *Client {
	return &Client{BaseURL: strings.TrimRight(baseURL, "/"), HTTPClient: &http.Client{Timeout: 30 * time.Second}}
}

func (c *Client) Get(ctx context.Context, r *http.Request, path []paths.Segment) (any, error) {
	return c.post(ctx, r, "/general/use", map[string]any{"path": JSONPath(path), "read-only?": true})
}

func (c *Client) Resolve(ctx context.Context, r *http.Request, path []paths.Segment) (any, error) {
	return c.post(ctx, r, "/general/retrieve", map[string]any{"path": JSONPath(path)})
}

func (c *Client) Set(ctx context.Context, r *http.Request, path []paths.Segment, value any) error {
	_, err := c.post(ctx, r, "/general/put", map[string]any{"path": JSONPath(path), "value": value})
	return err
}

func (c *Client) Delete(ctx context.Context, r *http.Request, path []paths.Segment) error {
	return c.Set(ctx, r, path, []string{"nothing"})
}

func (c *Client) Pin(ctx context.Context, r *http.Request, path []paths.Segment) error {
	_, err := c.post(ctx, r, "/general/pin", map[string]any{"path": JSONPath(path)})
	return err
}

func (c *Client) Unpin(ctx context.Context, r *http.Request, path []paths.Segment) error {
	_, err := c.post(ctx, r, "/general/unpin", map[string]any{"path": JSONPath(path)})
	return err
}

func JSONPath(path []paths.Segment) []any {
	out := make([]any, 0, len(path))
	for _, segment := range path {
		if segment.IsInt {
			out = append(out, segment.Int)
		} else {
			out = append(out, paths.EncodeSchemePathSegment(segment.String))
		}
	}
	return out
}

func (c *Client) post(ctx context.Context, source *http.Request, route string, body any) (any, error) {
	encoded, err := json.Marshal(body)
	if err != nil {
		return nil, err
	}
	req, err := http.NewRequestWithContext(ctx, http.MethodPost, c.BaseURL+route, bytes.NewReader(encoded))
	if err != nil {
		return nil, err
	}
	req.Header.Set("Content-Type", "application/json")
	forwardAuth(source, req)
	res, err := c.HTTPClient.Do(req)
	if err != nil {
		return nil, err
	}
	defer res.Body.Close()
	payload, err := io.ReadAll(res.Body)
	if err != nil {
		return nil, err
	}
	var parsed any
	if len(payload) != 0 {
		if err := json.Unmarshal(payload, &parsed); err != nil {
			parsed = string(payload)
		}
	}
	if res.StatusCode < 200 || res.StatusCode >= 300 {
		return nil, Error{StatusCode: res.StatusCode, Body: parsed}
	}
	return parsed, nil
}

func forwardAuth(source *http.Request, target *http.Request) {
	if header := source.Header.Get("Authorization"); strings.HasPrefix(header, "Bearer ") {
		target.Header.Set("Authorization", header)
		return
	}
	if _, password, ok := source.BasicAuth(); ok && password != "" {
		target.Header.Set("Authorization", "Bearer "+password)
		return
	}
	if cookie := source.Header.Get("Cookie"); cookie != "" {
		target.Header.Set("Cookie", cookie)
	}
	if token := source.Header.Get("X-Session-Token"); token != "" {
		target.Header.Set("X-Session-Token", token)
	}
}

type Error struct {
	StatusCode int
	Body       any
}

func (e Error) Error() string {
	if e.Body == nil {
		return fmt.Sprintf("gateway returned status %d", e.StatusCode)
	}
	encoded, err := json.Marshal(e.Body)
	if err != nil {
		return fmt.Sprintf("gateway returned status %d", e.StatusCode)
	}
	return fmt.Sprintf("gateway returned status %d: %s", e.StatusCode, string(encoded))
}

func BasicAuth(username, password string) string {
	return "Basic " + base64.StdEncoding.EncodeToString([]byte(username+":"+password))
}
