import './globals.css';
import './theme-light.css';
import { NextIntlClientProvider } from 'next-intl';
import { getLocale, getMessages } from 'next-intl/server';
import { Sidebar } from '@/components/Sidebar';
import { Topbar } from '@/components/Topbar';
import { ServiceWorkerRegistration } from '@/components/ServiceWorkerRegistration';
import { THEME_BOOT_SCRIPT } from '@/components/ThemeToggle';
import type { Metadata, Viewport } from 'next';

export const metadata: Metadata = {
  title: 'GlobalInfra AI',
  description: 'Global Transportation Infrastructure Intelligence & Trusted Execution Platform',
  manifest: '/manifest.webmanifest',
  appleWebApp: { capable: true, statusBarStyle: 'black-translucent', title: 'GlobalInfra AI' },
  formatDetection: { telephone: false },
  icons: { icon: '/favicon.svg', apple: '/icons/icon-192.png' }
};

export const viewport: Viewport = {
  width: 'device-width',
  initialScale: 1,
  maximumScale: 1,
  viewportFit: 'cover',
  themeColor: '#071016'
};

export default async function RootLayout({ children }: { children: React.ReactNode }) {
  const locale = await getLocale();
  const messages = await getMessages();
  return (
    <html lang={locale} suppressHydrationWarning>
      <head><script dangerouslySetInnerHTML={{ __html: THEME_BOOT_SCRIPT }} /></head>
      <body>
        <NextIntlClientProvider locale={locale} messages={messages}>
          <ServiceWorkerRegistration />
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
