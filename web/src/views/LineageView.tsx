import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { ApiError, getLineage } from "../api/client";
import type { LineageNode } from "../api/types";
import { copy } from "../copy";

/**
 * "Explain this number": renders the provenance tree the API serves for one
 * metric value, from the reported figure down to the raw records that
 * produced it (ADR-0007). The tree is displayed exactly as served — never
 * reshaped, filtered, or recomputed.
 *
 * Accessible structure: nested <ul>/<li>. Nodes with inputs get a toggle
 * button carrying aria-expanded; leaves (raw records) are plain items.
 */
export function LineageView() {
  const { id } = useParams<{ id: string }>();
  const [root, setRoot] = useState<LineageNode | null>(null);
  const [error, setError] = useState<string | null>(null);

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
      {!root && !error && <p>{copy.loading}</p>}
      {root && (
        <ul className="lineage-tree">
          <LineageTreeNode node={root} />
        </ul>
      )}
    </>
  );
}

function kindLabel(kind: string): string {
  return copy.lineage.kindLabels[kind] ?? kind;
}

function LineageTreeNode({ node }: { node: LineageNode }) {
  const [open, setOpen] = useState(true);
  const inputs = node.inputs ?? [];
  const hasInputs = inputs.length > 0;
  const label = `${kindLabel(node.kind)} ${node.id}`;

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
        {node.kind === "raw.records" && (
          <span className="transform">{copy.lineage.rawLeaf}</span>
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
