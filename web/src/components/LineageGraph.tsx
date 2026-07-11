/**
 * The lineage walk, drawn (handoff 0007, pillar 2): a hand-rolled, accessible
 * SVG flow of the provenance tree the API serves — three tiers:
 *
 *   reported figure  →  processing steps (transform name + version)  →  raw records
 *
 * The raw tier starts collapsed as a single count node ("326 raw records")
 * and expands in pages of 20. Keyboard: arrow keys move up/down within a
 * tier and left/right between tiers (roving tabindex); Enter or Space
 * toggles the raw group / shows the next page; every node has an accessible
 * name; focus is drawn visibly on the node.
 *
 * This graph is progressive enhancement, NEVER the only path: LineageView
 * keeps the full nested-list text tree one always-visible toggle away, and
 * that text tree remains the complete, unsummarized rendering (every
 * intermediate canonical row and full record id). The graph draws the same
 * served tree — it computes nothing and never reshapes the data beyond
 * grouping for display. No charting library: plain SVG + existing tokens.
 */

import { useMemo, useRef, useState } from "react";
import type { KeyboardEvent } from "react";
import type { LineageNode } from "../api/types";
import { copy } from "../copy";

const PAGE_SIZE = 20;

const NODE_W = 250;
const NODE_H = 54;
const V_GAP = 14;
const COL_GAP = 90;
const PAD = 16;
const HEADER_H = 28;

interface GraphNodeSpec {
  key: string;
  /** Full accessible name — never truncated. */
  name: string;
  line1: string;
  line2?: string;
  role: "img" | "button";
  expanded?: boolean;
  onActivate?: () => void;
  variant: "metric" | "transform" | "raw-group" | "raw" | "more";
}

interface GraphSummary {
  rootId: string;
  rootKindLabel: string;
  transforms: { name: string; version: string; produced: number }[];
  rawIds: string[];
}

/**
 * Read the served tree into the three tiers. Grouping only — nothing is
 * computed or dropped: transforms are the distinct (name, version) pairs
 * with how many records each produced in this trail; raw ids are every
 * distinct raw.records leaf. The text tree shows the same data unsummarized.
 */
function summarize(root: LineageNode): GraphSummary {
  const transforms = new Map<
    string,
    { name: string; version: string; produced: number }
  >();
  const rawIds: string[] = [];
  const seenRaw = new Set<string>();

  const visit = (node: LineageNode) => {
    if (node.transform_name) {
      const version = node.transform_version ?? "?";
      const key = `${node.transform_name}@${version}`;
      const entry = transforms.get(key) ?? {
        name: node.transform_name,
        version,
        produced: 0,
      };
      entry.produced += 1;
      transforms.set(key, entry);
    }
    if (node.kind === "raw.records" && !seenRaw.has(node.id)) {
      seenRaw.add(node.id);
      rawIds.push(node.id);
    }
    for (const input of node.inputs ?? []) visit(input);
  };
  visit(root);

  return {
    rootId: root.id,
    rootKindLabel: copy.lineage.kindLabels[root.kind] ?? root.kind,
    transforms: [...transforms.values()],
    rawIds,
  };
}

/** Visual truncation only: the full id stays in the accessible name and in the text view. */
function shortId(id: string): string {
  return id.length > 26 ? `${id.slice(0, 25)}…` : id;
}

export function LineageGraph({ root }: { root: LineageNode }) {
  const summary = useMemo(() => summarize(root), [root]);
  const [rawExpanded, setRawExpanded] = useState(false);
  const [rawShown, setRawShown] = useState(PAGE_SIZE);
  // Roving tabindex: the key of the node that owns Tab focus.
  const [activeKey, setActiveKey] = useState("metric");
  const nodeRefs = useRef(new Map<string, SVGGElement>());

  const totalRaw = summary.rawIds.length;
  const visibleRaw = rawExpanded ? summary.rawIds.slice(0, rawShown) : [];
  const hasMore = rawExpanded && rawShown < totalRaw;

  // ---- the three tiers as node specs ----
  const metricColumn: GraphNodeSpec[] = [
    {
      key: "metric",
      name: copy.lineage.graph.metricNode(summary.rootId),
      line1: summary.rootKindLabel,
      line2: shortId(summary.rootId),
      role: "img",
      variant: "metric",
    },
  ];

  const transformColumn: GraphNodeSpec[] = summary.transforms.map((t, i) => ({
    key: `transform:${i}`,
    name: copy.lineage.graph.transformNode(
      t.name,
      t.version,
      String(t.produced),
    ),
    line1: t.name,
    line2: copy.lineage.graph.transformDetail(t.version, String(t.produced)),
    role: "img",
    variant: "transform",
  }));

  const rawColumn: GraphNodeSpec[] = [
    {
      key: "raw-group",
      name: `${copy.lineage.graph.rawGroupNode(String(totalRaw))}. ${copy.lineage.graph.rawGroupHint}`,
      line1: copy.lineage.graph.rawGroupNode(String(totalRaw)),
      role: "button",
      expanded: rawExpanded,
      onActivate: () => setRawExpanded((v) => !v),
      variant: "raw-group",
    },
    ...visibleRaw.map(
      (id): GraphNodeSpec => ({
        key: `raw:${id}`,
        name: copy.lineage.graph.rawNode(id),
        line1: shortId(id),
        line2: copy.lineage.kindLabels["raw.records"],
        role: "img",
        variant: "raw",
      }),
    ),
    ...(hasMore
      ? [
          {
            key: "raw-more",
            name: copy.lineage.graph.showMore(
              String(visibleRaw.length),
              String(totalRaw),
            ),
            line1: copy.lineage.graph.showMore(
              String(visibleRaw.length),
              String(totalRaw),
            ),
            role: "button" as const,
            onActivate: () => setRawShown((n) => n + PAGE_SIZE),
            variant: "more" as const,
          },
        ]
      : []),
  ];

  const columns = [metricColumn, transformColumn, rawColumn];
  const columnHeadings = [
    copy.lineage.graph.tierMetric,
    copy.lineage.graph.tierTransforms,
    copy.lineage.graph.tierRaw,
  ];

  // ---- geometry ----
  const colX = (col: number) => PAD + col * (NODE_W + COL_GAP);
  const rowY = (row: number) => PAD + HEADER_H + row * (NODE_H + V_GAP);
  const width = PAD * 2 + 3 * NODE_W + 2 * COL_GAP;
  const maxRows = Math.max(...columns.map((c) => c.length), 1);
  const height = PAD * 2 + HEADER_H + maxRows * (NODE_H + V_GAP) - V_GAP;

  // ---- keyboard: arrows within/between tiers, Enter/Space activates ----
  const findPos = (key: string): [number, number] => {
    for (let c = 0; c < columns.length; c++) {
      const r = columns[c].findIndex((n) => n.key === key);
      if (r >= 0) return [c, r];
    }
    return [0, 0];
  };

  const focusNode = (col: number, row: number) => {
    const column = columns[col];
    if (column.length === 0) return;
    const node = column[Math.max(0, Math.min(row, column.length - 1))];
    setActiveKey(node.key);
    nodeRefs.current.get(node.key)?.focus();
  };

  const onKeyDown = (event: KeyboardEvent<SVGSVGElement>) => {
    const [col, row] = findPos(activeKey);
    switch (event.key) {
      case "ArrowDown":
        event.preventDefault();
        focusNode(col, row + 1);
        break;
      case "ArrowUp":
        event.preventDefault();
        focusNode(col, row - 1);
        break;
      case "ArrowRight":
        event.preventDefault();
        if (col < columns.length - 1) focusNode(col + 1, row);
        break;
      case "ArrowLeft":
        event.preventDefault();
        if (col > 0) focusNode(col - 1, row);
        break;
      case "Enter":
      case " ": {
        const node = columns[col][row];
        if (node?.onActivate) {
          event.preventDefault();
          node.onActivate();
        }
        break;
      }
    }
  };

  // The roving-tabindex owner must exist; after a collapse removes it, hand
  // Tab focus back to the raw group node.
  const activeExists = columns.some((c) => c.some((n) => n.key === activeKey));
  const tabOwner = activeExists ? activeKey : "raw-group";

  // ---- edges: metric → each transform → raw group → each shown raw ----
  const edges: { x1: number; y1: number; x2: number; y2: number }[] = [];
  for (let t = 0; t < transformColumn.length; t++) {
    edges.push({
      x1: colX(0) + NODE_W,
      y1: rowY(0) + NODE_H / 2,
      x2: colX(1),
      y2: rowY(t) + NODE_H / 2,
    });
    edges.push({
      x1: colX(1) + NODE_W,
      y1: rowY(t) + NODE_H / 2,
      x2: colX(2),
      y2: rowY(0) + NODE_H / 2,
    });
  }
  for (let r = 1; r < rawColumn.length; r++) {
    edges.push({
      x1: colX(2) + NODE_W / 2,
      y1: rowY(r - 1) + NODE_H,
      x2: colX(2) + NODE_W / 2,
      y2: rowY(r),
    });
  }

  return (
    <div className="lineage-graph-wrap">
      <p className="lineage-graph-instructions">
        {copy.lineage.graph.instructions}
      </p>
      <svg
        className="lineage-graph"
        role="group"
        aria-label={copy.lineage.graph.graphLabel}
        viewBox={`0 0 ${width} ${height}`}
        width={width}
        height={height}
        onKeyDown={onKeyDown}
      >
        {/* Tier headings — decorative repetition; every node names its tier. */}
        <g aria-hidden="true">
          {columnHeadings.map((heading, c) => (
            <text
              key={heading}
              className="graph-heading"
              x={colX(c)}
              y={PAD + HEADER_H - 12}
            >
              {heading}
            </text>
          ))}
        </g>
        <g aria-hidden="true">
          {edges.map((e, i) => (
            <line
              key={i}
              className="graph-edge"
              x1={e.x1}
              y1={e.y1}
              x2={e.x2}
              y2={e.y2}
            />
          ))}
        </g>
        {columns.map((column, c) =>
          column.map((node, r) => (
            <g
              key={node.key}
              ref={(el) => {
                if (el) nodeRefs.current.set(node.key, el);
                else nodeRefs.current.delete(node.key);
              }}
              className={`graph-node graph-node-${node.variant}`}
              role={node.role}
              aria-label={node.name}
              aria-expanded={node.role === "button" && node.expanded !== undefined ? node.expanded : undefined}
              tabIndex={node.key === tabOwner ? 0 : -1}
              // Any focus (mouse, Tab, or programmatic) hands the roving
              // tabindex to this node so the arrow keys continue from here.
              onFocus={() => setActiveKey(node.key)}
              onClick={() => {
                setActiveKey(node.key);
                node.onActivate?.();
              }}
            >
              <rect
                x={colX(c)}
                y={rowY(r)}
                width={NODE_W}
                height={NODE_H}
                rx={6}
              />
              <text
                className="graph-node-line1"
                x={colX(c) + 12}
                y={rowY(r) + (node.line2 ? 22 : 32)}
              >
                {node.line1}
              </text>
              {node.line2 && (
                <text
                  className="graph-node-line2"
                  x={colX(c) + 12}
                  y={rowY(r) + 42}
                >
                  {node.line2}
                </text>
              )}
            </g>
          )),
        )}
      </svg>
    </div>
  );
}
