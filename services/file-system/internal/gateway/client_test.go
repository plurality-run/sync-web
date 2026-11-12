package gateway

import (
	"reflect"
	"testing"

	"github.com/plurality-run/sync-web/services/file-system/internal/paths"
)

func TestJSONPathEncodesWebDAVSegmentsAsSchemeIdentifiers(t *testing.T) {
	got := JSONPath([]paths.Segment{
		paths.Str("*state*"),
		paths.Str("tdinh"),
		paths.Str("New folder"),
		paths.Str("a%b.txt"),
	})
	want := []any{"*state*", "tdinh", "New%20folder", "a%25b.txt"}
	if !reflect.DeepEqual(got, want) {
		t.Fatalf("JSONPath() = %#v, want %#v", got, want)
	}
}
