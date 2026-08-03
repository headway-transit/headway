// Package permsg turns a bare file-permission error on a drop-directory
// path into a message a transit-agency operator can act on (handoff 0037).
//
// The connectors run as uid 65532 — the fixed "nonroot" account of the
// distroless container image (services/ingestion/Dockerfile) — so a drop
// directory created by root (or any other account) on the host is
// unreadable/unwritable to them. The first live agency install hit exactly
// this, and the interim advice in the field was `chmod 777`, which is
// beneath the platform's security posture. The rule (handoff 0037, design
// point 4, binding): no generic "permission denied" ever reaches the
// operator bare — every permission error names the actual paths involved
// and prints the exact least-privilege command that fixes them, plus one
// line of why. Never 777.
package permsg

import (
	"errors"
	"fmt"
	"io/fs"
)

// UID is the fixed user id the connector containers run as: the "nonroot"
// user of gcr.io/distroless/static-debian12 (see services/ingestion/
// Dockerfile). It is a constant of the image, not configuration.
const UID = 65532

// Hint returns a plain-language explanation and the exact fix command when
// err is (or wraps) a file-permission error, and "" for every other error.
//
// dir is the drop directory as the connector sees it (the path inside the
// container, e.g. /data/tides-drop). hostDir, when known, is the same
// folder as the operator sees it on the host machine (the compose file
// passes it via TIDES_DROP_DIR_HOST / VENDOR_DROP_DIR_HOST; in the standard
// install it is deploy/compose/tides-drop under the Headway folder) — the
// fix command must name the host-side path, because that is where the
// operator's shell runs.
func Hint(err error, dir, hostDir string) string {
	if !errors.Is(err, fs.ErrPermission) {
		return ""
	}
	target := hostDir
	var where string
	switch {
	case target == "":
		// No host-side hint configured: name the container path honestly
		// and say which side of the mount the command applies to.
		target = dir
		where = fmt.Sprintf(" The path above is how the collector container "+
			"sees the folder; run the command against the folder on the host "+
			"machine that is mounted at %s in the collector container.", dir)
	case target[0] != '/':
		// Relative to the Headway checkout (the standard install wiring).
		where = fmt.Sprintf(" (%s is under your Headway folder — run the "+
			"command from there.)", target)
	}
	return fmt.Sprintf(" — HOW TO FIX THIS: Headway's collector runs as a "+
		"locked-down user account (user id %d) that cannot read or change "+
		"files owned by another account, such as root. Make the collector "+
		"the owner of the drop folder and everything in it by running this "+
		"one command on the Headway machine:  sudo chown -R %d:%d %s  "+
		"After that the collector picks the files up on its next scan "+
		"(within about a minute) — no restart needed.%s Do not use "+
		"chmod 777: it would let every account on the machine change your "+
		"agency's data files.", UID, UID, UID, target, where)
}
