import { Icon } from './components';

type Workspace = 'research' | 'factor' | 'scheduler';
const destinations: Array<{ id: Workspace; href: string; title: string; label: string; icon: 'sources' | 'compare' | 'layers' }> = [
  { id: 'research', href: '/datasource', title: 'Research evidence', label: 'Research', icon: 'sources' },
  { id: 'factor', href: '/factor-mining', title: 'Factor mining', label: 'Factors', icon: 'compare' },
  { id: 'scheduler', href: '/scheduler', title: 'Scheduler', label: 'Scheduler', icon: 'layers' },
];

export default function WorkspaceChrome({ active }: { active: Workspace }) {
  return <>
    <header className="app-header workspace-rail">
      <a className="app-identity" href="/datasource" aria-label="Research operations"><span className="identity-symbol"><Icon name="layers" size={25} /></span><span className="sr-only">Research operations</span></a>
      <nav className="workspace-nav" aria-label="Workspace">
        {destinations.map(item => <a key={item.id} href={item.href} title={item.title} aria-label={item.title} aria-current={active === item.id ? 'page' : undefined}><Icon name={item.icon} size={23} /><span aria-hidden="true">{item.label}</span></a>)}
      </nav>
      <span className="workspace-rail-boundary">Local<br />read-only</span>
    </header>
    <div className="workspace-topbar"><span>Research operations</span><span className="read-only"><Icon name="check" size={15} />Read-only workspace</span></div>
  </>;
}
