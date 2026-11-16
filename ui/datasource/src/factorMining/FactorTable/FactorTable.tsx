import { Badge, Empty } from '../../components';
import type { FactorMiningFactor } from '../viewModels';
import styles from './FactorTable.module.css';

function value(number: number) { return new Intl.NumberFormat('en', { maximumSignificantDigits: 6 }).format(number); }
export function FactorTable({ factors, selected = '', onSelect }: { factors: FactorMiningFactor[]; selected?: string; onSelect?: (id: string) => void }) {
  if (!factors.length) return <section aria-labelledby="factor-table-title"><h3 id="factor-table-title">Factors and metrics</h3><Empty title="No factor metrics recorded">This run has boundary or implementation evidence only. It does not contain factor-performance results.</Empty></section>;
  const metrics = [...new Set(factors.flatMap(factor => Object.keys(factor.metrics)))];
  return <section aria-labelledby="factor-table-title"><h3 id="factor-table-title">Factors and metrics</h3>
    <p className={styles.note}>Select a factor to inspect its standalone results, combinations and contribution checks. Scalar metrics alone do not supply uncertainty.</p>
    {onSelect ? <label className={styles.inspect} htmlFor="factor-inspect">Inspect factor<select id="factor-inspect" value={selected} onChange={event => onSelect(event.target.value)}><option value="">All factors</option>{factors.map(factor => <option key={factor.id} value={factor.id}>{factor.id}</option>)}</select></label> : null}
    <div className={styles.wrap} role="region" aria-label="Factor metrics" tabIndex={0}><table><caption className="sr-only">Factor metrics</caption><thead><tr><th scope="col">Factor</th><th scope="col">Family</th><th scope="col">Status</th>{metrics.map(metric => <th scope="col" key={metric}>{metric}</th>)}<th scope="col">Formula evidence</th></tr></thead><tbody>{factors.map(factor => <tr key={factor.id}><th scope="row">{onSelect ? <button aria-label={`Inspect factor ${factor.id}`} aria-pressed={selected === factor.id} onClick={() => onSelect(factor.id)}>{factor.id}</button> : factor.id}</th><td>{factor.family}</td><td><Badge value={factor.status} /></td>{metrics.map(metric => <td className={styles.number} key={metric}>{factor.metrics[metric] == null ? '—' : value(factor.metrics[metric])}</td>)}<td><details><summary>Formula identity</summary><code>{factor.formulaSha256 ?? 'Not recorded'}</code></details></td></tr>)}</tbody></table></div>
  </section>;
}
