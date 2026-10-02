import './globals.css';
import { NextIntlClientProvider } from 'next-intl';
import { getLocale, getMessages } from 'next-intl/server';
import { Sidebar } from '@/components/Sidebar';
import { Topbar } from '@/components/Topbar';

export const metadata = {
  title: 'GlobalInfra AI',
  description: 'Global Transportation Infrastructure Intelligence & Trusted Execution Platform',
  icons: { icon: '/favicon.svg' }
};

export default async function RootLayout({ children }: { children: React.ReactNode }) {
  const locale = await getLocale();
  const messages = await getMessages();
  return (
    <html lang={locale}>
      <body>
        <NextIntlClientProvider locale={locale} messages={messages}>
          <div className="shell">
            <Sidebar />
            <main className="main">
              <Topbar />
              <div className="content">{children}</div>
            </main>
          </div>
        </NextIntlClientProvider>
      </body>
    </html>
  );
}
