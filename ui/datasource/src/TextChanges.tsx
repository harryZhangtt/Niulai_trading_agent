import { useState } from 'react';
import type { CapturedSummary, Comparison } from './types';

type Piece = { text: string; changed: boolean };

// Inputs are bounded by the API; cap the alignment as well to keep unusually
// fragmented text from blocking the inspector. Above the cap, show block changes.
function align(a: string, b: string): { A: Piece[]; B: Piece[] } {
  if (a === b) return { A: [{ text: a, changed: false }], B: [{ text: b, changed: false }] };
  const left = a.match(/\S+\s*|\s+/g) ?? [];
  const right = b.match(/\S+\s*|\s+/g) ?? [];
  if (left.length > 400 || right.length > 400) return { A: [{ text: a, changed: true }], B: [{ text: b, changed: true }] };
  const width = right.length + 1;
  const grid = new Uint16Array((left.length + 1) * width);
  for (let i = left.length - 1; i >= 0; i--) {
    for (let j = right.length - 1; j >= 0; j--) {
      grid[i * width + j] = left[i] === right[j] ? grid[(i + 1) * width + j + 1] + 1 : Math.max(grid[(i + 1) * width + j], grid[i * width + j + 1]);
    }
  }
  const result: { A: Piece[]; B: Piece[] } = { A: [], B: [] };
  let i = 0;
  let j = 0;
  while (i < left.length || j < right.length) {
    if (i < left.length && j < right.length && left[i] === right[j]) {
      result.A.push({ text: left[i++], changed: false });
      result.B.push({ text: right[j++], changed: false });
    } else if (i < left.length && (j >= right.length || grid[(i + 1) * width + j] >= grid[i * width + j + 1])) {
      result.A.push({ text: left[i++], changed: true });
    } else {
      result.B.push({ text: right[j++], changed: true });
    }
  }
  return result;
}

function Passage({ pieces, arm, value }: { pieces?: Piece[]; arm: 'A' | 'B'; value: string | null }) {
  return value === null ? <p className="text-unknown">Unknown — no captured summary recorded.</p> : value === '' ? <p className="text-unknown">Empty in the captured summary.</p> : <p className="diff-passage">{pieces ? pieces.map((piece, index) => piece.changed ? arm === 'A' ? <del key={index}>{piece.text}</del> : <ins key={index}>{piece.text}</ins> : piece.text) : value}</p>;
}

function field(summary: CapturedSummary | null | undefined, key: keyof CapturedSummary): string | null {
  if (!summary) return null;
  const value = summary[key];
  return Array.isArray(value) ? value.join('\n') : value;
}

function SummaryComparison({ A, B }: { A?: CapturedSummary | null; B?: CapturedSummary | null }) {
  const fields: Array<{ key: keyof CapturedSummary; title: string }> = [
    { key: 'incremental_contribution', title: 'Incremental contribution' },
    { key: 'economic_inference', title: 'Economic inference' },
    { key: 'unproved_links', title: 'Unproved links' },
  ];
  return <div className="text-change-content"><p className="text-diff-boundary">Passages from captured worker proposals. Highlighting shows wording changes; it does not establish new information or a better conclusion.</p><div className="text-diff-legend"><span><del>A-only text removed</del></span><span><ins>B-only text added</ins></span></div>
    {fields.map(({ key, title }) => {
      const left = field(A, key);
      const right = field(B, key);
      const pieces = left !== null && right !== null ? align(left, right) : undefined;
      return <section className="text-diff-field" key={key}><h4>{title}</h4>{!pieces ? <p className="diff-incomplete">Missing text prevents alignment for this field.</p> : null}<div className="text-diff-columns"><div className="text-arm text-arm-a"><span className="text-arm-name">A</span><Passage value={left} pieces={pieces?.A} arm="A" /></div><div className="text-arm text-arm-b"><span className="text-arm-name">B</span><Passage value={right} pieces={pieces?.B} arm="B" /></div></div></section>;
    })}</div>;
}

function CaseTextChanges({ row }: { row: Comparison['rows'][number] }) {
  const [open, setOpen] = useState(false);
  return <details className="case-text-changes" onToggle={event => setOpen(event.currentTarget.open)}><summary><span>{row.case_id}</span><span>Compare captured summaries</span></summary>{open ? <SummaryComparison A={row.A.summary} B={row.B.summary} /> : null}</details>;
}

export default function TextChanges({ comparison }: { comparison: Comparison }) {
  return <section className="text-changes" aria-labelledby="text-changes-title"><h3 id="text-changes-title">Text changes</h3><p className="subtle">Expand a matched case to inspect A and B in context.</p>{comparison.rows.map(row => <CaseTextChanges key={row.case_id} row={row} />)}</section>;
}
