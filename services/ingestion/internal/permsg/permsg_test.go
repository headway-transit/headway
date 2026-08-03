package permsg

import (
	"errors"
	"fmt"
	"io/fs"
	"os"
	"strings"
	"testing"
)

// The binding message rules (handoff 0037, design point 4): the actual
// path, the exact fix command, one line of why — and never 777.

func TestHintOnPermissionErrorNamesCommandWhyAndHostPath(t *testing.T) {
	err := fmt.Errorf("mkdir /data/tides-drop/processed: %w", fs.ErrPermission)
	got := Hint(err, "/data/tides-drop", "deploy/compose/tides-drop")
	for _, want := range []string{
		"sudo chown -R 65532:65532 deploy/compose/tides-drop", // the exact fix
		"locked-down user account",                            // the one-line why
		"user id 65532",
		"under your Headway folder", // where the relative path lives
	} {
		if !strings.Contains(got, want) {
			t.Errorf("hint missing %q\nhint: %s", want, got)
		}
	}
	if strings.Contains(got, "777") && !strings.Contains(got, "Do not use chmod 777") {
		t.Errorf("hint mentions 777 outside the explicit do-not: %s", got)
	}
	if !strings.Contains(got, "Do not use chmod 777") {
		t.Errorf("hint must warn against 777 by name (the bad field advice): %s", got)
	}
}

func TestHintWithoutHostDirNamesTheMountHonestly(t *testing.T) {
	err := fmt.Errorf("open x: %w", os.ErrPermission)
	got := Hint(err, "/data/vendor-drop", "")
	if !strings.Contains(got, "sudo chown -R 65532:65532 /data/vendor-drop") {
		t.Errorf("fix command missing: %s", got)
	}
	if !strings.Contains(got, "mounted at /data/vendor-drop in the collector container") {
		t.Errorf("container-vs-host mount explanation missing: %s", got)
	}
}

func TestHintEmptyForNonPermissionErrors(t *testing.T) {
	for _, err := range []error{
		nil,
		errors.New("connection refused"),
		fs.ErrNotExist,
		fmt.Errorf("stat: %w", fs.ErrNotExist),
	} {
		if got := Hint(err, "/data/tides-drop", ""); got != "" {
			t.Errorf("Hint(%v) = %q, want empty", err, got)
		}
	}
}

func TestHintDetectsWrappedRealOSError(t *testing.T) {
	// A real *fs.PathError from the OS, wrapped the way the connectors
	// wrap it, must still be recognized.
	dir := t.TempDir()
	if os.Geteuid() == 0 {
		t.Skip("running as root: cannot produce a permission error")
	}
	if err := os.Chmod(dir, 0o555); err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { _ = os.Chmod(dir, 0o755) })
	_, err := os.Create(dir + "/f")
	if err == nil {
		t.Fatal("expected permission error")
	}
	wrapped := fmt.Errorf("vendorfile: create %s: %w", dir, err)
	if got := Hint(wrapped, dir, ""); got == "" {
		t.Fatalf("real wrapped EACCES not recognized: %v", wrapped)
	}
}
