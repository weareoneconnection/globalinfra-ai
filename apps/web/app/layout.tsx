import './globals.css';
import { Sidebar } from '@/components/Sidebar';
import { Topbar } from '@/components/Topbar';

export const metadata = {
  title: 'GlobalInfra AI',
  description: 'Global Transportation Infrastructure Intelligence & Trusted Execution Platform',
  icons: { icon: '/favicon.svg' }
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>
        <div className="shell">
          <Sidebar />
          <main className="main">
            <Topbar />
            <div className="content">{children}</div>
          </main>
        </div>
      </body>
    </html>
  );
}
