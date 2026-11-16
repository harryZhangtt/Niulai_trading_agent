import { Badge, Empty } from '../../components';
import type { FactorMiningGate } from '../viewModels';
import styles from './GateTable.module.css';

export function GateTable({ gates, showEvidence = false }: { gates: FactorMiningGate[]; showEvidence?: boolean }) {
  return <section aria-labelledby="factor-gate-title"><h3 id="factor-gate-title">Admission gates</h3>
    <p className={styles.note}>Implementation, predictive, economic and publication evidence are separate decisions. Missing or withheld evidence is not a pass.</p>
    {gates.length ? <div className={styles.wrap} role="region" aria-label="Factor admission gates" tabIndex={0}><table><caption className="sr-only">Factor admission gates</caption><thead><tr><th scope="col">Dimension</th><th scope="col">Gate</th><th scope="col">Status</th><th scope="col">Reason</th>{showEvidence ? <th scope="col">Evidence identity</th> : null}</tr></thead><tbody>{gates.map(gate => <tr key={gate.id}><td>{gate.dimension}</td><th scope="row">{gate.id}</th><td><Badge value={gate.status} /></td><td>{gate.reasonCode ? <><span>{gate.reasonCode.replaceAll('_', ' ').replaceAll('-', ' ')}</span><details><summary>Reason code</summary><code>{gate.reasonCode}</code></details></> : 'Not decided'}</td>{showEvidence ? <td><code>{gate.evidenceSha256 ?? 'No evidence identity'}</code></td> : null}</tr>)}</tbody></table></div> : <Empty title="No admission gate evidence">No admission decisions were recorded in this manifest.</Empty>}
  </section>;
}
