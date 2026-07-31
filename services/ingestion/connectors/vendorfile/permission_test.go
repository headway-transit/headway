package vendorfile

// Permission-error message tests (handoff 0037, design point 4, binding):
// no bare "permission denied" ever reaches the operator — every permission
// failure on the drop directory names the actual paths involved and prints
// the exact least-privilege fix command (sudo chown -R 65532:65532 <dir>)
// plus one line of why. These tests pin the message CONTENT, because the
// message is the product: the first live agency install was blocked on
// exactly these paths and the interim field advice was chmod 777.

import (
	"context"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

const wantFix = "sudo chown -R 65532:65532 deploy/compose/vendor-drop"

func skipIfRoot(t *testing.T) {
	t.Helper()
	if os.Geteuid() == 0 {
		t.Skip("running as root: permission errors cannot be produced")
	}
}

func assertPermissionMessage(t *testing.T, err error, failingPath string) {
	t.Helper()
	if err == nil {
		t.Fatal("expected a permission error, got nil")
	}
	msg := err.Error()
	t.Logf("operator-facing error as printed:\n%s", msg)
	for _, want := range []string{
		failingPath,                // the actual path involved
		wantFix,                    // the exact fix command, host-side path
		"locked-down user account", // the one-line why
		"Do not use chmod 777",     // the bad field advice, refused by name
	} {
		if !strings.Contains(msg, want) {
			t.Errorf("permission error missing %q\ngot: %s", want, msg)
		}
	}
}

// The connector cannot CREATE processed/ under a read-only drop dir — the
// exact first-agency blocker.
func TestUnwritableDropDirPrintsFixForProcessedDir(t *testing.T) {
	skipIfRoot(t)
	s, _, _, dir := newTestScanner(t)
	s.HostDir = "deploy/compose/vendor-drop"
	dropFile(t, dir, "export.csv", vendorCSV)

	if err := s.ScanOnce(context.Background()); err != nil {
		t.Fatalf("observation scan: %v", err)
	}
	if err := os.Chmod(dir, 0o555); err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { _ = os.Chmod(dir, 0o755) })

	err := s.ScanOnce(context.Background())
	assertPermissionMessage(t, err, filepath.Join(dir, ProcessedDir))
}

// The connector cannot READ a drop file owned by another account.
func TestUnreadableDropFilePrintsFix(t *testing.T) {
	skipIfRoot(t)
	s, fakeProd, _, dir := newTestScanner(t)
	s.HostDir = "deploy/compose/vendor-drop"
	path := dropFile(t, dir, "export.csv", vendorCSV)
	if err := os.Chmod(path, 0o000); err != nil {
		t.Fatal(err)
	}

	err := scanTwice(t, s)
	assertPermissionMessage(t, err, path)
	if len(fakeProd.Messages()) != 0 {
		t.Fatal("unreadable file still produced an envelope")
	}
}

// The connector cannot LIST an unreadable drop dir. Without the explicit
// check, filepath.Glob silently reports "no files" on a root-owned dir and
// the connector idles forever — the silent version of the same failure.
func TestUnreadableDropDirFailsLoudlyWithFix(t *testing.T) {
	skipIfRoot(t)
	s, _, _, dir := newTestScanner(t)
	s.HostDir = "deploy/compose/vendor-drop"
	if err := os.Chmod(dir, 0o000); err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { _ = os.Chmod(dir, 0o755) })

	err := s.ScanOnce(context.Background())
	assertPermissionMessage(t, err, dir)
}

// Without a host-dir hint the fix command still prints, against the path
// the connector sees, with the mount relationship stated honestly.
func TestFixWithoutHostDirNamesContainerMount(t *testing.T) {
	skipIfRoot(t)
	s, _, _, dir := newTestScanner(t)
	if err := os.Chmod(dir, 0o000); err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { _ = os.Chmod(dir, 0o755) })

	err := s.ScanOnce(context.Background())
	if err == nil {
		t.Fatal("expected a permission error")
	}
	if !strings.Contains(err.Error(), "sudo chown -R 65532:65532 "+dir) {
		t.Errorf("fix command missing without host hint: %s", err)
	}
	if !strings.Contains(err.Error(), "mounted at "+dir+" in the collector container") {
		t.Errorf("mount explanation missing: %s", err)
	}
}
