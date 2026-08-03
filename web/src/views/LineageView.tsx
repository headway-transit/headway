import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { ToggleButton } from "react-aria-components";
import { ApiError, getLineage } from "../api/client";
import type { LineageNode } from "../api/types";
import { Breadcrumbs } from "../components/Breadcrumbs";
import { LineageGraph } from "../components/LineageGraph";
import { RawRecordInspector } from "../components/RawRecordInspector";
import { Skeleton } from "../components/Skeleton";
import { copy } from "../copy";

/**
 * "Explain this number": renders the provenance tree the API serves for one
 * metric value, from the reported figure down to the raw records that
 * produced it (ADR-0007). The tree is displayed exactly as served — never
 * reshaped, filtered, or recomputed.
 *
 * Two equivalent renderings (handoff 0007, pillar 2), one always-visible
 * toggle apart:
 *  - the GRAPH view (default): an accessible, keyboard-navigable SVG flow of
 *    the three tiers (LineageGraph) — progressive enhancement;
 *  - the TEXT view: the full nested <ul>/<li> tree, unsummarized, with every
 *    node and complete record id. Nodes with inputs get a toggle button
 *    carrying aria-expanded; leaves (raw records) open into the inspector.
 *
 * Handoff 0035: the raw leaves are no longer dead ends. Each one opens into
 * the RawRecordInspector — label, integrity check, bounded preview, exact
 * bytes — and the graph view reaches the SAME inspector by selecting a raw
 * node, so neither rendering is the only way to inspect the evidence.
 *
 * The leaf opens ON DEMAND rather than loading every label with the tree:
 * a real trail bottoms out in hundreds or thousands of raw records, and
 * fetching a label for each one on page load is the mistake handoff 0030
 * spent a wave removing from /dq, in a new costume.
 */
export function LineageView() {
  const { id } = useParams<{ id: string }>();
  const [root, setRoot] = useState<LineageNode | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [view, setView] = useState<"graph" | "text">("graph");
  //: The raw record selected in the GRAPH view. The text view opens leaves
  //: in place; the graph reaches the same inspector through this panel, so
  //: both renderings have the same reach (handoff 0007 pillar 2 parity).
  const [selectedRaw, setSelectedRaw] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setRoot(null);
    setError(null);
    getLineage(id ?? "")
      .then((node) => {
        if (!cancelled) setRoot(node);
      })
      .catch((err) => {
        if (!cancelled)
          setError(err instanceof ApiError ? err.message : String(err));
      });
    return () => {
      cancelled = true;
    };
  }, [id]);

  return (
    <>
      {/* Deep-entity breadcrumb (handoff 0017 #4): the figure's receipt
          lives on /metrics; this page is the walk onward to raw records. */}
      <Breadcrumbs
        trail={[
          { label: copy.nav.metrics, to: "/metrics" },
          { label: `${copy.lineage.crumbFigure} ${id ?? ""}` },
          { label: copy.lineage.heading },
        ]}
      />
      <h1>{copy.lineage.heading}</h1>
      <p>{copy.lineage.intro}</p>
      <p>
        <Link to="/metrics">{copy.lineage.back}</Link>
      </p>
      {error && (
        <div role="alert" className="alert">
          {error}
        </div>
      )}
      {/* Skeleton (handoff 0021 #2): the tree's shape while it loads. */}
      {!root && !error && <Skeleton variant="table" count={5} />}
      {root && (
        <>
          {/* The toggle is ALWAYS visible: the graph is never the only path. */}
          <div
            className="view-toggle"
            role="group"
            aria-label={copy.lineage.graph.viewToggleLabel}
          >
            <ToggleButton
              isSelected={view === "graph"}
              onChange={(selected) => selected && setView("graph")}
            >
              {copy.lineage.graph.graphView}
            </ToggleButton>
            <ToggleButton
              isSelected={view === "text"}
              onChange={(selected) => selected && setView("text")}
            >
              {copy.lineage.graph.textView}
            </ToggleButton>
          </div>
          {view === "graph" ? (
            <>
              <LineageGraph root={root} onSelectRaw={setSelectedRaw} />
              {selectedRaw && (
                <section
                  className="lineage-raw-panel"
                  aria-label={copy.rawRecord.openLabel(selectedRaw)}
                >
                  <h2>
                    {copy.lineage.kindLabels["raw.records"]}{" "}
                    <code>{selectedRaw}</code>
                  </h2>
                  <button type="button" onClick={() => setSelectedRaw(null)}>
                    {copy.rawRecord.close}
                  </button>
                  <RawRecordInspector recordId={selectedRaw} />
                </section>
              )}
            </>
          ) : (
            <ul className="lineage-tree">
              <LineageTreeNode node={root} />
            </ul>
          )}
        </>
      )}
    </>
  );
}

function kindLabel(kind: string): string {
  return copy.lineage.kindLabels[kind] ?? kind;
}

function LineageTreeNode({ node }: { node: LineageNode }) {
  const [open, setOpen] = useState(true);
  //: Raw leaves open into the inspector, one at a time, on demand.
  const [inspecting, setInspecting] = useState(false);
  const inputs = node.inputs ?? [];
  const hasInputs = inputs.length > 0;
  const label = `${kindLabel(node.kind)} ${node.id}`;
  const isRaw = node.kind === "raw.records";

  return (
    <li className="lineage-node">
      <div className="node-head">
        <span className="kind">{kindLabel(node.kind)}</span>
        <span className="node-id">{node.id}</span>
        {node.transform_name && (
          <span className="transform">
            {copy.lineage.madeBy(
              node.transform_name,
              node.transform_version ?? "?",
            )}
          </span>
        )}
        {isRaw && <span className="transform">{copy.lineage.rawLeaf}</span>}
        {isRaw && (
          <button
            type="button"
            aria-expanded={inspecting}
            onClick={() => setInspecting((v) => !v)}
          >
            {inspecting
              ? copy.rawRecord.close
              : copy.rawRecord.openLabel(node.id)}
          </button>
        )}
        {hasInputs && (
          <button
            type="button"
            aria-expanded={open}
            onClick={() => setOpen((v) => !v)}
          >
            {copy.lineage.toggleInputs(label)}
          </button>
        )}
      </div>
      {isRaw && inspecting && <RawRecordInspector recordId={node.id} />}
      {hasInputs && open && (
        <ul>
          {inputs.map((input) => (
            <LineageTreeNode
              key={`${input.kind}:${input.id}`}
              node={input}
            />
          ))}
        </ul>
      )}
    </li>
  );
}
