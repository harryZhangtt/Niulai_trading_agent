import { Badge, Empty } from '../../components';
import type { FactorMiningStage } from '../viewModels';
import styles from './StageProgress.module.css';

export function StageProgress({ stages, showReceipts = false }: { stages: FactorMiningStage[]; showReceipts?: boolean }) {
  return <section aria-labelledby="factor-stage-title"><h3 id="factor-stage-title">Pipeline stages</h3>
    {stages.length ? <ol className={styles.stages}>{stages.map(stage => <li key={stage.id}>
      <div><strong>{stage.id.replaceAll('-', ' ')}</strong><span>{stage.attempts} {stage.attempts === 1 ? 'attempt' : 'attempts'}</span>
        {stage.failureCode ? <code>{stage.failureCode}</code> : null}
        {showReceipts ? <details><summary>Stage receipt</summary><code>{stage.receiptSha256 ?? 'No receipt recorded'}</code></details> : null}
      </div><Badge value={stage.status} />
    </li>)}</ol> : <Empty title="No pipeline stage evidence">No stage records were published in this manifest.</Empty>}
  </section>;
}
