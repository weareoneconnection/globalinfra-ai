import Link from 'next/link';

export default function OfflinePage() {
  return <section className="offline-state card">
    <span className="offline-icon">GI</span>
    <div className="eyebrow">OFFLINE MODE · 离线模式</div>
    <h2 className="page-title">连接暂时中断</h2>
    <p className="page-subtitle">已缓存的应用界面仍可使用。恢复网络后，请重新载入以同步项目、数字孪生与审批数据。</p>
    <Link className="button" href="/">重新连接</Link>
  </section>;
}
